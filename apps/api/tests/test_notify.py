"""The expanded notification system: the unified dispatch (bell always, email
and push pref-gated), web-push subscriptions, the in-app inbox, and the admin
broadcast.

Push is exercised with a FAKE pywebpush module (the fake-module pattern from
test_config_secrets.py) so no network happens and no real VAPID key is needed;
settings.vapid_private_key is monkeypatched on so the feature is "lit".
"""

import sys
import types
import uuid

import pytest

from app.config import settings
from app.models import (
    Contribution,
    FeedEvent,
    FeedEventType,
    FundAccount,
    Notification,
    PushSubscription,
)
from app.services.notifications import DEFAULT_PREFS

from .conftest import (
    TestingSession,
    add_child,
    create_family,
    make_premium,
    setup_fund,
    signup,
)
from .test_contributions import contribute
from .test_goals import make_grandparent
from .test_supporter_access import make_supporter
from .test_stripe_webhook import intent_event, sign, webhook_secret  # noqa: F401


# --- fake web push -----------------------------------------------------------


class _FakePush:
    """Records webpush() calls and can be told to raise for a given endpoint."""

    def __init__(self):
        self.calls = []
        self.raise_for: dict[str, Exception] = {}

        class WebPushException(Exception):
            def __init__(self, message="", response=None):
                super().__init__(message)
                self.response = response

        self.WebPushException = WebPushException

    def webpush(self, **kwargs):
        endpoint = kwargs["subscription_info"]["endpoint"]
        self.calls.append(kwargs)
        exc = self.raise_for.get(endpoint)
        if exc is not None:
            raise exc


@pytest.fixture()
def push(monkeypatch):
    fake = _FakePush()
    module = types.ModuleType("pywebpush")
    module.webpush = fake.webpush
    module.WebPushException = fake.WebPushException
    monkeypatch.setitem(sys.modules, "pywebpush", module)
    monkeypatch.setattr(settings, "vapid_private_key", "test-private-key")
    monkeypatch.setattr(settings, "vapid_public_key", "test-public-key")
    monkeypatch.setattr(settings, "vapid_subject", "mailto:test@futureroots.app")
    return fake


def subscribe_push(client, headers, endpoint):
    r = client.post(
        "/me/push-subscriptions",
        json={"endpoint": endpoint, "p256dh": "p256dh-key", "auth": "auth-key"},
        headers=headers,
    )
    assert r.status_code == 201, r.text


def _bells(user_email, kind=None):
    with TestingSession() as db:
        from app.models import User

        uid = db.query(User).filter(User.email == user_email).one().id
        q = db.query(Notification).filter(Notification.user_id == uid)
        if kind is not None:
            q = q.filter(Notification.kind == kind)
        return q.all()


# --- prefs shape -------------------------------------------------------------


def test_prefs_expose_all_20_fields_plus_public_key(client):
    parent = signup(client, "parent@example.com")
    body = client.get("/me/notifications", headers=parent).json()
    for field in DEFAULT_PREFS:
        assert field in body
    assert body["push_public_key"] == ""  # dark by default


def test_prefs_public_key_served_when_lit(client, push):
    parent = signup(client, "parent@example.com")
    body = client.get("/me/notifications", headers=parent).json()
    assert body["push_public_key"] == "test-public-key"


# --- bell is always written; interruptions are pref-gated --------------------


def test_bell_written_even_when_email_and_push_opted_out(client, tmp_path, monkeypatch, push):
    from app.services import email as email_module

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")
    # Gran mutes milestone email AND push, but still has a device.
    from .test_me import prefs

    client.put(
        "/me/notifications",
        json=prefs(email_milestone=False, push_milestone=False),
        headers=gran,
    )
    subscribe_push(client, gran, "https://fcm.googleapis.com/gran")
    for f in outbox.glob("*.txt"):
        f.unlink()

    client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    )
    # Bell row still written; no email, no push (both muted).
    assert len(_bells("gran@example.com", "milestone")) == 1
    assert list(outbox.glob("*.txt")) == []
    assert push.calls == []


