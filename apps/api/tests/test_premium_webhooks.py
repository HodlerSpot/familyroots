"""FutureRoots Premium webhook handling, via the signed harness: replay
idempotency, out-of-order delivery, live-state convergence (never payload
trust for subscriptions), gift settlement, dedupe, and the double-subscribe
webhook guard."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.models import (
    FamilySubscription,
    FeedEvent,
    FeedEventType,
    PremiumGrant,
    SubscriptionStatus,
    User,
    utcnow,
)
from app.services.payments import SubscriptionState

from .conftest import TestingSession, create_family, make_premium, signup
from .test_goals import make_grandparent
from .test_stripe_webhook import WEBHOOK_SECRET, sign

pytestmark = []


@pytest.fixture(autouse=True)
def webhook_secret(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)


def post_event(client, event_type: str, obj: dict):
    payload = json.dumps(
        {"id": "evt_test", "object": "event", "type": event_type, "data": {"object": obj}}
    ).encode()
    return client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
    )


def sub_object(
    sub_id: str,
    family_id: str | None,
    owner_id: str | None,
    *,
    status: str = "active",
    plan: str = "annual",
    period_end: datetime | None = None,
    cancel_at_period_end: bool = False,
) -> dict:
    metadata = {}
    if family_id is not None:
        metadata = {
            "kind": "premium_subscription",
            "family_id": family_id,
            "owner_user_id": owner_id,
            "plan": plan,
        }
    return {
        "id": sub_id,
        "object": "subscription",
        "status": status,
        "customer": "cus_test",
        "cancel_at_period_end": cancel_at_period_end,
        "current_period_end": int(
            (period_end or utcnow() + timedelta(days=365)).timestamp()
        ),
        "metadata": metadata,
        "items": {"data": [{"price": {"id": "price_test"}}]},
    }


def set_live_state(monkeypatch, sub: dict | None):
    """Handlers must converge to LIVE state — this is that live state."""
    from app.services import payments as pay

    if sub is None:
        monkeypatch.setattr(
            pay._provider, "subscription_state", lambda sid: None, raising=False
        )
        return
    state = SubscriptionState(
        subscription_id=sub["id"],
        customer_id=sub["customer"],
        status=sub["status"],
        price_id="price_test",
        current_period_end=datetime.fromtimestamp(
            sub["current_period_end"], tz=timezone.utc
        ),
        cancel_at_period_end=sub["cancel_at_period_end"],
        metadata=dict(sub["metadata"]),
    )
    monkeypatch.setattr(
        pay._provider,
        "subscription_state",
        lambda sid: state if sid == sub["id"] else None,
        raising=False,
    )


def checkout_session_for_sub(sub: dict) -> dict:
    return {
        "id": f"cs_test_{uuid.uuid4().hex}",
        "object": "checkout.session",
        "subscription": sub["id"],
        "payment_status": "paid",
        "metadata": dict(sub["metadata"]),
    }


def gift_session(
    session_id: str,
    family_id: str,
    gifter_id: str,
    *,
    amount_total: int = 9900,
    payment_status: str = "paid",
    currency: str = "usd",
) -> dict:
    return {
        "id": session_id,
        "object": "checkout.session",
        "payment_status": payment_status,
        "amount_total": amount_total,
        "currency": currency,
        "payment_intent": "pi_test_gift",
        "metadata": {
            "kind": "premium_gift",
            "family_id": family_id,
            "gifter_user_id": gifter_id,
        },
    }


def family_with_parent(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent, "The Salignas")
    with TestingSession() as db:
        owner_id = str(db.query(User).filter(User.email == "parent@example.com").one().id)
    return parent, family_id, owner_id


def premium_plan(client, headers, family_id) -> str:
    return client.get(f"/families/{family_id}/premium", headers=headers).json()["plan"]


def outbox_texts(tmp_path):
    return [p.read_text(encoding="utf-8") for p in sorted(tmp_path.glob("*.txt"))]


def feed_count(event_type: FeedEventType) -> int:
    with TestingSession() as db:
        return db.query(FeedEvent).filter(FeedEvent.type == event_type).count()


# --- subscription lifecycle ---

def test_checkout_completed_mirrors_live_state_and_replays_safely(
    client, monkeypatch, tmp_path
):
    parent, family_id, owner_id = family_with_parent(client)
    sub = sub_object("sub_wh_1", family_id, owner_id, plan="monthly")
    set_live_state(monkeypatch, sub)
    session = checkout_session_for_sub(sub)

    for _ in range(3):  # Stripe retries deliveries
        assert post_event(client, "checkout.session.completed", session).status_code == 200

    assert premium_plan(client, parent, family_id) == "premium"
    with TestingSession() as db:
        rows = db.query(FamilySubscription).all()
        assert len(rows) == 1
        assert rows[0].stripe_subscription_id == "sub_wh_1"
        assert rows[0].status == SubscriptionStatus.active
    # Exactly one feed event and one activation email despite the replays.
    assert feed_count(FeedEventType.premium_activated) == 1
    assert len([t for t in outbox_texts(tmp_path) if "Welcome to FutureRoots Premium" in t]) == 1


def test_out_of_order_updated_before_completed(client, monkeypatch, tmp_path):
    """subscription.updated arriving first still creates the mirror (metadata
    self-identifies the family); the late checkout.session.completed is a no-op."""
    parent, family_id, owner_id = family_with_parent(client)
    sub = sub_object("sub_wh_2", family_id, owner_id)
    set_live_state(monkeypatch, sub)

    assert post_event(client, "customer.subscription.updated", sub).status_code == 200
    assert premium_plan(client, parent, family_id) == "premium"

    assert post_event(
        client, "checkout.session.completed", checkout_session_for_sub(sub)
    ).status_code == 200
    with TestingSession() as db:
        assert db.query(FamilySubscription).count() == 1
    assert feed_count(FeedEventType.premium_activated) == 1
    assert len([t for t in outbox_texts(tmp_path) if "Welcome to FutureRoots Premium" in t]) == 1


def test_subscription_deleted_downgrades_and_emails_once(client, monkeypatch, tmp_path):
    parent, family_id, owner_id = family_with_parent(client)
    make_premium(client, parent, family_id)
    with TestingSession() as db:
        sub_id = db.query(FamilySubscription).one().stripe_subscription_id

    # Deleted subscriptions 404 on retrieve → handler maps the signed payload
    # to canceled.
    set_live_state(monkeypatch, None)
    payload_sub = sub_object(sub_id, family_id, owner_id, status="canceled")

    for _ in range(2):
        assert post_event(client, "customer.subscription.deleted", payload_sub).status_code == 200

    assert premium_plan(client, parent, family_id) == "free"
    ended = [t for t in outbox_texts(tmp_path) if "back on the Free plan" in t]
    assert len(ended) == 1  # deduped across the replay

    # A free family is gated again within one request of the webhook landing.
    r = client.post(f"/families/{family_id}/call/join", headers=parent)
    assert r.status_code == 402


def test_subscription_deleted_with_live_grant_stays_premium_no_email(
    client, monkeypatch, tmp_path
):
    parent, family_id, owner_id = family_with_parent(client)
    gran = make_grandparent(client, parent, family_id)
    make_premium(client, parent, family_id)
    assert client.post(
        f"/families/{family_id}/premium/gift-checkout", json={}, headers=gran
    ).status_code == 200
    with TestingSession() as db:
        sub_id = db.query(FamilySubscription).one().stripe_subscription_id

    set_live_state(monkeypatch, None)
    assert post_event(
        client,
        "customer.subscription.deleted",
        sub_object(sub_id, family_id, owner_id, status="canceled"),
    ).status_code == 200

    assert premium_plan(client, parent, family_id) == "premium"  # the gift carries them
    assert not [t for t in outbox_texts(tmp_path) if "back on the Free plan" in t]


def test_invoice_payment_failed_past_due_and_owner_email_once_per_invoice(
    client, monkeypatch, tmp_path
):
    parent, family_id, owner_id = family_with_parent(client)
    make_premium(client, parent, family_id)
    with TestingSession() as db:
        sub_id = db.query(FamilySubscription).one().stripe_subscription_id

    set_live_state(
        monkeypatch,
        sub_object(sub_id, family_id, owner_id, status="past_due",
                   period_end=utcnow() - timedelta(days=2)),
    )
    invoice = {"id": "in_test_1", "object": "invoice", "subscription": sub_id, "amount_due": 9900}
    for _ in range(3):  # retries of the same invoice event: one email
        assert post_event(client, "invoice.payment_failed", invoice).status_code == 200

    s = client.get(f"/families/{family_id}/premium", headers=parent).json()
    assert s["plan"] == "premium"  # the retry window IS the grace period
    assert s["subscription"]["status"] == "past_due"
    failed = [t for t in outbox_texts(tmp_path) if "A quick note about your Premium payment" in t]
    assert len(failed) == 1
    assert "To: parent@example.com" in failed[0]

    # The NEXT failed invoice emails again (once per invoice, not per retry).
    invoice2 = dict(invoice, id="in_test_2")
    assert post_event(client, "invoice.payment_failed", invoice2).status_code == 200
    assert len(
        [t for t in outbox_texts(tmp_path) if "A quick note about your Premium payment" in t]
    ) == 2


def test_invoice_upcoming_reminder_annual_only_and_deduped(client, tmp_path):
    parent, family_id, owner_id = family_with_parent(client)
    make_premium(client, parent, family_id, plan="annual")
    with TestingSession() as db:
        sub_id = db.query(FamilySubscription).one().stripe_subscription_id

    period_end = int((utcnow() + timedelta(days=7)).timestamp())
    invoice = {"object": "invoice", "subscription": sub_id, "period_end": period_end}
    for _ in range(2):
        assert post_event(client, "invoice.upcoming", invoice).status_code == 200
    reminders = [t for t in outbox_texts(tmp_path) if "renews on" in t]
    assert len(reminders) == 1
    assert "$99" in reminders[0]

    # Monthly plans get no renewal reminder.
    parent2 = signup(client, "parent2@example.com")
    family2 = create_family(client, parent2, "Monthly Fam")
    make_premium(client, parent2, family2, plan="monthly")
    with TestingSession() as db:
        sub2 = (
            db.query(FamilySubscription)
            .filter(FamilySubscription.family_id == uuid.UUID(family2))
            .one()
            .stripe_subscription_id
        )
    assert post_event(
        client,
        "invoice.upcoming",
        {"object": "invoice", "subscription": sub2, "period_end": period_end},
    ).status_code == 200
    assert len([t for t in outbox_texts(tmp_path) if "renews on" in t]) == 1


def test_invoice_paid_remirrors_renewal(client, monkeypatch):
    parent, family_id, owner_id = family_with_parent(client)
    make_premium(client, parent, family_id)
    with TestingSession() as db:
        row = db.query(FamilySubscription).one()
        sub_id = row.stripe_subscription_id

    new_end = utcnow() + timedelta(days=730)
    set_live_state(monkeypatch, sub_object(sub_id, family_id, owner_id, period_end=new_end))
    assert post_event(
        client, "invoice.paid", {"object": "invoice", "subscription": sub_id}
    ).status_code == 200

    with TestingSession() as db:
        row = db.query(FamilySubscription).one()
        assert abs(
            (row.current_period_end.replace(tzinfo=timezone.utc) - new_end).total_seconds()
        ) < 2


# --- gifts ---

def test_gift_webhook_settles_once_and_joins_local_message(client, monkeypatch, tmp_path):
    parent, family_id, owner_id = family_with_parent(client)
    gran = make_grandparent(client, parent, family_id, name="June")
    with TestingSession() as db:
        gifter_id = str(db.query(User).filter(User.email == "gran@example.com").one().id)

    # The message was staged locally at checkout time — never sent to Stripe.
    from app.models import PremiumGiftIntent

    session_id = "cs_gift_wh_1"
    with TestingSession() as db:
        db.add(
            PremiumGiftIntent(
                family_id=uuid.UUID(family_id),
                gifter_user_id=uuid.UUID(gifter_id),
                stripe_checkout_session_id=session_id,
                message="For the recitals",
            )
        )
        db.commit()

    session = gift_session(session_id, family_id, gifter_id)
    for _ in range(3):
        assert post_event(client, "checkout.session.completed", session).status_code == 200

    with TestingSession() as db:
        grants = db.query(PremiumGrant).all()
        assert len(grants) == 1
        assert grants[0].message == "For the recitals"
        assert grants[0].amount_cents == 9900
        assert grants[0].stripe_payment_intent_id == "pi_test_gift"
    assert premium_plan(client, parent, family_id) == "premium"
    assert feed_count(FeedEventType.premium_gifted) == 1
    assert len([t for t in outbox_texts(tmp_path) if "gave your family a year of Premium" in t]) == 1
    assert len([t for t in outbox_texts(tmp_path) if "Your gift to" in t]) == 1


def test_gift_webhook_rejects_unpaid_or_wrong_amount(client, tmp_path):
    parent, family_id, owner_id = family_with_parent(client)
    gran = make_grandparent(client, parent, family_id)
    with TestingSession() as db:
        gifter_id = str(db.query(User).filter(User.email == "gran@example.com").one().id)

    assert post_event(
        client,
        "checkout.session.completed",
        gift_session("cs_unpaid", family_id, gifter_id, payment_status="unpaid"),
    ).status_code == 200
    assert post_event(
        client,
        "checkout.session.completed",
        gift_session("cs_wrong_amount", family_id, gifter_id, amount_total=5000),
    ).status_code == 200

    with TestingSession() as db:
        assert db.query(PremiumGrant).count() == 0
    assert premium_plan(client, parent, family_id) == "free"
    texts = outbox_texts(tmp_path)
    assert not [t for t in texts if "gave your family" in t]
    assert not [t for t in texts if "Your gift to" in t]


def test_gift_webhook_rejects_wrong_currency(client, tmp_path):
    """A paid session for the exact gift amount but in the wrong currency must
    NOT settle — a non-USD charge isn't the USD gift Price we sell."""
    parent, family_id, owner_id = family_with_parent(client)
    gran = make_grandparent(client, parent, family_id)
    with TestingSession() as db:
        gifter_id = str(db.query(User).filter(User.email == "gran@example.com").one().id)

    assert post_event(
        client,
        "checkout.session.completed",
        gift_session("cs_eur", family_id, gifter_id, currency="eur"),
    ).status_code == 200

    with TestingSession() as db:
        assert db.query(PremiumGrant).count() == 0
    assert premium_plan(client, parent, family_id) == "free"
    assert not [t for t in outbox_texts(tmp_path) if "Your gift to" in t]


