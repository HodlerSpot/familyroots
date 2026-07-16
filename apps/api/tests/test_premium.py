"""FutureRoots Premium: derived entitlements, role gates on every endpoint,
402 enforcement at the choke points, the local end-to-end checkout/gift flow,
and the request-driven lifecycle emails."""

import uuid
from datetime import timedelta

import pytest

from app.models import (
    FamilyInvite,
    FamilySubscription,
    PremiumGrant,
    SubscriptionPlan,
    SubscriptionStatus,
    User,
    utcnow,
)
from .conftest import (
    TestingSession,
    add_child,
    create_family,
    make_premium,
    media_token,
    signup,
)
from .test_goals import make_grandparent
from .test_supporter_access import make_supporter


def make_member(client, parent, family_id, email, role, name="Member"):
    client.post(
        f"/families/{family_id}/invites",
        json={"email": email, "role": role},
        headers=parent,
    )
    with TestingSession() as db:
        token = db.query(FamilyInvite).filter(FamilyInvite.email == email).first().token
    member = signup(client, email, name)
    r = client.post("/invites/accept", json={"token": token}, headers=member)
    assert r.status_code == 200, r.text
    return member


def _user_id(email: str) -> uuid.UUID:
    with TestingSession() as db:
        return db.query(User).filter(User.email == email).one().id


def insert_subscription(
    family_id: str,
    owner_email: str,
    *,
    status: str = "active",
    period_end_delta=timedelta(days=30),
    plan: str = "annual",
    cancel_at_period_end: bool = False,
) -> str:
    sub_id = f"sub_test_{uuid.uuid4().hex}"
    with TestingSession() as db:
        owner = db.query(User).filter(User.email == owner_email).one()
        db.add(
            FamilySubscription(
                family_id=uuid.UUID(family_id),
                owner_user_id=owner.id,
                stripe_customer_id="cus_test",
                stripe_subscription_id=sub_id,
                plan=SubscriptionPlan(plan),
                status=SubscriptionStatus(status),
                current_period_end=utcnow() + period_end_delta,
                cancel_at_period_end=cancel_at_period_end,
            )
        )
        db.commit()
    return sub_id


def insert_grant(
    family_id: str,
    gifter_email: str,
    *,
    starts_delta=timedelta(days=0),
    ends_delta=timedelta(days=365),
    voided: bool = False,
    message: str | None = None,
) -> str:
    grant_id = uuid.uuid4()
    with TestingSession() as db:
        gifter = db.query(User).filter(User.email == gifter_email).one()
        db.add(
            PremiumGrant(
                id=grant_id,
                family_id=uuid.UUID(family_id),
                granted_by_user_id=gifter.id,
                stripe_checkout_session_id=f"cs_test_{uuid.uuid4().hex}",
                amount_cents=9900,
                currency="USD",
                message=message,
                starts_at=utcnow() + starts_delta,
                ends_at=utcnow() + ends_delta,
                voided_at=utcnow() if voided else None,
            )
        )
        db.commit()
    return str(grant_id)


