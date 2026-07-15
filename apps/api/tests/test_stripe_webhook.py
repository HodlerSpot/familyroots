import hashlib
import hmac
import json
import time

import pytest

from app.config import settings
from .conftest import TestingSession, add_child, create_family, setup_fund, signup
from .test_contributions import contribute

WEBHOOK_SECRET = "whsec_test_secret_for_unit_tests"


def sign(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    """Build a valid Stripe-Signature header the way Stripe does."""
    t = int(time.time())
    signed = f"{t}.".encode() + payload
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"


def intent_event(
    event_type: str,
    intent_id: str,
    destination: str | None = None,
    application_fee_amount: int | None = None,
) -> bytes:
    intent: dict = {"id": intent_id, "object": "payment_intent"}
    if destination is not None:
        intent["transfer_data"] = {"destination": destination}
        intent["application_fee_amount"] = application_fee_amount
    return json.dumps(
        {
            "id": "evt_test",
            "object": "event",
            "type": event_type,
            "data": {"object": intent},
        }
    ).encode()


@pytest.fixture(autouse=True)
def webhook_secret(monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)


def make_pending_contribution(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)
    c = contribute(client, parent, child_id, amount_cents=2500)
    with TestingSession() as db:
        from app.models import Contribution, FundAccount

        intent_id = db.get(Contribution, __import__("uuid").UUID(c["id"])).provider_payment_id
        account_id = (
            db.query(FundAccount)
            .filter(FundAccount.child_id == __import__("uuid").UUID(child_id))
            .one()
            .stripe_account_id
        )
    return parent, child_id, c, intent_id, account_id


def test_signed_success_webhook_settles(client):
    parent, child_id, c, intent_id, account_id = make_pending_contribution(client)
    payload = intent_event("payment_intent.succeeded", intent_id, account_id, 103)

    r = client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
    )
    assert r.status_code == 200, r.text

    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert fund["balance_cents"] == 2500 - 103
    assert len(fund["entries"]) == 1


def test_webhook_is_idempotent(client):
    parent, child_id, c, intent_id, account_id = make_pending_contribution(client)
    payload = intent_event("payment_intent.succeeded", intent_id, account_id, 103)

    for _ in range(3):  # Stripe retries deliveries; only one ledger entry allowed
        r = client.post(
            "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
        )
        assert r.status_code == 200

    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert len(fund["entries"]) == 1


def test_bad_signature_rejected_and_nothing_settles(client):
    parent, child_id, c, intent_id, account_id = make_pending_contribution(client)
    payload = intent_event("payment_intent.succeeded", intent_id, account_id, 103)

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
    parent, child_id, c, intent_id, account_id = make_pending_contribution(client)
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


def test_destination_mismatch_does_not_settle(client):
    """A succeeded PI whose transfer destination is not the child's current
    account must never write the ledger — ack and leave pending."""
    parent, child_id, c, intent_id, account_id = make_pending_contribution(client)
    payload = intent_event(
        "payment_intent.succeeded", intent_id, "acct_someone_elses", 103
    )
    r = client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
    )
    assert r.status_code == 200  # acked so Stripe stops retrying

    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert fund["balance_cents"] == 0 and fund["entries"] == []
    with TestingSession() as db:
        from app.models import Contribution, ContributionStatus

        assert (
            db.get(Contribution, __import__("uuid").UUID(c["id"])).status
            == ContributionStatus.pending
        )


def test_application_fee_mismatch_does_not_settle(client):
    parent, child_id, c, intent_id, account_id = make_pending_contribution(client)
    payload = intent_event("payment_intent.succeeded", intent_id, account_id, 1)
    r = client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
    )
    assert r.status_code == 200
    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert fund["balance_cents"] == 0 and fund["entries"] == []


def test_missing_transfer_data_with_connect_account_does_not_settle(client):
    """Once the child has a connected account, a PI with no transfer_data is
    not one of our destination charges — it must not settle."""
    parent, child_id, c, intent_id, account_id = make_pending_contribution(client)
    payload = intent_event("payment_intent.succeeded", intent_id)  # no transfer_data
    r = client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
    )
    assert r.status_code == 200
    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert fund["balance_cents"] == 0 and fund["entries"] == []


