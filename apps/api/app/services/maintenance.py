"""Daily data-lifecycle maintenance (invoked by the Lambda management command
{"futureroots_command": "maintenance"}, scheduled via EventBridge).

Everything here is idempotent and safe to run at any time, any number of
times. It mostly touches low-sensitivity operational rows. The ONE money-record
step is the financial-record retention purge below: it hard-deletes only
FULLY-SEVERED money rows (every subject FK already null, from a prior erasure)
that are past the counsel-set 7-year retention window — a record still tied to a
living user/child is NEVER purged. No money field is ever edited.

What runs, in one DB session / one commit:
- premium_gift_intents older than 30 days (abandoned-checkout staging rows
  that may hold a free-text message naming a child — storage limitation);
- premium_email_log rows older than 1 year (send-once dedupe rows; every kind
  can only re-fire within a window far shorter than a year — see
  run_lazy_lifecycle's recency guard for premium_ended);
- fund_nudges older than 30 days (the throttle only needs 7 days);
- abandoned video calls: an active call with no heartbeat for
  CALL_ABANDONED_AFTER is ended (nobody polled it, so the lazy read-time reap
  never saw it);
- call_participants / call_child_presence rows of calls that ended more than
  90 days ago ("who was on, when" history — retention bound);
- fully-severed financial rows (contributions, family_subscriptions,
  premium_grants, fund_ledger_entries whose account is severed) older than the
  7-year retention window (§3.D financial carve-out disposal).
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    CallChildPresence,
    CallParticipant,
    CallStatus,
    Contribution,
    FamilyCall,
    FamilySubscription,
    FundAccount,
    FundLedgerEntry,
    FundNudge,
    MemoryPrompt,
    Notification,
    PremiumEmailLog,
    PremiumGiftIntent,
    PremiumGrant,
    utcnow,
)
from .memory_prompts import run_memory_prompts
from .predictions import seal_due_prediction_rounds

logger = logging.getLogger(__name__)

GIFT_INTENT_RETENTION = timedelta(days=30)
PREMIUM_EMAIL_LOG_RETENTION = timedelta(days=365)
FUND_NUDGE_RETENTION = timedelta(days=30)
# The memory-prompt throttle only needs the current month; 90 days is a safe
# retention floor that keeps recent history for audit without accumulating.
MEMORY_PROMPT_RETENTION = timedelta(days=90)
CALL_HISTORY_RETENTION = timedelta(days=90)
# In-app bell notifications are transient — the bell shows recent activity, not
# an archive. Ninety days is plenty of scrollback.
NOTIFICATION_RETENTION = timedelta(days=90)
# An active call whose freshest heartbeat is older than this is abandoned.
# Presence heartbeats arrive every few seconds (agora_presence_ttl_seconds is
# 30s), so 15 minutes of silence means every participant is long gone.
CALL_ABANDONED_AFTER = timedelta(minutes=15)
# Financial records are retained (never cascade-deleted) on erasure under GDPR
# Art. 17(3)(b)/(e) with only the identity link severed (§3.D). This is the
# counsel-set duration (WS0) after which that legal basis lapses and a
# fully-severed money row may finally be disposed of — 7 years (US tax /
# CRA / EU member-state accounting retention floor).
FINANCIAL_RECORD_RETENTION_DAYS = 7 * 365


def _aware(dt: datetime) -> datetime:
    """SQLite (tests) drops tzinfo; normalize to aware UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def prune_gift_intents(db: Session) -> int:
    """Delete gift-intent staging rows older than 30 days (abandoned checkouts
    leave harmless orphans; settled gifts have already copied the message onto
    the grant). Shared by the admin endpoint and the daily maintenance run."""
    cutoff = utcnow() - GIFT_INTENT_RETENTION
    return (
        db.query(PremiumGiftIntent)
        .filter(PremiumGiftIntent.created_at < cutoff)
        .delete(synchronize_session=False)
    )