def premium_status(client, headers, family_id):
    r = client.get(f"/families/{family_id}/premium", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def outbox_texts(tmp_path) -> list[str]:
    return [p.read_text(encoding="utf-8") for p in sorted(tmp_path.glob("*.txt"))]


def feed_types(client, headers, family_id) -> list[str]:
    r = client.get(f"/families/{family_id}/feed", headers=headers)
    assert r.status_code == 200
    return [e["type"] for e in r.json()]


# --- entitlement derivation ---

def test_new_family_is_free(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    s = premium_status(client, parent, family_id)
    assert s["plan"] == "free"
    assert s["capabilities"] == []
    assert s["premium_until"] is None
    assert s["subscription"] is None
    assert s["grants"] == []
    assert s["can_manage"] is True
    assert s["can_gift"] is False


def test_active_subscription_is_premium(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    insert_subscription(family_id, "parent@example.com", period_end_delta=timedelta(days=20))
    s = premium_status(client, parent, family_id)
    assert s["plan"] == "premium"
    assert sorted(s["capabilities"]) == ["family_video_call", "video_upload"]


def test_active_subscription_renewal_slack(client):
    """A just-lapsed active row stays premium for 72h (lost-webhook slack),
    but not beyond it. Displayed premium_until never includes the slack."""
    parent = signup(client, "parent@example.com")
    family_a = create_family(client, parent, "A")
    family_b = create_family(client, parent, "B")
    insert_subscription(family_a, "parent@example.com", period_end_delta=timedelta(hours=-1))
    insert_subscription(family_b, "parent@example.com", period_end_delta=timedelta(hours=-73))
    assert premium_status(client, parent, family_a)["plan"] == "premium"
    assert premium_status(client, parent, family_b)["plan"] == "free"


def test_past_due_holds_entitlement_unconditionally(client):
    """Stripe's Smart Retries window IS the grace period."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    insert_subscription(
        family_id, "parent@example.com", status="past_due",
        period_end_delta=timedelta(days=-30),
    )
    assert premium_status(client, parent, family_id)["plan"] == "premium"


def test_canceled_subscription_is_free(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    insert_subscription(
        family_id, "parent@example.com", status="canceled",
        period_end_delta=timedelta(days=30),
    )
    assert premium_status(client, parent, family_id)["plan"] == "free"


def test_grant_entitlement_rules(client):
    parent = signup(client, "parent@example.com")
    gran_family = create_family(client, parent, "Current")
    make_grandparent(client, parent, gran_family)

    # current grant → premium
    insert_grant(gran_family, "gran@example.com")
    assert premium_status(client, parent, gran_family)["plan"] == "premium"

    # voided grant → free
    voided_family = create_family(client, parent, "Voided")
    insert_grant(voided_family, "gran@example.com", voided=True)
    assert premium_status(client, parent, voided_family)["plan"] == "free"

    # expired grant → free
    expired_family = create_family(client, parent, "Expired")
    insert_grant(
        expired_family, "gran@example.com",
        starts_delta=timedelta(days=-400), ends_delta=timedelta(days=-35),
    )
    # (lazy lifecycle may email here; entitlement is what we assert)
    assert premium_status(client, parent, expired_family)["plan"] == "free"

    # future-starting grant → not premium yet, but shows on the horizon
    future_family = create_family(client, parent, "Future")
    insert_grant(
        future_family, "gran@example.com",
        starts_delta=timedelta(days=10), ends_delta=timedelta(days=375),
    )
    s = premium_status(client, parent, future_family)
    assert s["plan"] == "free"
    assert s["premium_until"] is not None


def test_grant_stacking_extends_premium_until(client):
    """Stacked grants never overlap: the second starts where the first ends,
    and premium_until reflects the combined coverage."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id)
    relative = make_member(client, parent, family_id, "uncle@example.com", "relative", "Uncle")

    r = client.post(f"/families/{family_id}/premium/gift-checkout", json={}, headers=gran)
    assert r.status_code == 200, r.text
    r = client.post(f"/families/{family_id}/premium/gift-checkout", json={}, headers=relative)
    assert r.status_code == 200, r.text

    with TestingSession() as db:
        grants = (
            db.query(PremiumGrant)
            .filter(PremiumGrant.family_id == uuid.UUID(family_id))
            .order_by(PremiumGrant.starts_at)
            .all()
        )
    assert len(grants) == 2
    assert grants[1].starts_at == grants[0].ends_at  # stack, never overlap

    s = premium_status(client, parent, family_id)
    assert s["plan"] == "premium"
    from datetime import datetime as _dt

    until = _dt.fromisoformat(s["premium_until"].replace("Z", "+00:00"))
    assert until.replace(tzinfo=None) == grants[1].ends_at.replace(tzinfo=None)
    assert len(s["grants"]) == 2


def test_families_list_badge_matches_entitlement(client):
    parent = signup(client, "parent@example.com")
    premium_family = create_family(client, parent, "Premium Family")
    free_family = create_family(client, parent, "Free Family")
    make_premium(client, parent, premium_family)

    r = client.get("/families", headers=parent)
    plans = {f["name"]: f["plan"] for f in r.json()}
    assert plans == {"Premium Family": "premium", "Free Family": "free"}

    detail = client.get(f"/families/{premium_family}", headers=parent).json()
    assert detail["plan"] == "premium"
    assert detail["premium_until"] is not None
    assert sorted(detail["capabilities"]) == ["family_video_call", "video_upload"]
    free_detail = client.get(f"/families/{free_family}", headers=parent).json()
    assert free_detail["plan"] == "free"
    assert free_detail["capabilities"] == []


# --- role gates ---

def test_checkout_is_parent_only(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id)
    guardian = make_member(client, parent, family_id, "guardian@example.com", "guardian")
    supporter = make_supporter(client, parent, family_id)
    outsider = signup(client, "outsider@example.com")

    url = f"/families/{family_id}/premium/checkout"
    for headers in (gran, guardian, supporter):
        assert client.post(url, json={"plan": "annual"}, headers=headers).status_code == 403
    assert client.post(url, json={"plan": "annual"}, headers=outsider).status_code == 404
    assert client.post(url, json={"plan": "annual"}, headers=parent).status_code == 200


def test_gift_checkout_role_matrix(client):
    """Any active non-parent (including a supporter) may gift; parents are
    pointed at subscribe; non-members never learn the family exists."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id)
    supporter = make_supporter(client, parent, family_id)
    outsider = signup(client, "outsider@example.com")

    url = f"/families/{family_id}/premium/gift-checkout"
    r = client.post(url, json={}, headers=parent)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "use_subscribe"
    assert client.post(url, json={}, headers=outsider).status_code == 404
    assert client.post(url, json={"message": "With love"}, headers=gran).status_code == 200
    assert client.post(url, json={}, headers=supporter).status_code == 200


def test_cancel_and_resume_are_parent_only(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id)
    make_premium(client, parent, family_id)

    assert client.post(f"/families/{family_id}/premium/cancel", headers=gran).status_code == 403
    assert client.post(f"/families/{family_id}/premium/resume", headers=gran).status_code == 403


def test_portal_is_owner_only(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    second_parent = make_member(client, parent, family_id, "parent2@example.com", "parent", "Sam")
    make_premium(client, parent, family_id)

    url = f"/families/{family_id}/premium/portal"
    # Another parent may cancel, but the Billing Portal is the owner's.
    assert client.post(url, headers=second_parent).status_code == 403
    r = client.post(url, headers=parent)
    assert r.status_code == 200
    assert "portal=simulated" in r.json()["portal_url"]


def test_status_requires_membership(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    outsider = signup(client, "outsider@example.com")
    assert client.get(f"/families/{family_id}/premium", headers=outsider).status_code == 404


def test_billing_detail_is_parents_only(client):
    """The subscription block (billing trouble is private) is null for
    non-parents; supporters additionally never see the grants list."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id)
    supporter = make_supporter(client, parent, family_id)
    make_premium(client, parent, family_id)
    client.post(f"/families/{family_id}/premium/gift-checkout", json={}, headers=gran)

    s = premium_status(client, parent, family_id)
    assert s["subscription"] is not None and s["subscription"]["is_owner"] is True
    assert len(s["grants"]) == 1

    s = premium_status(client, gran, family_id)
    assert s["plan"] == "premium"
    assert s["subscription"] is None
    assert len(s["grants"]) == 1
    assert s["can_gift"] is True and s["can_manage"] is False

    s = premium_status(client, supporter, family_id)
    assert s["subscription"] is None
    assert s["grants"] == []


# --- double-subscribe & gift-on-premium ---

def test_second_checkout_is_blocked(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    second_parent = make_member(client, parent, family_id, "parent2@example.com", "parent")
    make_premium(client, parent, family_id)

    for headers in (parent, second_parent):
        r = client.post(
            f"/families/{family_id}/premium/checkout",
            json={"plan": "monthly"},
            headers=headers,
        )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "already_premium"


def test_gift_on_already_premium_family_stacks(client):
    """Gift coverage doesn't block subscribing and vice versa; the grant
    simply extends the combined end date."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id)
    make_premium(client, parent, family_id)  # annual → ~365d

    before = premium_status(client, parent, family_id)["premium_until"]
    r = client.post(f"/families/{family_id}/premium/gift-checkout", json={}, headers=gran)
    assert r.status_code == 200
    after = premium_status(client, parent, family_id)
    assert after["plan"] == "premium"
    assert after["premium_until"] > before  # combined coverage grew
    assert len(after["grants"]) == 1


# --- local end-to-end flows ---

def test_local_checkout_end_to_end(client, tmp_path):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent, "The Salignas")

    r = client.post(
        f"/families/{family_id}/premium/checkout",
        json={"plan": "monthly"},
        headers=parent,
    )
    assert r.status_code == 200, r.text
    assert f"/family/{family_id}/premium/success?session_id=cs_local_" in r.json()["checkout_url"]

    s = premium_status(client, parent, family_id)
    assert s["plan"] == "premium"
    sub = s["subscription"]
    assert sub["plan"] == "monthly"
    assert sub["status"] == "active"
    assert sub["cancel_at_period_end"] is False
    assert sub["owner_name"] == "Pat"
    assert sub["is_owner"] is True

    assert "premium_activated" in feed_types(client, parent, family_id)

    texts = outbox_texts(tmp_path)
    activation = [t for t in texts if "Welcome to FutureRoots Premium" in t]
    assert len(activation) == 1  # exactly one parent → exactly one email
    assert "To: parent@example.com" in activation[0]
    assert "$9.99 a month" in activation[0]

    # The customer id was persisted for reuse — and never serialized.
    with TestingSession() as db:
        user = db.query(User).filter(User.email == "parent@example.com").one()
        assert user.stripe_customer_id == f"cus_local_{user.id}"
    assert "stripe" not in str(s).lower()


def test_local_gift_end_to_end(client, tmp_path):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent, "The Salignas")
    gran = make_grandparent(client, parent, family_id, name="June")

    r = client.post(
        f"/families/{family_id}/premium/gift-checkout",
        json={"message": "For all the recital videos to come"},
        headers=gran,
    )
    assert r.status_code == 200, r.text
    assert f"/family/{family_id}/premium/gift/success?session_id=" in r.json()["checkout_url"]

    s = premium_status(client, parent, family_id)
    assert s["plan"] == "premium"
    assert s["subscription"] is None  # a gift is not a subscription
    assert len(s["grants"]) == 1
    grant = s["grants"][0]
    assert grant["gifter_name"] == "June"
    assert grant["message"] == "For all the recital videos to come"

    r = client.get(f"/families/{family_id}/feed", headers=parent)
    gifted = [e for e in r.json() if e["type"] == "premium_gifted"]
    assert len(gifted) == 1
    assert gifted[0]["payload"]["gifter_name"] == "June"
    assert gifted[0]["payload"]["months"] == 12
    assert gifted[0]["payload"]["message"] == "For all the recital videos to come"
    # No amounts on the feed — "a year of Premium" is the unit of love.
    assert "amount" not in gifted[0]["payload"]

    texts = outbox_texts(tmp_path)
    # No doubled article: "The Salignas" already begins with "The", so the
    # phrase is "The Salignas family" — never "the The Salignas family".
    receipt = [t for t in texts if "Your gift to The Salignas family is live" in t]
    assert not [t for t in texts if "the The Salignas" in t]
    assert len(receipt) == 1 and "To: gran@example.com" in receipt[0]
    assert "$99.00" in receipt[0]
    received = [t for t in texts if "June gave your family a year of Premium" in t]
    assert len(received) == 1 and "To: parent@example.com" in received[0]
    assert "For all the recital videos to come" in received[0]

    # The gift message never left the local DB (it lives on intent + grant).
    with TestingSession() as db:
        grant_row = db.query(PremiumGrant).one()
        assert grant_row.message == "For all the recital videos to come"
        assert grant_row.amount_cents == 9900


def test_sync_binds_subscription_to_authorized_family_not_metadata(client, monkeypatch):
    """/sync authorizes the PATH family, then must pin the mirror row to it —
    never to a second family_id carried in the live subscription's own
    metadata blob (which could be stale or attacker-influenced)."""
    from app.services import payments as pay
    from app.services.payments import CheckoutResult, SubscriptionState

    parent = signup(client, "parent@example.com", "Pat")
    family_a = create_family(client, parent, "Family A")
    other = signup(client, "other@example.com", "Otto")
    family_b = create_family(client, other, "Family B")

    owner_id = _user_id("parent@example.com")
    sub_id = "sub_sync_bind"

    # The checkout session (verified against the path family) points at A.
    result = CheckoutResult(
        session_id="cs_sync_bind",
        kind="premium_subscription",
        paid=True,
        subscription_id=sub_id,
        payment_intent_id=None,
        amount_total=9900,
        currency="usd",
        price_id="price_test",
        metadata={
            "kind": "premium_subscription",
            "family_id": family_a,
            "owner_user_id": str(owner_id),
        },
    )
    # The live subscription's OWN metadata points at a DIFFERENT family (B).
    state = SubscriptionState(
        subscription_id=sub_id,
        customer_id="cus_test",
        status="active",
        price_id="price_test",
        current_period_end=utcnow() + timedelta(days=365),
        cancel_at_period_end=False,
        metadata={
            "kind": "premium_subscription",
            "family_id": family_b,
            "owner_user_id": str(_user_id("other@example.com")),
        },
    )
    monkeypatch.setattr(pay._provider, "checkout_result", lambda sid: result, raising=False)
    monkeypatch.setattr(pay._provider, "subscription_state", lambda sid: state, raising=False)

    r = client.post(
        f"/families/{family_a}/premium/sync",
        json={"session_id": "cs_sync_bind"},
        headers=parent,
    )
    assert r.status_code == 200, r.text

    with TestingSession() as db:
        row = (
            db.query(FamilySubscription)
            .filter(FamilySubscription.stripe_subscription_id == sub_id)
            .one()
        )
        assert str(row.family_id) == family_a  # authorized family, not B
        assert row.owner_user_id == owner_id

    # Family B was never made premium off another family's /sync.
    assert (
        client.get(f"/families/{family_b}/premium", headers=other).json()["plan"]
        == "free"
    )


def test_abandoned_gift_checkout_leaves_no_grant_no_email(client, tmp_path):
    """A gift intent row alone (checkout started, never paid) grants nothing."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id)

    from app.models import PremiumGiftIntent

    with TestingSession() as db:
        gifter = db.query(User).filter(User.email == "gran@example.com").one()
        db.add(
            PremiumGiftIntent(
                family_id=uuid.UUID(family_id),
                gifter_user_id=gifter.id,
                stripe_checkout_session_id="cs_abandoned",
                message="never paid",
            )
        )
        db.commit()

    assert premium_status(client, parent, family_id)["plan"] == "free"
    assert not [t for t in outbox_texts(tmp_path) if "gave your family" in t]


# --- cancel / resume ---

def test_cancel_and_resume_flow(client, tmp_path):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    make_premium(client, parent, family_id)

    r = client.post(f"/families/{family_id}/premium/cancel", headers=parent)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["plan"] == "premium"  # cancel never ends Premium early
    assert s["subscription"]["cancel_at_period_end"] is True

    confirmations = [t for t in outbox_texts(tmp_path) if "Premium stays on until" in t]
    assert len(confirmations) == 1

    # Cancel again: idempotent, and no duplicate confirmation email.
    r = client.post(f"/families/{family_id}/premium/cancel", headers=parent)
    assert r.status_code == 200
    assert len([t for t in outbox_texts(tmp_path) if "Premium stays on until" in t]) == 1

    r = client.post(f"/families/{family_id}/premium/resume", headers=parent)
    assert r.status_code == 200
    assert r.json()["subscription"]["cancel_at_period_end"] is False
    assert r.json()["plan"] == "premium"


def test_resume_without_pending_cancel_409(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    make_premium(client, parent, family_id)
    assert client.post(f"/families/{family_id}/premium/resume", headers=parent).status_code == 409


def test_cancel_without_subscription_409(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    assert client.post(f"/families/{family_id}/premium/cancel", headers=parent).status_code == 409
    assert client.post(f"/families/{family_id}/premium/portal", headers=parent).status_code == 409


# --- enforcement at the choke points ---

def _assert_premium_required(r, capability: str):
    assert r.status_code == 402, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "premium_required"
    assert detail["capability"] == capability


def test_video_upload_ticket_gated_on_child_media(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)

    r = client.post(
        f"/children/{child_id}/media", json={"content_type": "video/mp4"}, headers=parent
    )
    _assert_premium_required(r, "video_upload")

    # Photos and voice stay free — zero premium friction on the free path.
    assert client.post(
        f"/children/{child_id}/media", json={"content_type": "image/png"}, headers=parent
    ).status_code == 201
    assert client.post(
        f"/children/{child_id}/media", json={"content_type": "audio/webm"}, headers=parent
    ).status_code == 201

    make_premium(client, parent, family_id)
    assert client.post(
        f"/children/{child_id}/media", json={"content_type": "video/mp4"}, headers=parent
    ).status_code == 201


def test_video_upload_ticket_gated_on_family_media(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)

    r = client.post(
        f"/families/{family_id}/media", json={"content_type": "video/mp4"}, headers=parent
    )
    _assert_premium_required(r, "video_upload")
    assert client.post(
        f"/families/{family_id}/media", json={"content_type": "image/png"}, headers=parent
    ).status_code == 201

    make_premium(client, parent, family_id)
    assert client.post(
        f"/families/{family_id}/media", json={"content_type": "video/mp4"}, headers=parent
    ).status_code == 201


def test_call_endpoints_gated_but_reads_and_leave_stay_open(client):
    """join/token/heartbeat/children/planned-set 402 on a free family; state,
    planned reads, clearing, and a graceful leave always work."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    base = f"/families/{family_id}/call"

    _assert_premium_required(client.post(f"{base}/join", headers=parent), "family_video_call")
    _assert_premium_required(client.post(f"{base}/token", headers=parent), "family_video_call")
    _assert_premium_required(client.post(f"{base}/heartbeat", headers=parent), "family_video_call")
    _assert_premium_required(
        client.put(f"{base}/children", json={"child_ids": []}, headers=parent),
        "family_video_call",
    )
    _assert_premium_required(
        client.put(
            f"{base}/planned",
            json={"scheduled_for": "2026-08-01T18:00:00Z"},
            headers=parent,
        ),
        "family_video_call",
    )

    # Never gated: reads + graceful exit.
    assert client.get(base, headers=parent).status_code == 200
    assert client.get(f"{base}/planned", headers=parent).status_code == 200
    assert client.post(f"{base}/leave", headers=parent).status_code == 200
    assert client.delete(f"{base}/planned", headers=parent).status_code == 204


def test_supporter_gets_403_not_402_on_calls_even_when_premium(client):
    """A supporter who gifted Premium still can't join calls: the gift changes
    entitlements, never access rules."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    supporter = make_supporter(client, parent, family_id)
    r = client.post(
        f"/families/{family_id}/premium/gift-checkout", json={}, headers=supporter
    )
    assert r.status_code == 200
    assert premium_status(client, parent, family_id)["plan"] == "premium"
    assert client.post(f"/families/{family_id}/call/join", headers=supporter).status_code == 403


def test_downgrade_blocks_new_videos_but_existing_media_plays(client):
    """Nothing is deleted or hidden on downgrade — only NEW video tickets stop."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    make_premium(client, parent, family_id)

    r = client.post(
        f"/children/{child_id}/media", json={"content_type": "video/mp4"}, headers=parent
    )
    assert r.status_code == 201
    media_id = r.json()["media_id"]
    client.put(r.json()["upload_url"], content=b"\x00" * 128, headers=parent)
    assert client.post(f"/media/{media_id}/complete", headers=parent).status_code == 204
    r = client.post(
        f"/children/{child_id}/vault",
        json={"type": "video", "title": "First steps", "media_id": media_id},
        headers=parent,
    )
    assert r.status_code == 201

    # Hard downgrade: flip the mirror row to canceled directly.
    with TestingSession() as db:
        sub = db.query(FamilySubscription).one()
        sub.status = SubscriptionStatus.canceled
        db.commit()

    _assert_premium_required(
        client.post(
            f"/children/{child_id}/media", json={"content_type": "video/mp4"}, headers=parent
        ),
        "video_upload",
    )
    token = media_token(client, parent)
    assert client.get(f"/media/{media_id}?token={token}").status_code == 200
    titles = [i["title"] for i in client.get(f"/children/{child_id}/vault", headers=parent).json()]
    assert "First steps" in titles


# --- lazy lifecycle (request-driven, no cron) ---

def test_gift_ending_soon_email_sent_once(client, tmp_path):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    make_grandparent(client, parent, family_id, name="June")
    insert_grant(
        family_id, "gran@example.com",
        starts_delta=timedelta(days=-362), ends_delta=timedelta(days=3),
    )

    assert premium_status(client, parent, family_id)["plan"] == "premium"
    ending = [t for t in outbox_texts(tmp_path) if "gift of Premium ends on" in t]
    assert len(ending) == 1
    assert "To: parent@example.com" in ending[0]
    assert "June" in ending[0]

    # CASL (compliance finding M2): recipients never opted into marketing, so
    # this must stay purely informational — no pricing, no upsell, and the CTA
    # goes to the family's own Plan settings, never the purchase page.
    assert "$9.99" not in ending[0] and "$99" not in ending[0]
    assert "returns to the Free plan" in ending[0]
    assert "stays yours" in ending[0]
    assert "See your family's plan" in ending[0]
    assert f"/family/{family_id}#plan" in ending[0]
    assert f"/family/{family_id}/premium" not in ending[0]

    # Poll again (and via family detail): the send-once log holds.
    premium_status(client, parent, family_id)
    client.get(f"/families/{family_id}", headers=parent)
    assert len([t for t in outbox_texts(tmp_path) if "gift of Premium ends on" in t]) == 1


def test_gift_ending_soon_suppressed_when_subscription_continues(client, tmp_path):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    make_grandparent(client, parent, family_id)
    insert_grant(
        family_id, "gran@example.com",
        starts_delta=timedelta(days=-362), ends_delta=timedelta(days=3),
    )
    insert_subscription(family_id, "parent@example.com")  # auto-renew continues coverage
    premium_status(client, parent, family_id)
    assert not [t for t in outbox_texts(tmp_path) if "gift of Premium ends on" in t]


def test_gift_lapse_premium_ended_email_once(client, tmp_path):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    make_grandparent(client, parent, family_id)
    insert_grant(
        family_id, "gran@example.com",
        starts_delta=timedelta(days=-400), ends_delta=timedelta(days=-1),
    )

    s = premium_status(client, parent, family_id)
    assert s["plan"] == "free"
    ended = [t for t in outbox_texts(tmp_path) if "back on the Free plan" in t]
    assert len(ended) == 1

    premium_status(client, parent, family_id)
    assert len([t for t in outbox_texts(tmp_path) if "back on the Free plan" in t]) == 1


def test_gift_lapsed_long_ago_sends_no_stale_premium_ended_email(client, tmp_path):
    """The 'back on the Free plan' email is a lifecycle moment, not history:
    coverage that ended beyond PREMIUM_ENDED_STALE_AFTER stays silent (this
    also makes the maintenance sweep's 1-year premium_email_log prune safe —
    nothing can re-fire from a pruned dedupe row)."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    make_grandparent(client, parent, family_id)
    insert_grant(
        family_id, "gran@example.com",
        starts_delta=timedelta(days=-430), ends_delta=timedelta(days=-65),
    )

    assert premium_status(client, parent, family_id)["plan"] == "free"
    assert not [t for t in outbox_texts(tmp_path) if "back on the Free plan" in t]


# --- owner departure hook ---

def test_owner_departure_cancels_at_period_end_and_emails_parents(client, tmp_path):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    make_member(client, parent, family_id, "parent2@example.com", "parent", "Sam")
    make_premium(client, parent, family_id)

    from app.services.premium import handle_owner_departure

    with TestingSession() as db:
        owner = db.query(User).filter(User.email == "parent@example.com").one()
        handle_owner_departure(db, uuid.UUID(family_id), owner.id)
        db.commit()

    s = premium_status(client, parent, family_id)
    assert s["plan"] == "premium"  # runs to period end, never cut short
    assert s["subscription"]["cancel_at_period_end"] is True

    departure = [t for t in outbox_texts(tmp_path) if "no longer part of the family" in t]
    assert len(departure) == 1
    assert "To: parent2@example.com" in departure[0]  # never to the departed owner
