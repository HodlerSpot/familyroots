"""The daily maintenance sweep (Lambda {"futureroots_command": "maintenance"}):
retention prunes + the abandoned-call cap, all idempotent."""

import uuid
from datetime import timedelta

from app.models import (
    CallChildPresence,
    CallParticipant,
    CallStatus,
    Contribution,
    ContributionStatus,
    FamilyCall,
    FamilySubscription,
    FundAccount,
    FundAccountStatus,
    FundLedgerEntry,
    FundNudge,
    LedgerEntryType,
    PremiumEmailLog,
    PremiumGiftIntent,
    PremiumGrant,
    SubscriptionPlan,
    SubscriptionStatus,
    User,
    utcnow,
)
from app.services.maintenance import FINANCIAL_RECORD_RETENTION_DAYS, run_maintenance

from .conftest import TestingSession, add_child, create_family, signup


def _seed(client):
    """Two families; for each table one row that should be swept and one that
    should survive."""
    parent = signup(client, "parent@example.com")
    family_a = create_family(client, parent, "A")
    family_b = create_family(client, parent, "B")
    child_1 = add_child(client, parent, family_a, "Ana")
    child_2 = add_child(client, parent, family_a, "Ben")

    now = utcnow()
    with TestingSession() as db:
        user = db.query(User).one()
        fid_a, fid_b = uuid.UUID(family_a), uuid.UUID(family_b)
        cid_1, cid_2 = uuid.UUID(child_1), uuid.UUID(child_2)

        # gift intents: stale (31d) vs fresh
        db.add(PremiumGiftIntent(
            family_id=fid_a, gifter_user_id=user.id,
            stripe_checkout_session_id="cs_old",
            created_at=now - timedelta(days=31),
        ))
        db.add(PremiumGiftIntent(
            family_id=fid_a, gifter_user_id=user.id,
            stripe_checkout_session_id="cs_new",
        ))

        # premium email log: stale (400d) vs fresh
        db.add(PremiumEmailLog(
            family_id=fid_a, kind="premium_ended", dedupe_key="old",
            sent_at=now - timedelta(days=400),
        ))
        db.add(PremiumEmailLog(family_id=fid_a, kind="premium_ended", dedupe_key="new"))

        # fund nudges: stale (31d) vs fresh (throttle only needs 7 days)
        db.add(FundNudge(child_id=cid_1, user_id=user.id,
                         created_at=now - timedelta(days=31)))
        db.add(FundNudge(child_id=cid_2, user_id=user.id))

        # Family A: an ABANDONED active call (last heartbeat 2h ago) — nobody
        # ever polls it, so only maintenance can end it.
        abandoned = FamilyCall(
            family_id=fid_a, active_family_id=fid_a, channel_name="fr-abandoned",
            started_by=user.id, started_at=now - timedelta(hours=3),
        )
        db.add(abandoned)
        db.flush()
        db.add(CallParticipant(
            call_id=abandoned.id, user_id=user.id, agora_uid=101,
            joined_at=now - timedelta(hours=3),
            last_seen_at=now - timedelta(hours=2),
        ))
        db.add(CallChildPresence(call_id=abandoned.id, child_id=cid_1, marked_by=user.id))

        # Family B: a LIVE active call with a fresh heartbeat — must survive.
        live = FamilyCall(
            family_id=fid_b, active_family_id=fid_b, channel_name="fr-live",
            started_by=user.id,
        )
        db.add(live)
        db.flush()
        db.add(CallParticipant(call_id=live.id, user_id=user.id, agora_uid=102))

        # Family A: a call that ended 100 days ago — its "who was on, when"
        # history is past the 90-day retention bound.
        ancient = FamilyCall(
            family_id=fid_a, active_family_id=None, channel_name="fr-ancient",
            status=CallStatus.ended, started_by=user.id,
            started_at=now - timedelta(days=100, hours=1),
            ended_at=now - timedelta(days=100),
        )
        db.add(ancient)
        db.flush()
        db.add(CallParticipant(
            call_id=ancient.id, user_id=user.id, agora_uid=103,
            joined_at=now - timedelta(days=100, hours=1),
            last_seen_at=now - timedelta(days=100),
            left_at=now - timedelta(days=100),
        ))
        db.add(CallChildPresence(
            call_id=ancient.id, child_id=cid_1, marked_by=user.id,
            created_at=now - timedelta(days=100),
        ))
        db.commit()


