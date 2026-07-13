"""Family Video Call: one active call per family, presence reaping, planned
calls, and the secret App Certificate never leaving the server."""

from datetime import timedelta

import pytest

from app.config import settings
from app.models import CallStatus

from .conftest import TestingSession, add_child, create_family, signup
from .test_goals import make_grandparent
from .test_supporter_access import make_supporter

# The vendored Agora builder requires a 32-char hex certificate (same shape as
# the App ID). Any such string signs a valid HMAC token in tests.
TEST_CERT = "0123456789abcdef0123456789abcdef"
APP_ID = "c58c8181f4204f07bc1a36d93cae5514"


@pytest.fixture(autouse=True)
def agora_cert(monkeypatch):
    monkeypatch.setattr(settings, "agora_app_certificate", TEST_CERT)


def _token(headers: dict) -> str:
    return headers["Authorization"].removeprefix("Bearer ")


def _join(client, headers, family_id):
    return client.post(f"/families/{family_id}/call/join", headers=headers)


def test_join_creates_call_with_token_and_valid_channel(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)

    r = _join(client, parent, family_id)
    assert r.status_code == 201, r.text
    data = r.json()

    assert data["app_id"] == APP_ID
    assert data["channel_name"].startswith("fr-")
    assert len(data["channel_name"]) == len("fr-") + 32  # token_hex(16)
    assert data["token"].startswith("007")  # Agora AccessToken2 version
    assert 1 <= data["agora_uid"] <= 2**31 - 1
    assert data["expires_at"] > 0
    assert data["call"]["active"] is True
    assert len(data["call"]["participants"]) == 1
    assert data["call"]["participants"][0]["is_you"] is True

    # The secret certificate must never appear anywhere in the response.
    assert TEST_CERT not in r.text


def test_second_member_joins_same_call(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id)

    r1 = _join(client, parent, family_id)
    r2 = _join(client, gran, family_id)

    assert r1.status_code == 201
    assert r2.status_code == 200  # joined, not created
    assert r2.json()["channel_name"] == r1.json()["channel_name"]
    assert r2.json()["call"]["call_id"] == r1.json()["call"]["call_id"]
    assert r2.json()["agora_uid"] != r1.json()["agora_uid"]  # distinct uids
    assert len(r2.json()["call"]["participants"]) == 2

    from app.models import FamilyCall

    with TestingSession() as db:
        assert db.query(FamilyCall).count() == 1


