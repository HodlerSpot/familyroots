"""Real Future Fund accounts (Stripe Connect): fee math, the setup lifecycle,
access control, contribution gating, refund flags, and the nudge flow."""

import types
import uuid as uuid_mod
from datetime import timedelta

import pytest

from .conftest import TestingSession, add_child, create_family, setup_fund, signup
from .test_goals import make_grandparent
from .test_supporter_access import make_supporter


# --- fee math ---

@pytest.mark.parametrize(
    "amount,fee,net",
    [
        (100, 33, 67),  # the minimum contribution
        (2500, 103, 2397),
        (10_000, 320, 9_680),
    ],
)
def test_contribution_fee_math(amount, fee, net):
    from app.services.payments import contribution_fee_cents

    assert contribution_fee_cents(amount) == fee
    assert amount - contribution_fee_cents(amount) == net


def test_fee_may_never_consume_the_contribution():
    from app.services.payments import contribution_fee_cents

    with pytest.raises(ValueError):
        contribution_fee_cents(31)  # fee would equal the amount


# --- setup lifecycle & access control ---

def test_setup_is_guardian_only(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id)
    supporter = make_supporter(client, parent, family_id)

    assert client.post(f"/children/{child_id}/fund/setup", headers=gran).status_code == 403
    assert client.post(f"/children/{child_id}/fund/setup", headers=supporter).status_code == 403
    assert client.get(f"/children/{child_id}/fund/setup/status", headers=gran).status_code == 403
    assert (
        client.get(f"/children/{child_id}/fund/setup/status", headers=supporter).status_code
        == 403
    )
    # an outsider doesn't even learn the child exists
    outsider = signup(client, "outsider@example.com")
    assert client.post(f"/children/{child_id}/fund/setup", headers=outsider).status_code == 404


def test_stripe_error_becomes_friendly_503(client, monkeypatch):
    """A Stripe failure in a request path (e.g. Connect not fully configured on
    the platform side) must surface as a warm 503, not a raw 500, and never leak
    the vendor's name or internals to the user."""
    import stripe

    from app.services import payments

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)

    def boom(*args, **kwargs):
        raise stripe.error.StripeError("Please review the responsibilities of managing losses")

    monkeypatch.setattr(payments._provider, "create_connect_account", boom)

    resp = client.post(f"/children/{child_id}/fund/setup", headers=parent)
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "payments partner" in detail
    assert "Stripe" not in detail and "losses" not in detail


def test_double_setup_creates_exactly_one_account(client):
    from app.models import FundAccount

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)

    r1 = client.post(f"/children/{child_id}/fund/setup", headers=parent)
    assert r1.status_code == 200 and r1.json()["url"]
    with TestingSession() as db:
        first_id = (
            db.query(FundAccount)
            .filter(FundAccount.child_id == uuid_mod.UUID(child_id))
            .one()
            .stripe_account_id
        )

    # clicking setup again mints a fresh link but NEVER a second account
    r2 = client.post(f"/children/{child_id}/fund/setup", headers=parent)
    assert r2.status_code == 200
    with TestingSession() as db:
        accounts = (
            db.query(FundAccount)
            .filter(FundAccount.child_id == uuid_mod.UUID(child_id))
            .all()
        )
        assert len(accounts) == 1
        assert accounts[0].stripe_account_id == first_id

    # once active, setup refuses
    r = client.get(f"/children/{child_id}/fund/setup/status", headers=parent)
    assert r.json()["account_status"] == "active"
    assert client.post(f"/children/{child_id}/fund/setup", headers=parent).status_code == 409


def test_local_end_to_end_setup_then_contribute(client):
    """Setup → active → contribute → confirm → ONE ledger entry for the NET →
    balance equals the net. The ledger meaning shifts (net = what actually
    reached the child's account) with unchanged math."""
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)

    r = client.post(f"/children/{child_id}/fund/setup", headers=parent)
    assert r.status_code == 200
    assert "simulated=1" in r.json()["url"]  # local provider: no hosted onboarding

    r = client.get(f"/children/{child_id}/fund/setup/status", headers=parent)
    assert r.status_code == 200
    body = r.json()
    assert body["account_status"] == "active"
    assert body["payouts_enabled"] is True
    assert body["requirements_due"] is False

    c = client.post(
        f"/children/{child_id}/contributions", json={"amount_cents": 2500}, headers=parent
    )
    assert c.status_code == 201
    assert c.json()["fee_cents"] == 103
    assert client.post(f"/contributions/{c.json()['id']}/confirm", headers=parent).status_code == 200

    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert len(fund["entries"]) == 1
    assert fund["entries"][0]["amount_cents"] == 2397  # net, never gross
    assert fund["balance_cents"] == 2397
    assert fund["account_status"] == "active"
    assert fund["setup_by_name"] == "Pat"

    # the account id never appears anywhere in the member-facing payloads
    assert "acct_" not in c.text and "acct_" not in str(fund)