def test_maintenance_sweeps_everything_and_is_idempotent(client):
    _seed(client)

    with TestingSession() as db:
        counts = run_maintenance(db)
    assert counts == {
        "gift_intents_pruned": 1,
        "premium_email_log_pruned": 1,
        "fund_nudges_pruned": 1,
        "memory_prompts_pruned": 0,
        # Family A has children and one non-supporter member (the parent) who
        # hasn't added a memory this month → one prompt; family B has no child.
        "memory_prompts_sent": 1,
        "notifications_pruned": 0,
        "contributions_purged": 0,
        "family_subscriptions_purged": 0,
        "premium_grants_purged": 0,
        "fund_ledger_entries_purged": 0,
        "abandoned_calls_ended": 1,
        "call_participants_pruned": 1,   # the 100-day-old call's history
        "call_child_presence_pruned": 1,
        # The children's first prediction rounds seal on their 2027 birthdays,
        # not today, so nothing seals/releases in this sweep.
        "prediction_rounds_sealed": 0,
        "prediction_rounds_skipped": 0,
        "prediction_rounds_released": 0,
    }

    with TestingSession() as db:
        # Survivors are intact.
        assert db.query(PremiumGiftIntent).one().stripe_checkout_session_id == "cs_new"
        assert db.query(PremiumEmailLog).one().dedupe_key == "new"
        assert db.query(FundNudge).count() == 1

        # The abandoned call was ended and cleaned; the live one still runs.
        abandoned = db.query(FamilyCall).filter_by(channel_name="fr-abandoned").one()
        assert abandoned.status == CallStatus.ended
        assert abandoned.active_family_id is None
        assert abandoned.ended_at is not None
        assert db.query(CallChildPresence).count() == 0
        stamped = (
            db.query(CallParticipant)
            .filter(CallParticipant.call_id == abandoned.id)
            .one()
        )
        assert stamped.left_at is not None  # history stays coherent

        live = db.query(FamilyCall).filter_by(channel_name="fr-live").one()
        assert live.status == CallStatus.active

        # The abandoned call ended TODAY, so its history is retained for now.
        assert db.query(CallParticipant).count() == 2  # abandoned + live

    # Idempotent: a second run finds nothing to do.
    with TestingSession() as db:
        assert run_maintenance(db) == {
            "gift_intents_pruned": 0,
            "premium_email_log_pruned": 0,
            "fund_nudges_pruned": 0,
            "memory_prompts_pruned": 0,
            "memory_prompts_sent": 0,  # the parent was already prompted
            "notifications_pruned": 0,
            "contributions_purged": 0,
            "family_subscriptions_purged": 0,
            "premium_grants_purged": 0,
            "fund_ledger_entries_purged": 0,
            "abandoned_calls_ended": 0,
            "call_participants_pruned": 0,
            "call_child_presence_pruned": 0,
            "prediction_rounds_sealed": 0,
            "prediction_rounds_skipped": 0,
            "prediction_rounds_released": 0,
        }


def test_maintenance_on_empty_database_is_a_noop(client):
    with TestingSession() as db:
        counts = run_maintenance(db)
    assert all(v == 0 for v in counts.values())


