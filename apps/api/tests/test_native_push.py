"""Native (iOS/Android) push: Expo token enrollment + the deliver_native
fan-out wired into the same notify() batch as web push.

The Expo Push API is exercised with a FAKE httpx (the module-swap pattern) so no
network happens; no VAPID key is set, which also proves native delivery is
independent of the web-push feature flag (web stays dark, native still fires).
"""

import uuid
from datetime import timedelta

import pytest

from app.models import NativePushToken, User, utcnow
from app.services import notify_native

from .conftest import TestingSession, add_child, create_family, signup
from .test_goals import make_grandparent
from .test_me import prefs
from .test_supporter_access import make_supporter


# --- fake Expo push service --------------------------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeHttpx:
    """Records POSTs to the Expo push API and returns one receipt per message.
    ``receipts_for[token]`` overrides the receipt for a given token (e.g. a
    DeviceNotRegistered error)."""

    def __init__(self):
        self.calls = []
        self.receipts_for: dict[str, dict] = {}

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        data = [
            self.receipts_for.get(m["to"], {"status": "ok", "id": "receipt-id"})
            for m in json
        ]
        return _FakeResponse({"data": data})


@pytest.fixture()
def expo(monkeypatch):
    fake = _FakeHttpx()
    monkeypatch.setattr(notify_native, "httpx", fake)
    return fake


def register(client, headers, token, platform="ios", device_label=None):
    body = {"expo_push_token": token, "platform": platform}
    if device_label is not None:
        body["device_label"] = device_label
    r = client.post("/me/native-push-tokens", json=body, headers=headers)
    assert r.status_code == 201, r.text


def _bells(user_email, kind=None):
    from app.models import Notification

    with TestingSession() as db:
        uid = db.query(User).filter(User.email == user_email).one().id
        q = db.query(Notification).filter(Notification.user_id == uid)
        if kind is not None:
            q = q.filter(Notification.kind == kind)
        return q.all()


def _token_row(expo_token):
    with TestingSession() as db:
        return (
            db.query(NativePushToken)
            .filter(NativePushToken.expo_push_token == expo_token)
            .first()
        )


# --- registration: upsert + last_seen refresh + reassignment ----------------


def test_register_creates_token(client):
    u = signup(client, "u@example.com")
    register(client, u, "ExponentPushToken[abc]", platform="ios", device_label="Rose's iPhone")
    row = _token_row("ExponentPushToken[abc]")
    assert row is not None
    assert row.platform.value == "ios"
    assert row.device_label == "Rose's iPhone"
    with TestingSession() as db:
        assert db.query(NativePushToken).count() == 1


def test_register_upserts_and_refreshes_last_seen(client):
    a = signup(client, "a@example.com")
    b = signup(client, "b@example.com")
    register(client, a, "ExponentPushToken[shared]", platform="ios", device_label="old")

    # Age the row so a refresh is observable.
    with TestingSession() as db:
        row = (
            db.query(NativePushToken)
            .filter(NativePushToken.expo_push_token == "ExponentPushToken[shared]")
            .one()
        )
        old = utcnow() - timedelta(days=3)
        row.created_at = old
        row.last_seen_at = old
        db.commit()

    # Same device, new holder + new platform/label: reassign + refresh, no new row.
    register(client, b, "ExponentPushToken[shared]", platform="android", device_label="new")

    with TestingSession() as db:
        rows = db.query(NativePushToken).all()
        assert len(rows) == 1  # token unique — upserted in place
        row = rows[0]
        b_id = db.query(User).filter(User.email == "b@example.com").one().id
        assert row.user_id == b_id            # reassigned to latest holder
        assert row.platform.value == "android"
        assert row.device_label == "new"
        assert row.last_seen_at > row.created_at  # last_seen refreshed


def test_unregister_removes_own_token(client):
    u = signup(client, "u@example.com")
    register(client, u, "ExponentPushToken[x]")
    r = client.post(
        "/me/native-push-tokens/unregister",
        json={"expo_push_token": "ExponentPushToken[x]"},
        headers=u,
    )
    assert r.status_code == 200, r.text
    assert _token_row("ExponentPushToken[x]") is None