def call_is_abandoned(db: Session, call: FamilyCall, now: datetime | None = None) -> bool:
    """True when nothing has heartbeat the call for CALL_ABANDONED_AFTER.
    The freshest signal is the newest participant heartbeat; a call that never
    got a participant falls back to its start time."""
    now = now or utcnow()
    last_seen = (
        db.query(func.max(CallParticipant.last_seen_at))
        .filter(CallParticipant.call_id == call.id)
        .scalar()
    )
    return _aware(last_seen or call.started_at) < now - CALL_ABANDONED_AFTER


def end_abandoned_calls(db: Session) -> int:
    """End every active call nobody has polled: same terminal state as the
    router's _end_call (status=ended, active slot released, child presence
    cleared), plus left_at stamped on lingering participants so the adult
    history stays coherent. Returns the number of calls ended."""
    now = utcnow()
    ended = 0
    active = db.query(FamilyCall).filter(FamilyCall.status == CallStatus.active).all()
    for call in active:
        if not call_is_abandoned(db, call, now):
            continue
        db.query(FamilyCall).filter(
            FamilyCall.id == call.id, FamilyCall.status == CallStatus.active
        ).update(
            {
                FamilyCall.status: CallStatus.ended,
                FamilyCall.active_family_id: None,
                FamilyCall.ended_at: now,
            },
            synchronize_session=False,
        )
        db.query(CallChildPresence).filter(CallChildPresence.call_id == call.id).delete(
            synchronize_session=False
        )
        db.query(CallParticipant).filter(
            CallParticipant.call_id == call.id, CallParticipant.left_at.is_(None)
        ).update({CallParticipant.left_at: now}, synchronize_session=False)
        ended += 1
    return ended