def test_financial_purge_only_touches_fully_severed_aged_rows(client):
    """The 7-year retention disposal (§3.D): hard-delete a money row ONLY when it
    is both fully severed (every subject FK null) AND past the window. A row still
    linked to a living user/child/family, or a severed row inside the window,
    survives untouched."""
    parent = signup(client, "fin@example.com")
    fid = create_family(client, parent, "Fin")
    cid = add_child(client, parent, fid, "FinKid")

    now = utcnow()
    aged = now - timedelta(days=FINANCIAL_RECORD_RETENTION_DAYS + 30)
    recent = now - timedelta(days=10)

    with TestingSession() as db:
        uid = db.query(User).one().id
        fid_u, cid_u = uuid.UUID(fid), uuid.UUID(cid)

        # (a) fully severed AND aged -> PURGED (one of each table).
        db.add(Contribution(
            contributor_user_id=None, child_id=None, amount_cents=1000,
            currency="USD", status=ContributionStatus.succeeded, created_at=aged,
        ))
        db.add(FamilySubscription(
            family_id=None, owner_user_id=None,
            stripe_customer_id="cus_old", stripe_subscription_id="sub_old",
            plan=SubscriptionPlan.annual, status=SubscriptionStatus.canceled,
            current_period_end=now, created_at=aged,
        ))
        db.add(PremiumGrant(
            family_id=None, granted_by_user_id=None,
            stripe_checkout_session_id="cs_old", amount_cents=1000, currency="USD",
            starts_at=aged, ends_at=now, created_at=aged,
        ))
        severed_acct = FundAccount(
            child_id=None, currency="USD", account_status=FundAccountStatus.active
        )
        db.add(severed_acct)
        db.flush()
        db.add(FundLedgerEntry(
            account_id=severed_acct.id, amount_cents=1000,
            entry_type=LedgerEntryType.contribution, created_at=aged,
        ))

        # (b) severed but RECENT (inside the window) -> SURVIVES.
        db.add(Contribution(
            contributor_user_id=None, child_id=None, amount_cents=2000,
            currency="USD", status=ContributionStatus.succeeded, created_at=recent,
        ))
        db.add(FundLedgerEntry(
            account_id=severed_acct.id, amount_cents=2000,
            entry_type=LedgerEntryType.contribution, created_at=recent,
        ))

        # (c) aged but STILL LINKED (a subject FK non-null) -> SURVIVES.
        db.add(Contribution(
            contributor_user_id=uid, child_id=cid_u, amount_cents=3000,
            currency="USD", status=ContributionStatus.succeeded, created_at=aged,
        ))
        db.add(FamilySubscription(
            family_id=fid_u, owner_user_id=uid,
            stripe_customer_id="cus_live", stripe_subscription_id="sub_live",
            plan=SubscriptionPlan.annual, status=SubscriptionStatus.canceled,
            current_period_end=now, created_at=aged,
        ))
        db.add(PremiumGrant(
            family_id=fid_u, granted_by_user_id=uid,
            stripe_checkout_session_id="cs_live", amount_cents=3000, currency="USD",
            starts_at=aged, ends_at=now, created_at=aged,
        ))
        linked_acct = FundAccount(
            child_id=cid_u, currency="USD", account_status=FundAccountStatus.active
        )
        db.add(linked_acct)
        db.flush()
        db.add(FundLedgerEntry(
            account_id=linked_acct.id, amount_cents=3000,
            entry_type=LedgerEntryType.contribution, created_at=aged,
        ))
        db.commit()

    with TestingSession() as db:
        counts = run_maintenance(db)

    # (d) counts appear in the summary — exactly the fully-severed aged rows.
    assert counts["contributions_purged"] == 1
    assert counts["family_subscriptions_purged"] == 1
    assert counts["premium_grants_purged"] == 1
    assert counts["fund_ledger_entries_purged"] == 1

    with TestingSession() as db:
        # (b) recent-severed + (c) aged-linked contributions both remain.
        assert {c.amount_cents for c in db.query(Contribution).all()} == {2000, 3000}
        # Only the still-linked subscription/grant survive.
        assert [s.stripe_subscription_id for s in db.query(FamilySubscription).all()] == ["sub_live"]
        assert [g.stripe_checkout_session_id for g in db.query(PremiumGrant).all()] == ["cs_live"]
        # Recent-severed ledger entry + aged-linked ledger entry survive.
        assert {e.amount_cents for e in db.query(FundLedgerEntry).all()} == {2000, 3000}

    # Idempotent: nothing new to purge on a second run.
    with TestingSession() as db:
        again = run_maintenance(db)
    assert again["contributions_purged"] == 0
    assert again["family_subscriptions_purged"] == 0
    assert again["premium_grants_purged"] == 0
    assert again["fund_ledger_entries_purged"] == 0


def test_financial_purge_ledger_follows_purged_contribution_despite_skew(client):
    """Timestamp-skew guard: a fully-severed aged contribution whose ledger entry
    is NEWER than the cutoff (created at webhook time, after checkout) must not be
    left behind -- the ledger purge follows source_contribution_id, so the entry
    is swept with its contribution and the (bare NO ACTION) FK never dangles."""
    signup(client, "skew@example.com")

    now = utcnow()
    aged = now - timedelta(days=FINANCIAL_RECORD_RETENTION_DAYS + 5)
    recent = now - timedelta(days=1)

    with TestingSession() as db:
        severed_acct = FundAccount(
            child_id=None, currency="USD", account_status=FundAccountStatus.active
        )
        db.add(severed_acct)
        db.flush()
        contrib = Contribution(
            contributor_user_id=None, child_id=None, amount_cents=1000,
            currency="USD", status=ContributionStatus.succeeded, created_at=aged,
        )
        db.add(contrib)
        db.flush()
        # Ledger entry is INSIDE the window but points at the aged contribution.
        db.add(FundLedgerEntry(
            account_id=severed_acct.id, amount_cents=1000,
            entry_type=LedgerEntryType.contribution,
            source_contribution_id=contrib.id, created_at=recent,
        ))
        db.commit()

    with TestingSession() as db:
        counts = run_maintenance(db)

    assert counts["contributions_purged"] == 1
    # The skewed (recent) ledger entry is purged too, not orphaned.
    assert counts["fund_ledger_entries_purged"] == 1
    with TestingSession() as db:
        assert db.query(Contribution).count() == 0
        assert db.query(FundLedgerEntry).count() == 0