def test_unregister_only_touches_own(client):
    a = signup(client, "a@example.com")
    b = signup(client, "b@example.com")
    register(client, a, "ExponentPushToken[a]")
    # b tries to remove a's token: scoped to caller, so it's a no-op.
    client.post(
        "/me/native-push-tokens/unregister",
        json={"expo_push_token": "ExponentPushToken[a]"},
        headers=b,
    )
    assert _token_row("ExponentPushToken[a]") is not None


# --- delivery: same batch, same prefs gating, right Expo shape --------------


def test_notify_sends_native_push_with_right_shape(client, expo):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")
    register(client, gran, "ExponentPushToken[gran]", platform="ios")

    client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    )

    # Exactly one POST to the hardcoded Expo host, one message, right shape.
    assert len(expo.calls) == 1
    call = expo.calls[0]
    assert call["url"] == notify_native.EXPO_PUSH_URL
    messages = call["json"]
    assert len(messages) == 1
    msg = messages[0]
    assert msg["to"] == "ExponentPushToken[gran]"
    assert msg["title"] and msg["body"]
    assert msg["data"]["tag"] == "milestone"
    assert msg["data"]["url"]  # in-app tap target carried in data
    # milestone uses the default TTL/urgency map -> 1-day, normal priority.
    assert msg["ttl"] == 86_400
    assert msg["priority"] == "default"
    # No access token configured -> unauthenticated send (no bearer header).
    assert "Authorization" not in call["headers"]
    # Bell still written for Gran.
    assert len(_bells("gran@example.com", "milestone")) == 1


def test_access_token_sends_bearer_header(client, expo, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "expo_access_token", "secret-expo-token")
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")
    register(client, gran, "ExponentPushToken[gran]", platform="android")

    client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    )
    assert expo.calls[0]["headers"]["Authorization"] == "Bearer secret-expo-token"


def test_native_push_gated_by_preference(client, expo):
    """Muting push_milestone suppresses the native push but the bell still
    writes — native obeys the SAME 22-boolean matrix as web."""
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")
    register(client, gran, "ExponentPushToken[gran]", platform="ios")
    client.put(
        "/me/notifications", json=prefs(push_milestone=False), headers=gran
    )

    client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    )
    assert expo.calls == []                                    # muted -> not sent
    assert len(_bells("gran@example.com", "milestone")) == 1   # bell still writes


def test_supporter_never_gets_native_push(client, expo):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    supporter = make_supporter(client, parent, family_id)
    register(client, supporter, "ExponentPushToken[coach]", platform="ios")

    client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    )
    assert expo.calls == []


def test_device_not_registered_prunes_token(client, expo):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")
    register(client, gran, "ExponentPushToken[gone]", platform="ios")

    # Expo reports the token is dead.
    expo.receipts_for["ExponentPushToken[gone]"] = {
        "status": "error",
        "message": "device not registered",
        "details": {"error": "DeviceNotRegistered"},
    }

    client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    )
    assert len(expo.calls) == 1
    assert _token_row("ExponentPushToken[gone]") is None  # pruned
    with TestingSession() as db:
        assert db.query(NativePushToken).count() == 0


def test_other_receipt_errors_do_not_prune(client, expo):
    """A non-DeviceNotRegistered error is logged and swallowed, not pruned."""
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")
    register(client, gran, "ExponentPushToken[flaky]", platform="ios")

    expo.receipts_for["ExponentPushToken[flaky]"] = {
        "status": "error",
        "message": "message rate exceeded",
        "details": {"error": "MessageRateExceeded"},
    }
    client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    )
    assert _token_row("ExponentPushToken[flaky]") is not None  # retained


def test_feature_dark_when_no_tokens(client, expo):
    """No enrolled tokens -> no Expo call, no error (feature-dark by absence)."""
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    make_grandparent(client, parent, family_id, name="Gran")

    client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    )
    assert expo.calls == []


def test_send_error_is_swallowed(client, monkeypatch):
    """A transport error never breaks the fan-out or the domain action."""
    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(notify_native.httpx, "post", boom)
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")
    register(client, gran, "ExponentPushToken[gran]", platform="ios")

    r = client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    )
    assert r.status_code == 201, r.text  # action succeeds despite push failure
    assert len(_bells("gran@example.com", "milestone")) == 1
    assert _token_row("ExponentPushToken[gran]") is not None  # not pruned on error
