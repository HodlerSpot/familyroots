"""Daily data-lifecycle maintenance (invoked by the Lambda management command
{"futureroots_command": "maintenance"}, scheduled via EventBridge).

Everything here is idempotent and safe to run at any time, any number of
times. It only ever touches low-sensitivity operational rows — never money
records: contributions and fund_ledger_entries are financial records and are
NEVER pruned here.

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
  90 days ago ("who was on, when" history — retention bound).
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    CallChildPresence,
    CallParticipant,
    CallStatus,
    FamilyCall,
    FundNudge,
    PremiumEmailLog,
    PremiumGiftIntent,
    utcnow,
)

logger = logging.getLogger(__name__)

GIFT_INTENT_RETENTION = timedelta(days=30)
PREMIUM_EMAIL_LOG_RETENTION = timedelta(days=365)
FUND_NUDGE_RETENTION = timedelta(days=30)
CALL_HISTORY_RETENTION = timedelta(days=90)
# An active call whose freshest heartbeat is older than this is abandoned.
# Presence heartbeats arrive every few seconds (agora_presence_ttl_seconds is
# 30s), so 15 minutes of silence means every participant is long gone.
CALL_ABANDONED_AFTER = timedelta(minutes=15)


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

    counts = {
        "gift_intents_pruned": gift_intents,
        "premium_email_log_pruned": email_log,
        "fund_nudges_pruned": fund_nudges,
        "abandoned_calls_ended": abandoned_calls,
        "call_participants_pruned": participants,
        "call_child_presence_pruned": presence,
    }
    db.commit()
    logger.info(
        "maintenance: %s",
        " ".join(f"{k}={v}" for k, v in counts.items()),
    )
    return counts