def test_supporter_never_gets_family_notifications(client, push):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    supporter = make_supporter(client, parent, family_id)
    subscribe_push(client, supporter, "https://fcm.googleapis.com/coach")

    client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    )
    assert _bells("coach@example.com") == []
    assert push.calls == []


# --- legacy-kind migration keeps email content + gating, adds the bell -------


def test_new_member_email_unchanged_and_bell_added(client, tmp_path, monkeypatch):
    from app.services import email as email_module

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    for f in outbox.glob("*.txt"):
        f.unlink()
    make_grandparent(client, parent, family_id, name="Gran")

    emails = [f.read_text(encoding="utf-8") for f in outbox.glob("*.txt")]
    joined = [e for e in emails if "joined" in e]
    # Existing email behavior preserved (Pat is told, default on).
    assert any("To: parent@example.com" in e for e in joined)
    # And Pat now also has a bell row for the new member.
    assert len(_bells("parent@example.com", "new_member")) == 1


# --- the critical one: webhook replay = exactly one of everything ------------


def _pending_contribution_from_gran(client):
    """Pat (parent) + Grandma Rose (grandparent contributor) + Emma + fund.
    Returns (pat_headers, child_id, intent_id, account_id)."""
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    setup_fund(client, parent, child_id)
    gran = make_grandparent(client, parent, family_id, name="Grandma Rose")
    c = contribute(client, gran, child_id, amount_cents=2500)
    with TestingSession() as db:
        intent_id = db.get(Contribution, uuid.UUID(c["id"])).provider_payment_id
        account_id = (
            db.query(FundAccount)
            .filter(FundAccount.child_id == uuid.UUID(child_id))
            .one()
            .stripe_account_id
        )
    return parent, child_id, intent_id, account_id


def test_webhook_replay_delivers_exactly_once(client, tmp_path, monkeypatch, push, webhook_secret):
    """Three deliveries of the same payment_intent.succeeded → exactly one bell
    row, one push per subscription, one email set. The bell is atomic with the
    ledger, so replays that skip settling add nothing."""
    from app.services import email as email_module

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    parent, child_id, intent_id, account_id = _pending_contribution_from_gran(client)
    subscribe_push(client, parent, "https://fcm.googleapis.com/pat")
    for f in outbox.glob("*.txt"):
        f.unlink()

    payload = intent_event("payment_intent.succeeded", intent_id, account_id, 103)
    for _ in range(3):
        r = client.post(
            "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
        )
        assert r.status_code == 200

    # exactly one bell row for the parent
    assert len(_bells("parent@example.com", "contribution")) == 1
    # exactly one push (one subscription, one settle)
    assert len(push.calls) == 1
    assert push.calls[0]["subscription_info"]["endpoint"] == "https://fcm.googleapis.com/pat"
    # exactly one email set (to the parent), and NO amount in bell/push
    mail = [f.read_text(encoding="utf-8") for f in outbox.glob("*.txt")]
    assert len(mail) == 1 and "To: parent@example.com" in mail[0]
    assert "25.00" not in _bells("parent@example.com", "contribution")[0].body


def test_webhook_integrity_race_delivers_nothing(client, tmp_path, monkeypatch, push, webhook_secret):
    """The loser of the concurrent settle race (ledger row already committed,
    contribution still read as pending) rolls back: no bell, no push, no email."""
    from app.models import FundLedgerEntry, LedgerEntryType
    from app.services import email as email_module

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    parent, child_id, intent_id, account_id = _pending_contribution_from_gran(client)
    subscribe_push(client, parent, "https://fcm.googleapis.com/pat")
    for f in outbox.glob("*.txt"):
        f.unlink()

    with TestingSession() as db:
        contribution = (
            db.query(Contribution).filter(Contribution.provider_payment_id == intent_id).one()
        )
        account = (
            db.query(FundAccount).filter(FundAccount.child_id == uuid.UUID(child_id)).one()
        )
        db.add(  # the winner's ledger write, already durable
            FundLedgerEntry(
                account_id=account.id,
                amount_cents=2500 - 103,
                entry_type=LedgerEntryType.contribution,
                source_contribution_id=contribution.id,
            )
        )
        db.commit()

    payload = intent_event("payment_intent.succeeded", intent_id, account_id, 103)
    r = client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
    )
    assert r.status_code == 200 and r.json() == {"received": True}

    assert _bells("parent@example.com", "contribution") == []
    assert push.calls == []
    assert list(outbox.glob("*.txt")) == []