def test_contribution_blocked_until_fund_is_active(client):
    from app.models import FundAccount, FundAccountStatus

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")

    # none: no setup at all
    r = client.post(
        f"/children/{child_id}/contributions", json={"amount_cents": 2500}, headers=parent
    )
    assert r.status_code == 409
    assert "isn't ready for gifts yet" in r.json()["detail"]

    # onboarding: setup started, not finished (no status poll yet)
    client.post(f"/children/{child_id}/fund/setup", headers=parent)
    r = client.post(
        f"/children/{child_id}/contributions", json={"amount_cents": 2500}, headers=parent
    )
    assert r.status_code == 409

    # restricted: Stripe paused the account
    with TestingSession() as db:
        account = (
            db.query(FundAccount)
            .filter(FundAccount.child_id == uuid_mod.UUID(child_id))
            .one()
        )
        account.account_status = FundAccountStatus.restricted
        db.commit()
    r = client.post(
        f"/children/{child_id}/contributions", json={"amount_cents": 2500}, headers=parent
    )
    assert r.status_code == 409
    assert "paused" in r.json()["detail"]


def test_supporter_sees_status_but_never_the_fund(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)
    supporter = make_supporter(client, parent, family_id)

    # readiness only — a supporter can give, so they may see whether they can
    r = client.get(f"/children/{child_id}/fund/status", headers=supporter)
    assert r.status_code == 200
    assert r.json() == {"account_status": "active"}

    # money stays family-only
    assert client.get(f"/children/{child_id}/fund", headers=supporter).status_code == 403


