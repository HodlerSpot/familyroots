import hashlib
import hmac
import json
import time

import pytest

from app.config import settings
from .conftest import TestingSession, add_child, create_family, signup
from .test_contributions import contribute

WEBHOOK_SECRET = "whsec_test_secret_for_unit_tests"


def sign(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    """Build a valid Stripe-Signature header the way Stripe does."""
    t = int(time.time())
    signed = f"{t}.".encode() + payload
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"


def intent_event(event_type: str, intent_id: str) -> bytes:
    return json.dumps(
        {
            "id": "evt_test",
            "object": "event",
            "type": event_type,
            "data": {"object": {"id": intent_id, "object": "payment_intent"}},
        }
    ).encode()


@pytest.fixture(autouse=True)
def webhook_secret(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)


def make_pending_contribution(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    c = contribute(client, parent, child_id, amount_cents=2500)
    with TestingSession() as db:
        from app.models import Contribution

        intent_id = db.get(Contribution, __import__("uuid").UUID(c["id"])).provider_payment_id
    return parent, child_id, c, intent_id


def test_signed_success_webhook_settles(client):
    parent, child_id, c, intent_id = make_pending_contribution(client)
    payload = intent_event("payment_intent.succeeded", intent_id)

    r = client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
    )
    assert r.status_code == 200, r.text

    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert fund["balance_cents"] == 2500 - 62
    assert len(fund["entries"]) == 1


def test_webhook_is_idempotent(client):
    parent, child_id, c, intent_id = make_pending_contribution(client)
    payload = intent_event("payment_intent.succeeded", intent_id)

    for _ in range(3):  # Stripe retries deliveries; only one ledger entry allowed
        r = client.post(
            "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
        )
        assert r.status_code == 200

    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert len(fund["entries"]) == 1


def test_bad_signature_rejected_and_nothing_settles(client):
    parent, child_id, c, intent_id = make_pending_contribution(client)
    payload = intent_event("payment_intent.succeeded", intent_id)

    r = client.post(
        "/webhooks/stripe",
        content=payload,
        headers={"Stripe-Signature": sign(payload, secret="whsec_wrong_secret")},
    )
    assert r.status_code == 400
    r = client.post("/webhooks/stripe", content=payload)  # no signature at all
    assert r.status_code == 400

    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert fund["balance_cents"] == 0


def test_failed_payment_marks_contribution_failed(client):
    parent, child_id, c, intent_id = make_pending_contribution(client)
    payload = intent_event("payment_intent.payment_failed", intent_id)

    r = client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
    )
    assert r.status_code == 200

    from app.models import Contribution, ContributionStatus
    import uuid as uuid_mod

    with TestingSession() as db:
        assert (
            db.get(Contribution, uuid_mod.UUID(c["id"])).status == ContributionStatus.failed
        )
    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert fund["balance_cents"] == 0


def test_unknown_intent_acknowledged_without_side_effects(client):
    parent = signup(client, "parent@example.com")
    payload = intent_event("payment_intent.succeeded", "pi_not_ours")
    r = client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
    )
    assert r.status_code == 200
    assert r.json() == {"received": True}