# --- call_live: once per call, supporter-excluded, NO feed event -------------


def test_call_live_notifies_family_no_feed_event(client, push, monkeypatch):
    monkeypatch.setattr(
        settings, "agora_app_certificate", "0123456789abcdef0123456789abcdef"
    )
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    make_premium(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id, name="Gran")
    supporter = make_supporter(client, parent, family_id)
    subscribe_push(client, gran, "https://fcm.googleapis.com/gran")

    with TestingSession() as db:
        feed_before = (
            db.query(FeedEvent).filter(FeedEvent.family_id == uuid.UUID(family_id)).count()
        )

    r = client.post(f"/families/{family_id}/call/join", headers=parent)
    assert r.status_code == 201, r.text
    # a second join (same live call) must not re-ring the family
    r = client.post(f"/families/{family_id}/call/join", headers=parent)
    assert r.status_code == 200

    assert len(_bells("gran@example.com", "call_live")) == 1  # once
    assert _bells("parent@example.com", "call_live") == []    # starter excluded
    assert _bells("coach@example.com", "call_live") == []     # supporter excluded
    assert len(push.calls) == 1
    # Calls emit NO feed events at all: the count is unchanged by the join.
    with TestingSession() as db:
        feed_after = (
            db.query(FeedEvent).filter(FeedEvent.family_id == uuid.UUID(family_id)).count()
        )
    assert feed_after == feed_before


# --- fund_activated: fires once on the transition, with a feed event --------


def test_fund_activated_fires_once(client, push):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    subscribe_push(client, parent, "https://fcm.googleapis.com/pat")
    setup_fund(client, parent, child_id)  # setup + status poll flips to active

    assert len(_bells("parent@example.com", "fund_activated")) == 1
    with TestingSession() as db:
        assert (
            db.query(FeedEvent)
            .filter(FeedEvent.type == FeedEventType.fund_activated)
            .count()
            == 1
        )
    # polling status again does not re-fire
    client.get(f"/children/{child_id}/fund/setup/status", headers=parent)
    assert len(_bells("parent@example.com", "fund_activated")) == 1
    assert len(push.calls) == 1


# --- capsules: seal notifies family; lazy release fires once ----------------


def test_capsule_sealed_and_lazy_release(client, push):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")

    # Seal a capsule that is already due (past date) — sealer is Gran.
    r = client.post(
        f"/children/{child_id}/capsules",
        json={
            "type": "letter",
            "body": "For your 18th",
            "release_condition": "date",
            "release_date": "2000-01-01",
        },
        headers=gran,
    )
    assert r.status_code == 201, r.text
    # capsule_sealed → family excl. sealer (Pat gets it, Gran does not)
    assert len(_bells("parent@example.com", "capsule_sealed")) == 1
    assert _bells("gran@example.com", "capsule_sealed") == []

    # Listing runs the lazy release scheduler → capsule_released to parents.
    client.get(f"/children/{child_id}/capsules", headers=parent)
    assert len(_bells("parent@example.com", "capsule_released")) == 1
    # Idempotent: a second read does not re-release / re-notify.
    client.get(f"/children/{child_id}/capsules", headers=parent)
    assert len(_bells("parent@example.com", "capsule_released")) == 1


# --- push subscriptions: 503-dark, upsert/reassign, dead-sub prune ----------


def test_subscribe_503_when_dark(client):
    parent = signup(client, "parent@example.com")
    r = client.post(
        "/me/push-subscriptions",
        json={"endpoint": "https://fcm.googleapis.com/x", "p256dh": "k", "auth": "a"},
        headers=parent,
    )
    assert r.status_code == 503