def test_legacy_intent_without_connect_account_still_settles(client):
    """Pre-Connect (legacy) contributions: PI has no transfer_data AND the
    child's fund has no connected account — settles exactly as before."""
    import uuid as uuid_mod

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)

    with TestingSession() as db:
        from app.models import Contribution, User

        contributor = db.query(User).filter(User.email == "parent@example.com").one()
        legacy = Contribution(
            child_id=uuid_mod.UUID(child_id),
            contributor_user_id=contributor.id,
            amount_cents=2500,
            fee_cents=62,  # priced under the old fee schedule
            provider_payment_id="pi_legacy_predeploy",
        )
        db.add(legacy)
        db.commit()

    payload = intent_event("payment_intent.succeeded", "pi_legacy_predeploy")
    r = client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
    )
    assert r.status_code == 200

    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert fund["balance_cents"] == 2500 - 62
    assert len(fund["entries"]) == 1


# --- the Connect endpoint (account.updated) ---

CONNECT_SECRET = "whsec_connect_secret_for_unit_tests"


def account_event(account_id: str) -> bytes:
    return json.dumps(
        {
            "id": "evt_acct",
            "object": "event",
            "type": "account.updated",
            "account": account_id,
            # Deliberately misleading payload body: handlers must NOT trust it
            "data": {"object": {"id": account_id, "payouts_enabled": True}},
        }
    ).encode()


@pytest.fixture()
def connect_secret(monkeypatch):
    monkeypatch.setattr(settings, "stripe_connect_webhook_secret", CONNECT_SECRET)


def test_connect_webhook_503_when_unconfigured(client):
    payload = account_event("acct_x")
    r = client.post(
        "/webhooks/stripe-connect",
        content=payload,
        headers={"Stripe-Signature": sign(payload, secret=CONNECT_SECRET)},
    )
    assert r.status_code == 503


def test_connect_webhook_requires_valid_signature(client, connect_secret):
    payload = account_event("acct_x")
    assert (
        client.post(
            "/webhooks/stripe-connect",
            content=payload,
            headers={"Stripe-Signature": sign(payload, secret="whsec_wrong")},
        ).status_code
        == 400
    )


def test_account_updated_transitions_status_from_live_state(client, connect_secret, monkeypatch):
    """account.updated triggers a LIVE re-fetch (never trusts the payload) and
    the shared sync walks the account through restricted and back to active."""
    from app.services import payments as pay
    from app.services.payments import ConnectAccountState

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)  # active, acct_local_… id

    with TestingSession() as db:
        from app.models import FundAccount
        import uuid as uuid_mod

        account_id = (
            db.query(FundAccount)
            .filter(FundAccount.child_id == uuid_mod.UUID(child_id))
            .one()
            .stripe_account_id
        )

    # Stripe pauses the account: payouts off, more info required
    monkeypatch.setattr(
        pay._provider,
        "connect_account_state",
        lambda acct: ConnectAccountState(
            details_submitted=True,
            charges_enabled=False,
            payouts_enabled=False,
            transfers_active=False,
            requirements_due=True,
        ),
        raising=False,
    )
    payload = account_event(account_id)
    r = client.post(
        "/webhooks/stripe-connect",
        content=payload,
        headers={"Stripe-Signature": sign(payload, secret=CONNECT_SECRET)},
    )
    assert r.status_code == 200
    r = client.get(f"/children/{child_id}/fund/status", headers=parent)
    assert r.json()["account_status"] == "restricted"

    # while restricted, gifts are paused
    r = client.post(
        f"/children/{child_id}/contributions", json={"amount_cents": 2500}, headers=parent
    )
    assert r.status_code == 409
    assert "paused" in r.json()["detail"]

    # Stripe reinstates it
    monkeypatch.setattr(
        pay._provider,
        "connect_account_state",
        lambda acct: ConnectAccountState(
            details_submitted=True,
            charges_enabled=True,
            payouts_enabled=True,
            transfers_active=True,
            requirements_due=False,
        ),
        raising=False,
    )
    r = client.post(
        "/webhooks/stripe-connect",
        content=payload,
        headers={"Stripe-Signature": sign(payload, secret=CONNECT_SECRET)},
    )
    assert r.status_code == 200
    assert (
        client.get(f"/children/{child_id}/fund/status", headers=parent).json()["account_status"]
        == "active"
    )


def test_account_updated_for_unknown_account_is_acked(client, connect_secret):
    payload = account_event("acct_never_seen")
    r = client.post(
        "/webhooks/stripe-connect",
        content=payload,
        headers={"Stripe-Signature": sign(payload, secret=CONNECT_SECRET)},
    )
    assert r.status_code == 200 and r.json() == {"received": True}
