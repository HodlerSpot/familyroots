"""The daily maintenance sweep (Lambda {"futureroots_command": "maintenance"}):
retention prunes + the abandoned-call cap, all idempotent."""

import uuid
from datetime import timedelta

from app.models import (
    CallChildPresence,
    CallParticipant,
    CallStatus,
    FamilyCall,
    FundNudge,
    PremiumEmailLog,
    PremiumGiftIntent,
    User,
    utcnow,
)
from app.services.maintenance import run_maintenance

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
        "notifications_pruned": 0,
        "abandoned_calls_ended": 1,
        "call_participants_pruned": 1,   # the 100-day-old call's history
        "call_child_presence_pruned": 1,
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
            "notifications_pruned": 0,
            "abandoned_calls_ended": 0,
            "call_participants_pruned": 0,
            "call_child_presence_pruned": 0,
        }


def test_maintenance_on_empty_database_is_a_noop(client):
    with TestingSession() as db:
        counts = run_maintenance(db)
    assert all(v == 0 for v in counts.values())