def test_subscribe_upsert_reassigns_endpoint(client, push):
    a = signup(client, "a@example.com")
    b = signup(client, "b@example.com")
    subscribe_push(client, a, "https://fcm.googleapis.com/shared")
    subscribe_push(client, b, "https://fcm.googleapis.com/shared")  # same device, new user
    with TestingSession() as db:
        subs = db.query(PushSubscription).all()
        assert len(subs) == 1  # still one row (endpoint unique)
        from app.models import User

        b_id = db.query(User).filter(User.email == "b@example.com").one().id
        assert subs[0].user_id == b_id  # reassigned to the latest holder


def test_unsubscribe_only_touches_own(client, push):
    a = signup(client, "a@example.com")
    b = signup(client, "b@example.com")
    subscribe_push(client, a, "https://fcm.googleapis.com/a")
    subscribe_push(client, b, "https://fcm.googleapis.com/b")
    # a tries to remove b's endpoint: no-op (scoped to caller)
    client.post(
        "/me/push-subscriptions/unsubscribe",
        json={"endpoint": "https://fcm.googleapis.com/b"},
        headers=a,
    )
    with TestingSession() as db:
        assert db.query(PushSubscription).count() == 2
    client.post(
        "/me/push-subscriptions/unsubscribe",
        json={"endpoint": "https://fcm.googleapis.com/a"},
        headers=a,
    )
    with TestingSession() as db:
        assert db.query(PushSubscription).count() == 1


def test_dead_subscription_pruned_on_410(client, tmp_path, monkeypatch, push, webhook_secret):
    from app.services import email as email_module

    monkeypatch.setattr(
        email_module, "_sender", email_module.OutboxEmailSender(tmp_path / "outbox")
    )
    parent, child_id, intent_id, account_id = _pending_contribution_from_gran(client)
    subscribe_push(client, parent, "https://fcm.googleapis.com/gone")

    # The push service reports the subscription is gone.
    resp = types.SimpleNamespace(status_code=410)
    push.raise_for["https://fcm.googleapis.com/gone"] = push.WebPushException("gone", response=resp)

    payload = intent_event("payment_intent.succeeded", intent_id, account_id, 103)
    r = client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": sign(payload)}
    )
    assert r.status_code == 200
    with TestingSession() as db:
        assert db.query(PushSubscription).count() == 0  # pruned


# --- inbox: pagination, mark-read, cross-user 404 ---------------------------