def run_maintenance(db: Session) -> dict[str, int]:
    """The daily sweep. One session, one commit, a one-line count summary."""
    now = utcnow()

    # Future Predictions: seal every round due on/before today (opens next
    # rounds, releases at 18). Its own commit + post-commit notification
    # delivery, run before the prunes so batches follow the post-commit rule.
    prediction_counts, prediction_batches = seal_due_prediction_rounds(db)
    db.commit()
    for batch in prediction_batches:
        batch.deliver(db)

    gift_intents = prune_gift_intents(db)

    email_log = (
        db.query(PremiumEmailLog)
        .filter(PremiumEmailLog.sent_at < now - PREMIUM_EMAIL_LOG_RETENTION)
        .delete(synchronize_session=False)
    )

    # Storage limitation: the nudge throttle only needs the last 7 days, and
    # re-nudges refresh created_at in place, so anything older is inert.
    fund_nudges = (
        db.query(FundNudge)
        .filter(FundNudge.created_at < now - FUND_NUDGE_RETENTION)
        .delete(synchronize_session=False)
    )

    # Memory-request throttle rows older than 90 days (the once-per-month claim
    # only needs the current month; mirror the fund_nudges prune).
    memory_prompts_pruned = (
        db.query(MemoryPrompt)
        .filter(MemoryPrompt.created_at < now - MEMORY_PROMPT_RETENTION)
        .delete(synchronize_session=False)
    )

    # In-app bell notifications older than 90 days (transient activity feed).
    notifications_pruned = (
        db.query(Notification)
        .filter(Notification.created_at < now - NOTIFICATION_RETENTION)
        .delete(synchronize_session=False)
    )

    # Financial-record 7-year retention purge (§3.D disposal, counsel WS0).
    # HARD-DELETE only FULLY-SEVERED money rows past the window — rows where every
    # subject FK is already null (severed at a prior erasure), so a record still
    # tied to a living user/child is NEVER purged and no money field is edited.
    # Ordered ledger-entries -> contributions so a ledger entry's
    # source_contribution_id FK (bare NO ACTION) can never dangle when its
    # contribution is deleted. The ledger purge deletes severed-account entries
    # that are past the window OR that point at a contribution being purged this
    # run -- the latter closes a timestamp-skew gap: a contribution and its
    # ledger entry are created seconds/hours apart (checkout vs. webhook), so on
    # the one run where the cutoff falls between them the contribution would
    # qualify while its still-referencing ledger entry did not.
    fin_cutoff = now - timedelta(days=FINANCIAL_RECORD_RETENTION_DAYS)
    severed_accounts = select(FundAccount.id).where(FundAccount.child_id.is_(None))
    purged_contribution_ids = select(Contribution.id).where(
        Contribution.contributor_user_id.is_(None),
        Contribution.child_id.is_(None),
        Contribution.created_at < fin_cutoff,
    )
    fund_ledger_entries_purged = (
        db.query(FundLedgerEntry)
        .filter(
            FundLedgerEntry.account_id.in_(severed_accounts),
            or_(
                FundLedgerEntry.created_at < fin_cutoff,
                FundLedgerEntry.source_contribution_id.in_(purged_contribution_ids),
            ),
        )
        .delete(synchronize_session=False)
    )
    contributions_purged = (
        db.query(Contribution)
        .filter(
            Contribution.contributor_user_id.is_(None),
            Contribution.child_id.is_(None),
            Contribution.created_at < fin_cutoff,
        )
        .delete(synchronize_session=False)
    )
    family_subscriptions_purged = (
        db.query(FamilySubscription)
        .filter(
            FamilySubscription.family_id.is_(None),
            FamilySubscription.owner_user_id.is_(None),
            FamilySubscription.created_at < fin_cutoff,
        )
        .delete(synchronize_session=False)
    )
    premium_grants_purged = (
        db.query(PremiumGrant)
        .filter(
            PremiumGrant.family_id.is_(None),
            PremiumGrant.granted_by_user_id.is_(None),
            PremiumGrant.created_at < fin_cutoff,
        )
        .delete(synchronize_session=False)
    )

    # End abandoned calls BEFORE the history prune so their retention clock
    # starts at today's ended_at.
    abandoned_calls = end_abandoned_calls(db)

    history_cutoff = now - CALL_HISTORY_RETENTION
    old_calls = select(FamilyCall.id).where(
        FamilyCall.ended_at.is_not(None), FamilyCall.ended_at < history_cutoff
    )
    participants = (
        db.query(CallParticipant)
        .filter(CallParticipant.call_id.in_(old_calls))
        .delete(synchronize_session=False)
    )
    presence = (
        db.query(CallChildPresence)
        .filter(
            or_(
                CallChildPresence.call_id.in_(old_calls),
                CallChildPresence.created_at < history_cutoff,  # belt and braces
            )
        )
        .delete(synchronize_session=False)
    )

    db.commit()

    # Monthly Memory Request: system-initiated notify with its own commit +
    # post-commit delivery (the FundNudge idiom), run after the prunes commit.
    # Idempotent — at most one prompt per member per family per month.
    memory_prompts_sent = run_memory_prompts(db)

    counts = {
        "gift_intents_pruned": gift_intents,
        "premium_email_log_pruned": email_log,
        "fund_nudges_pruned": fund_nudges,
        "memory_prompts_pruned": memory_prompts_pruned,
        "memory_prompts_sent": memory_prompts_sent,
        "notifications_pruned": notifications_pruned,
        "contributions_purged": contributions_purged,
        "family_subscriptions_purged": family_subscriptions_purged,
        "premium_grants_purged": premium_grants_purged,
        "fund_ledger_entries_purged": fund_ledger_entries_purged,
        "abandoned_calls_ended": abandoned_calls,
        "call_participants_pruned": participants,
        "call_child_presence_pruned": presence,
        **prediction_counts,
    }
    logger.info(
        "maintenance: %s",
        " ".join(f"{k}={v}" for k, v in counts.items()),
    )
    return counts