def test_concurrent_double_join_resolves_to_one_call(client, monkeypatch):
    """A create race (both callers see no live call) collapses to one call:
    the unique active-call constraint makes the loser roll back and re-read."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id)

    r1 = _join(client, parent, family_id)
    assert r1.status_code == 201

    from app.routers import calls

    real_active = calls._active_call
    calls_count = {"n": 0}

    def flaky_active(db, fid):
        # Make gran's join miss the live call on its first look, forcing the
        # create path into an IntegrityError against the existing active call.
        calls_count["n"] += 1
        if calls_count["n"] == 1:
            return None
        return real_active(db, fid)

    monkeypatch.setattr(calls, "_active_call", flaky_active)

    r2 = _join(client, gran, family_id)
    assert r2.status_code == 200
    assert r2.json()["channel_name"] == r1.json()["channel_name"]

    from app.models import FamilyCall

    with TestingSession() as db:
        assert (
            db.query(FamilyCall).filter(FamilyCall.status == CallStatus.active).count() == 1
        )


def test_get_state_never_returns_token_or_certificate(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    _join(client, parent, family_id)

    r = client.get(f"/families/{family_id}/call", headers=parent)
    assert r.status_code == 200
    body = r.json()
    assert "token" not in body
    assert body["active"] is True
    assert body["channel_name"].startswith("fr-")
    assert TEST_CERT not in r.text


def test_supporter_is_blocked_from_every_call_endpoint(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    supporter = make_supporter(client, parent, family_id)
    base = f"/families/{family_id}/call"

    assert client.post(f"{base}/join", headers=supporter).status_code == 403
    assert client.get(base, headers=supporter).status_code == 403
    assert client.post(f"{base}/heartbeat", headers=supporter).status_code == 403
    assert client.post(f"{base}/leave", headers=supporter).status_code == 403
    assert client.put(
        f"{base}/children", json={"child_ids": []}, headers=supporter
    ).status_code == 403
    assert client.get(f"{base}/planned", headers=supporter).status_code == 403
    assert client.put(
        f"{base}/planned", json={"scheduled_for": "2026-08-01T18:00:00Z"}, headers=supporter
    ).status_code == 403
    assert client.delete(f"{base}/planned", headers=supporter).status_code == 403
    assert client.post(f"{base}/token", headers=supporter).status_code == 403


def test_children_presence_rejects_cross_family_child(client):
    parent = signup(client, "parent@example.com")
    family_a = create_family(client, parent, "A")
    child_a = add_child(client, parent, family_a, "Ana")
    family_b = create_family(client, parent, "B")
    child_b = add_child(client, parent, family_b, "Ben")

    _join(client, parent, family_a)

    # A child from another family is rejected (IDOR guard) — 404, never leaks.
    r = client.put(
        f"/families/{family_a}/call/children",
        json={"child_ids": [child_b]},
        headers=parent,
    )
    assert r.status_code == 404

    # The family's own child is accepted and appears in the roster.
    r = client.put(
        f"/families/{family_a}/call/children",
        json={"child_ids": [child_a]},
        headers=parent,
    )
    assert r.status_code == 200
    present = r.json()["children_present"]
    assert [c["child_id"] for c in present] == [child_a]
    assert present[0]["first_name"] == "Ana"
    assert present[0]["marked_by"]


def test_presence_expiry_reaps_participant_and_ends_call(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    _join(client, parent, family_id)
    client.put(
        f"/families/{family_id}/call/children",
        json={"child_ids": [child_id]},
        headers=parent,
    )

    # Backdate the heartbeat beyond the presence TTL.
    from app.models import CallChildPresence, CallParticipant, FamilyCall, utcnow

    with TestingSession() as db:
        p = db.query(CallParticipant).first()
        p.last_seen_at = utcnow() - timedelta(
            seconds=settings.agora_presence_ttl_seconds + 60
        )
        db.commit()

    # A read reaps the stale participant and auto-ends the empty call.
    r = client.get(f"/families/{family_id}/call", headers=parent)
    assert r.status_code == 200
    assert r.json()["active"] is False
    assert r.json()["participants"] == []

    with TestingSession() as db:
        call = db.query(FamilyCall).first()
        assert call.status == CallStatus.ended
        assert call.active_family_id is None
        assert call.ended_at is not None
        # child-presence marked by the departed member was dropped
        assert db.query(CallChildPresence).count() == 0


def test_leave_ends_call_only_when_last_person_out(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id)

    _join(client, parent, family_id)
    _join(client, gran, family_id)

    # Parent leaves; gran is still present, so the call stays live.
    r = client.post(f"/families/{family_id}/call/leave", headers=parent)
    assert r.status_code == 200
    assert r.json()["active"] is True
    assert len(r.json()["participants"]) == 1

    # Gran leaves last; the call ends.
    r = client.post(f"/families/{family_id}/call/leave", headers=gran)
    assert r.status_code == 200
    assert r.json()["active"] is False

    from app.models import FamilyCall

    with TestingSession() as db:
        assert db.query(FamilyCall).first().status == CallStatus.ended


def test_planned_call_set_get_and_clear(client):
    parent = signup(client, "parent@example.com", "Grandpa Joe")
    family_id = create_family(client, parent)
    base = f"/families/{family_id}/call/planned"

    assert client.get(base, headers=parent).json() is None

    r = client.put(
        base,
        json={"scheduled_for": "2026-08-01T18:00:00Z", "note": "Sunday dinner"},
        headers=parent,
    )
    assert r.status_code == 200, r.text
    assert r.json()["note"] == "Sunday dinner"
    assert r.json()["set_by_name"] == "Grandpa Joe"

    got = client.get(base, headers=parent).json()
    assert got["note"] == "Sunday dinner"
    assert got["set_by_name"] == "Grandpa Joe"

    # It also rides along in the live call state.
    _join(client, parent, family_id)
    state = client.get(f"/families/{family_id}/call", headers=parent).json()
    assert state["planned_call"]["note"] == "Sunday dinner"

    assert client.delete(base, headers=parent).status_code == 204
    assert client.get(base, headers=parent).json() is None


def test_token_refresh_requires_present_participant(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    base = f"/families/{family_id}/call"

    # Not in a call yet -> 409.
    assert client.post(f"{base}/token", headers=parent).status_code == 409

    join = _join(client, parent, family_id).json()
    r = client.post(f"{base}/token", headers=parent)
    assert r.status_code == 200
    assert r.json()["channel_name"] == join["channel_name"]
    assert r.json()["agora_uid"] == join["agora_uid"]  # stable per call
    assert r.json()["token"].startswith("007")
    assert TEST_CERT not in r.text

    # Once the caller goes stale, the refresh is refused again.
    from app.models import CallParticipant, utcnow

    with TestingSession() as db:
        p = db.query(CallParticipant).first()
        p.last_seen_at = utcnow() - timedelta(
            seconds=settings.agora_presence_ttl_seconds + 60
        )
        db.commit()

    assert client.post(f"{base}/token", headers=parent).status_code == 409


def test_set_children_requires_being_in_the_call(client):
    """Only someone actually in the call may attest who's present — this also
    prevents a non-participant from leaving orphaned child-presence rows."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id)

    _join(client, parent, family_id)  # parent is in the call; gran is not

    # A member who hasn't joined the call cannot mark children present.
    r = client.put(
        f"/families/{family_id}/call/children",
        json={"child_ids": [child_id]},
        headers=gran,
    )
    assert r.status_code == 409

    # A member who is in the call can.
    r = client.put(
        f"/families/{family_id}/call/children",
        json={"child_ids": [child_id]},
        headers=parent,
    )
    assert r.status_code == 200
    assert [c["child_id"] for c in r.json()["children_present"]] == [child_id]


def test_token_minting_is_dark_without_a_certificate(client, monkeypatch):
    monkeypatch.setattr(settings, "agora_app_certificate", "")
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    r = _join(client, parent, family_id)
    assert r.status_code == 503
    assert "set up" in r.json()["detail"].lower()