def test_inbox_pagination_and_read(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")
    for i in range(3):
        client.post(
            f"/children/{child_id}/milestones", json={"title": f"Step {i}"}, headers=parent
        )
    # Gran has 3 milestone bells (+ nothing else meaningful here).
    r = client.get("/me/inbox?limit=2", headers=gran)
    body = r.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None
    r2 = client.get(f"/me/inbox?limit=2&cursor={body['next_cursor']}", headers=gran)
    assert len(r2.json()["items"]) >= 1
    assert r2.json()["next_cursor"] is None

    assert client.get("/me/inbox/unread-count", headers=gran).json()["count"] == 3
    first_id = body["items"][0]["id"]
    assert client.post(f"/me/inbox/{first_id}/read", headers=gran).status_code == 200
    assert client.get("/me/inbox/unread-count", headers=gran).json()["count"] == 2
    client.post("/me/inbox/read-all", headers=gran)
    assert client.get("/me/inbox/unread-count", headers=gran).json()["count"] == 0


def test_inbox_mark_read_cross_user_404(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")
    client.post(f"/children/{child_id}/milestones", json={"title": "Hi"}, headers=parent)
    gran_item = client.get("/me/inbox", headers=gran).json()["items"][0]["id"]
    # Parent cannot read Gran's notification.
    assert client.post(f"/me/inbox/{gran_item}/read", headers=parent).status_code == 404


# --- admin broadcast --------------------------------------------------------


def _make_admin(client, email="admin@example.com"):
    from app.models import User, UserRole

    headers = signup(client, email, "Admin")
    with TestingSession() as db:
        db.query(User).filter(User.email == email).one().role = UserRole.admin
        db.commit()
    return headers


def test_broadcast_requires_admin(client):
    user = signup(client, "user@example.com")
    r = client.post("/admin/broadcast", json={"title": "Hi", "body": "There"}, headers=user)
    assert r.status_code == 403


def test_broadcast_dry_run_counts_without_sending(client, tmp_path, monkeypatch, push):
    from app.services import email as email_module

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    admin = _make_admin(client)
    u1 = signup(client, "u1@example.com")
    subscribe_push(client, u1, "https://fcm.googleapis.com/u1")
    for f in outbox.glob("*.txt"):  # drop signup welcome emails
        f.unlink()

    r = client.post(
        "/admin/broadcast",
        json={"title": "News", "body": "Big news", "include_email": True, "dry_run": True},
        headers=admin,
    )
    body = r.json()
    assert body["dry_run"] is True
    assert body["bell"] >= 2       # admin + u1
    assert body["push"] == 1       # only u1 has a device
    assert body["email"] >= 2
    # nothing actually sent / written
    assert _bells("u1@example.com") == []
    assert push.calls == []
    assert list(outbox.glob("*.txt")) == []


def test_broadcast_bell_for_all_push_and_email_gated(client, tmp_path, monkeypatch, push):
    from app.services import email as email_module
    from .test_me import prefs

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    admin = _make_admin(client)
    opted_out = signup(client, "opt@example.com")
    subscribe_push(client, opted_out, "https://fcm.googleapis.com/opt")
    # Opt fully out of announcements (both channels).
    client.put(
        "/me/notifications",
        json=prefs(email_announcements=False, push_announcements=False),
        headers=opted_out,
    )
    for f in outbox.glob("*.txt"):
        f.unlink()

    r = client.post(
        "/admin/broadcast",
        json={"title": "Update", "body": "Something new", "include_email": True},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    # Bell is written even for the opted-out user (bell is never gated).
    assert len(_bells("opt@example.com", "announcement")) == 1
    # But no push to them (opted out), and no email to them.
    assert push.calls == []
    mail = [f.read_text(encoding="utf-8") for f in outbox.glob("*.txt")]
    assert all("To: opt@example.com" not in m for m in mail)


def test_broadcast_email_off_by_default(client, tmp_path, monkeypatch, push):
    from app.services import email as email_module

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    admin = _make_admin(client)
    u1 = signup(client, "u1@example.com")
    subscribe_push(client, u1, "https://fcm.googleapis.com/u1")
    for f in outbox.glob("*.txt"):  # drop signup welcome emails
        f.unlink()

    r = client.post(
        "/admin/broadcast", json={"title": "Hi", "body": "There"}, headers=admin
    )
    assert r.status_code == 200
    assert r.json()["email"] == 0
    assert list(outbox.glob("*.txt")) == []  # no email by default
    assert len(push.calls) == 1              # push still goes out


# --- maintenance prunes old bell rows ---------------------------------------


def test_maintenance_prunes_old_notifications(client):
    from datetime import timedelta

    from app.models import User, utcnow
    from app.services.maintenance import run_maintenance

    parent = signup(client, "parent@example.com")
    with TestingSession() as db:
        uid = db.query(User).filter(User.email == "parent@example.com").one().id
        db.add(
            Notification(
                user_id=uid, kind="announcement", title="old", body="old",
                created_at=utcnow() - timedelta(days=120),
            )
        )
        db.add(
            Notification(
                user_id=uid, kind="announcement", title="new", body="new",
                created_at=utcnow() - timedelta(days=1),
            )
        )
        db.commit()
    with TestingSession() as db:
        counts = run_maintenance(db)
    assert counts["notifications_pruned"] == 1
    with TestingSession() as db:
        assert db.query(Notification).count() == 1


# --- Fix 1: push endpoint SSRF allowlist -------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/abc123",
        "https://updates.push.services.mozilla.com/wpush/v2/xyz",
        "https://wns2-par02p.notify.windows.com/w/?token=AA",
        "https://web.push.apple.com/QA/abc",
    ],
)
def test_subscribe_accepts_known_push_services(client, push, endpoint):
    parent = signup(client, "parent@example.com")
    r = client.post(
        "/me/push-subscriptions",
        json={"endpoint": endpoint, "p256dh": "k", "auth": "a"},
        headers=parent,
    )
    assert r.status_code == 201, r.text


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://169.254.169.254/latest/meta-data/",   # metadata SSRF, non-https
        "https://169.254.169.254/x",                   # metadata SSRF, IP literal
        "http://localhost:8000",                       # loopback name, non-https
        "https://127.0.0.1/x",                         # loopback IP
        "http://10.0.0.5",                             # private IP, non-https
        "https://10.0.0.5/x",                          # private IP literal
        "https://evil.com/x",                          # unknown origin
        "http://fcm.googleapis.com/x",                 # right host, wrong scheme
    ],
)
def test_subscribe_rejects_ssrf_endpoints(client, push, endpoint):
    parent = signup(client, "parent@example.com")
    r = client.post(
        "/me/push-subscriptions",
        json={"endpoint": endpoint, "p256dh": "k", "auth": "a"},
        headers=parent,
    )
    assert r.status_code == 422, r.text
    with TestingSession() as db:
        assert db.query(PushSubscription).count() == 0  # nothing stored