def test_fund_status_requires_membership(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    outsider = signup(client, "outsider@example.com")
    assert client.get(f"/children/{child_id}/fund/status", headers=outsider).status_code == 404


# --- refunds carry the Connect flags ---

def test_stripe_refund_reverses_transfer_and_application_fee(client, monkeypatch):
    """The Stripe refund call must claw back the transfer and the app fee, and
    the ledger gets a compensating NET entry (append-only, no mutation)."""
    from app.services import payments as pay
    from app.services.payments import StripePaymentProvider
    from .test_admin import make_admin

    admin = make_admin(client)
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)
    c = client.post(
        f"/children/{child_id}/contributions", json={"amount_cents": 2500}, headers=parent
    ).json()
    client.post(f"/contributions/{c['id']}/confirm", headers=parent)

    calls: list[dict] = []
    provider = StripePaymentProvider("sk_test_dummy_key_never_used")
    # The live PI is a destination charge, so the refund must unwind the
    # transfer and application fee alongside the contributor's card.
    live_pi = {
        "transfer_data": {"destination": "acct_local_whatever"},
        "application_fee_amount": 103,
    }
    provider.client = types.SimpleNamespace(
        refunds=types.SimpleNamespace(create=lambda params: calls.append(params)),
        payment_intents=types.SimpleNamespace(retrieve=lambda pid: live_pi),
    )
    monkeypatch.setattr(pay, "_provider", provider)

    r = client.post(f"/admin/contributions/{c['id']}/refund", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "refunded"

    assert len(calls) == 1
    assert calls[0]["amount"] == 2500  # gross back to the contributor
    assert calls[0]["refund_application_fee"] is True
    assert calls[0]["reverse_transfer"] is True

    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert len(fund["entries"]) == 2  # original + compensating entry
    assert fund["entries"][0]["amount_cents"] == -2397  # net reversed
    assert fund["balance_cents"] == 0


def test_stripe_refund_of_legacy_charge_omits_transfer_flags():
    """A pre-Connect charge has no transfer; Stripe rejects reverse_transfer
    on it, so the refund call must omit both Connect flags (else legacy
    contributions would become non-refundable)."""
    from app.models import Contribution
    from app.services.payments import StripePaymentProvider

    provider = StripePaymentProvider("sk_test_dummy_key_never_used")
    calls: list[dict] = []
    provider.client = types.SimpleNamespace(
        refunds=types.SimpleNamespace(create=lambda params: calls.append(params)),
        payment_intents=types.SimpleNamespace(retrieve=lambda pid: {}),  # no transfer_data
    )
    contribution = Contribution(provider_payment_id="pi_legacy_123")
    assert provider.refund_payment(contribution, 2500) is True
    assert len(calls) == 1
    assert calls[0]["amount"] == 2500
    assert "refund_application_fee" not in calls[0]
    assert "reverse_transfer" not in calls[0]


def test_contribution_currency_must_match_the_fund(client):
    """A crafted non-USD currency would charge in that currency while the USD
    ledger records raw cents; the fund's currency always wins."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)

    r = client.post(
        f"/children/{child_id}/contributions",
        json={"amount_cents": 1000, "currency": "JPY"},
        headers=parent,
    )
    assert r.status_code == 422
    assert "USD" in r.json()["detail"]


def test_setup_records_contributions_consent(client):
    """Opening a real money account for the child is recorded consent
    (COPPA: consent is data, never an assumption)."""
    from app.models import ConsentRecord, ConsentType

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)

    with TestingSession() as db:
        records = (
            db.query(ConsentRecord)
            .filter(
                ConsentRecord.child_id == uuid_mod.UUID(child_id),
                ConsentRecord.consent_type == ConsentType.contributions,
            )
            .all()
        )
        assert len(records) == 1


# --- nudges ---

def test_nudge_emails_parents_only_and_throttles(client, tmp_path):
    from app.models import FundNudge, utcnow

    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Grandma Rose")
    make_supporter(client, parent, family_id)  # coach@example.com

    before = set(tmp_path.glob("*.txt"))
    r = client.post(f"/children/{child_id}/fund/nudge", headers=gran)
    assert r.status_code == 200 and r.json() == {"sent": True}

    new_mail = [
        f.read_text(encoding="utf-8") for f in set(tmp_path.glob("*.txt")) - before
    ]
    assert len(new_mail) == 1  # exactly the one parent
    assert "To: parent@example.com" in new_mail[0]
    assert "Grandma Rose is ready to give to Emma's Future Fund" in new_mail[0]
    assert not any("coach@example.com" in m for m in new_mail)  # never supporters

    # 7-day throttle: quietly refuses, no error, no email
    before = set(tmp_path.glob("*.txt"))
    r = client.post(f"/children/{child_id}/fund/nudge", headers=gran)
    assert r.status_code == 200 and r.json() == {"sent": False}
    assert set(tmp_path.glob("*.txt")) == before

    # …but a different member may still nudge
    other = make_supporter(
        client, parent, family_id, email="uncle-coach@example.com", name="Coach"
    )
    r = client.post(f"/children/{child_id}/fund/nudge", headers=other)
    assert r.status_code == 200 and r.json() == {"sent": True}

    # …and after the window passes, the grandparent can nudge again
    with TestingSession() as db:
        from app.models import User

        gran_user = db.query(User).filter(User.email == "gran@example.com").one()
        nudge = (
            db.query(FundNudge)
            .filter(
                FundNudge.child_id == uuid_mod.UUID(child_id),
                FundNudge.user_id == gran_user.id,
            )
            .one()
        )
        nudge.created_at = utcnow() - timedelta(days=8)
        db.commit()
    r = client.post(f"/children/{child_id}/fund/nudge", headers=gran)
    assert r.status_code == 200 and r.json() == {"sent": True}


def test_nudge_double_tap_race_is_single_send(client, tmp_path, monkeypatch):
    """Two concurrent FIRST nudges both see no claim row; the loser's INSERT
    hits the unique (child, member) constraint and quietly returns sent=false
    with no email. Simulated by making the loser's lookup miss the claim the
    winner has already committed — exactly its view of the race."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id)

    # The winner claims the throttle and sends.
    r = client.post(f"/children/{child_id}/fund/nudge", headers=gran)
    assert r.status_code == 200 and r.json() == {"sent": True}

    from app.routers import funds as funds_router

    monkeypatch.setattr(funds_router, "_nudge_claim", lambda db, cid, uid: None)

    before = set(tmp_path.glob("*.txt"))
    r = client.post(f"/children/{child_id}/fund/nudge", headers=gran)
    assert r.status_code == 200 and r.json() == {"sent": False}
    assert set(tmp_path.glob("*.txt")) == before  # no duplicate email

    from app.models import FundNudge

    with TestingSession() as db:
        assert db.query(FundNudge).count() == 1  # single claim row survives


def test_renudge_after_window_refreshes_claim_in_place(client):
    """A re-nudge after the 7-day window refreshes created_at on the SAME row
    (one row per member+child, ever)."""
    from app.models import FundNudge, utcnow

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id)

    assert client.post(f"/children/{child_id}/fund/nudge", headers=gran).json() == {"sent": True}
    with TestingSession() as db:
        nudge = db.query(FundNudge).one()
        nudge.created_at = utcnow() - timedelta(days=8)
        db.commit()
        old_id = nudge.id

    assert client.post(f"/children/{child_id}/fund/nudge", headers=gran).json() == {"sent": True}
    with TestingSession() as db:
        refreshed = db.query(FundNudge).one()  # still exactly one row
        assert refreshed.id == old_id
        created = refreshed.created_at
        if created.tzinfo is None:
            from datetime import timezone

            created = created.replace(tzinfo=timezone.utc)
        assert created > utcnow() - timedelta(minutes=1)


def test_parents_cannot_nudge_themselves(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    assert client.post(f"/children/{child_id}/fund/nudge", headers=parent).status_code == 409


def test_outsider_cannot_nudge(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    outsider = signup(client, "outsider@example.com")
    assert client.post(f"/children/{child_id}/fund/nudge", headers=outsider).status_code == 404