# --- double-subscribe webhook guard ---

def test_second_subscription_for_premium_family_is_cancelled_and_refunded(
    client, monkeypatch, tmp_path
):
    parent, family_id, owner_id = family_with_parent(client)
    make_premium(client, parent, family_id)

    cancelled: list[tuple[str, bool]] = []
    from app.services import payments as pay

    monkeypatch.setattr(
        pay._provider,
        "cancel_subscription_now",
        lambda sid, *, refund_latest_charge: cancelled.append((sid, refund_latest_charge)),
        raising=False,
    )

    dup = sub_object("sub_duplicate", family_id, owner_id, plan="monthly")
    set_live_state(monkeypatch, dup)
    for _ in range(2):
        assert post_event(
            client, "checkout.session.completed", checkout_session_for_sub(dup)
        ).status_code == 200

    with TestingSession() as db:
        live = (
            db.query(FamilySubscription)
            .filter(FamilySubscription.status != SubscriptionStatus.canceled)
            .all()
        )
        assert len(live) == 1  # the original — no double billing survives
        assert live[0].stripe_subscription_id != "sub_duplicate"
    assert cancelled and cancelled[0] == ("sub_duplicate", True)
    apologies = [t for t in outbox_texts(tmp_path) if "you weren't charged twice" in t]
    assert len(apologies) == 1  # deduped across replays


# --- not ours / noise ---

def test_unknown_subscription_without_premium_metadata_is_ignored(client, monkeypatch):
    signup(client, "parent@example.com")
    sub = sub_object("sub_other_product", None, None)
    set_live_state(monkeypatch, sub)
    r = post_event(client, "customer.subscription.updated", sub)
    assert r.status_code == 200 and r.json() == {"received": True}
    with TestingSession() as db:
        assert db.query(FamilySubscription).count() == 0


def test_bad_signature_rejected(client):
    payload = json.dumps({"type": "checkout.session.completed", "data": {"object": {}}}).encode()
    r = client.post(
        "/webhooks/stripe",
        content=payload,
        headers={"Stripe-Signature": sign(payload, secret="whsec_wrong")},
    )
    assert r.status_code == 400