def test_validate_push_endpoint_unit():
    from app.push_targets import validate_push_endpoint

    assert (
        validate_push_endpoint("https://fcm.googleapis.com/fcm/send/x")
        == "https://fcm.googleapis.com/fcm/send/x"
    )
    for bad in (
        "https://evil.com",
        "https://169.254.169.254/x",
        "http://fcm.googleapis.com/x",
        "https://fcm.googleapis.com.evil.com/x",  # suffix-spoof
    ):
        with pytest.raises(ValueError):
            validate_push_endpoint(bad)


# --- Fix 3: per-user subscription cap ----------------------------------------


def test_push_subscriptions_capped_per_user(client, push):
    from datetime import timedelta

    from app.models import User, utcnow
    from app.routers.me import MAX_PUSH_SUBSCRIPTIONS_PER_USER as CAP

    u = signup(client, "cap@example.com")
    with TestingSession() as db:
        uid = db.query(User).filter(User.email == "cap@example.com").one().id
        base = utcnow()
        for i in range(CAP):  # seed a full complement with distinct, ordered times
            db.add(
                PushSubscription(
                    user_id=uid,
                    endpoint=f"https://fcm.googleapis.com/e{i}",
                    p256dh="k",
                    auth="a",
                    created_at=base + timedelta(seconds=i),
                )
            )
        db.commit()

    # The (CAP+1)-th distinct endpoint evicts the oldest (e0).
    subscribe_push(client, u, f"https://fcm.googleapis.com/e{CAP}")
    with TestingSession() as db:
        eps = {
            s.endpoint
            for s in db.query(PushSubscription)
            .filter(PushSubscription.user_id == uid)
            .all()
        }
    assert len(eps) == CAP
    assert "https://fcm.googleapis.com/e0" not in eps          # oldest evicted
    assert f"https://fcm.googleapis.com/e{CAP}" in eps         # newcomer kept

    # Re-subscribing an existing endpoint updates in place: no new row, no evict.
    subscribe_push(client, u, "https://fcm.googleapis.com/e5")
    with TestingSession() as db:
        count = (
            db.query(PushSubscription)
            .filter(PushSubscription.user_id == uid)
            .count()
        )
    assert count == CAP


# --- Fix 2: broadcast url must be a same-site relative path ------------------


def test_broadcast_accepts_relative_url(client, tmp_path, monkeypatch, push):
    from app.services import email as email_module

    monkeypatch.setattr(
        email_module, "_sender", email_module.OutboxEmailSender(tmp_path / "outbox")
    )
    admin = _make_admin(client)
    r = client.post(
        "/admin/broadcast",
        json={"title": "Hi", "body": "There", "url": "/family", "dry_run": True},
        headers=admin,
    )
    assert r.status_code == 200, r.text


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "https://evil.com", "//evil.com", "@evil.com", "/\\evil.com"],
)
def test_broadcast_rejects_open_redirect_urls(client, url):
    admin = _make_admin(client)
    r = client.post(
        "/admin/broadcast",
        json={"title": "Hi", "body": "There", "url": url, "dry_run": True},
        headers=admin,
    )
    assert r.status_code == 422, r.text
