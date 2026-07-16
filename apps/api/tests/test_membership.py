"""Family membership departures: leaving, removal, the last-parent guard,
the Premium owner-departure wiring, and re-invitation after a departure.

Nothing a departed member authored is ever deleted — memories and
contributions are family history — so these tests only assert on access
and lifecycle, never on content disappearing.
"""

import uuid

from app.models import FamilySubscription, User
from .conftest import TestingSession, create_family, make_premium, signup
from .test_goals import make_grandparent
from .test_premium import make_member, outbox_texts
from .test_supporter_access import make_supporter


def _leave(client, headers, family_id):
    return client.post(f"/families/{family_id}/members/me/leave", headers=headers)


def _remove(client, headers, family_id, user_id):
    return client.delete(f"/families/{family_id}/members/{user_id}", headers=headers)


def _user_id(email: str) -> str:
    with TestingSession() as db:
        return str(db.query(User).filter(User.email == email).one().id)


def _feed(client, headers, family_id):
    r = client.get(f"/families/{family_id}/feed", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _subscription(family_id: str) -> FamilySubscription:
    with TestingSession() as db:
        return (
            db.query(FamilySubscription)
            .filter(FamilySubscription.family_id == uuid.UUID(family_id))
            .one()
        )


# --- leaving ---

def test_member_can_leave_and_loses_access(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id, name="June")

    r = _leave(client, gran, family_id)
    assert r.status_code == 204, r.text

    # Access is gone immediately — and as a non-member they get a 404, not
    # a 403, so the family's existence no longer leaks to them.
    assert client.get(f"/families/{family_id}", headers=gran).status_code == 404
    r = client.get("/families", headers=gran)
    assert r.json() == []

    # The family sees a warm goodbye on the feed.
    events = _feed(client, parent, family_id)
    left = [e for e in events if e["type"] == "member_left"]
    assert len(left) == 1
    assert left[0]["payload"]["member_name"] == "June"
    assert left[0]["payload"]["role"] == "grandparent"


def test_supporter_can_leave(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    supporter = make_supporter(client, parent, family_id)

    assert _leave(client, supporter, family_id).status_code == 204
    assert client.get(f"/families/{family_id}", headers=supporter).status_code == 404


def test_supporter_sees_member_left_on_feed(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    supporter = make_supporter(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id)

    assert _leave(client, gran, family_id).status_code == 204
    types = [e["type"] for e in _feed(client, supporter, family_id)]
    assert "member_left" in types  # roster events are supporter-visible


def test_last_parent_cannot_leave(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    make_grandparent(client, parent, family_id)  # other members don't help

    r = _leave(client, parent, family_id)
    assert r.status_code == 409
    assert "only parent" in r.json()["detail"]
    # Still an active member.
    assert client.get(f"/families/{family_id}", headers=parent).status_code == 200


def test_parent_can_leave_when_another_parent_remains(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    parent2 = make_member(client, parent, family_id, "parent2@example.com", "parent")

    assert _leave(client, parent2, family_id).status_code == 204
    assert client.get(f"/families/{family_id}", headers=parent2).status_code == 404


def test_double_leave_is_a_404(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id)

    assert _leave(client, gran, family_id).status_code == 204
    # No longer an active member, so the second leave can't find the family.
    assert _leave(client, gran, family_id).status_code == 404
    # And only one goodbye reached the feed.
    events = _feed(client, parent, family_id)
    assert len([e for e in events if e["type"] == "member_left"]) == 1


def test_nonmember_cannot_leave(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    outsider = signup(client, "outsider@example.com")
    assert _leave(client, outsider, family_id).status_code == 404


# --- removal ---

def test_parent_removes_relative(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    relative = make_member(client, parent, family_id, "rel@example.com", "relative", "Ray")

    r = _remove(client, parent, family_id, _user_id("rel@example.com"))
    assert r.status_code == 204, r.text
    assert client.get(f"/families/{family_id}", headers=relative).status_code == 404

    events = _feed(client, parent, family_id)
    left = [e for e in events if e["type"] == "member_left"]
    assert len(left) == 1
    assert left[0]["payload"]["member_name"] == "Ray"


def test_parent_can_remove_another_parent(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    parent2 = make_member(client, parent, family_id, "parent2@example.com", "parent")

    assert _remove(client, parent, family_id, _user_id("parent2@example.com")).status_code == 204
    assert client.get(f"/families/{family_id}", headers=parent2).status_code == 404


def test_relative_cannot_remove(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    relative = make_member(client, parent, family_id, "rel@example.com", "relative")
    gran = make_grandparent(client, parent, family_id)

    r = _remove(client, relative, family_id, _user_id("gran@example.com"))
    assert r.status_code == 403
    # The grandparent is untouched.
    assert client.get(f"/families/{family_id}", headers=gran).status_code == 200


def test_supporter_cannot_remove(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    supporter = make_supporter(client, parent, family_id)
    assert _remove(client, supporter, family_id, _user_id("parent@example.com")).status_code == 403


def test_guardian_cannot_remove(client):
    """Removal is parent-only, stricter than the guardian gate."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    guardian = make_member(client, parent, family_id, "guard@example.com", "guardian")
    gran = make_grandparent(client, parent, family_id)
    assert _remove(client, guardian, family_id, _user_id("gran@example.com")).status_code == 403


def test_cannot_remove_yourself(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    make_member(client, parent, family_id, "parent2@example.com", "parent")

    r = _remove(client, parent, family_id, _user_id("parent@example.com"))
    assert r.status_code == 409
    assert "Leave this family" in r.json()["detail"]


def test_remove_unknown_or_already_removed_member_404(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id)
    gran_id = _user_id("gran@example.com")

    # Someone who was never a member.
    assert _remove(client, parent, family_id, str(uuid.uuid4())).status_code == 404

    assert _remove(client, parent, family_id, gran_id).status_code == 204
    # Removing again finds no active membership.
    assert _remove(client, parent, family_id, gran_id).status_code == 404


def test_nonmember_remover_gets_404_not_403(client):
    """Cross-family probing must not reveal that the family exists."""
    parent_a = signup(client, "a@example.com")
    family_a = create_family(client, parent_a, "Family A")
    outsider = signup(client, "b@example.com")
    create_family(client, outsider, "Family B")  # a parent elsewhere, still 404 here

    r = _remove(client, outsider, family_a, _user_id("a@example.com"))
    assert r.status_code == 404


# --- Premium owner departure wiring ---

def test_leaving_owner_cancels_subscription_at_period_end_and_emails(client, tmp_path):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    parent2 = make_member(client, parent, family_id, "parent2@example.com", "parent", "Sam")
    make_premium(client, parent, family_id)

    assert _leave(client, parent, family_id).status_code == 204

    sub = _subscription(family_id)
    assert sub.cancel_at_period_end is True  # runs to period end, never cut short

    # Remaining parent still sees Premium, with auto-renew off.
    r = client.get(f"/families/{family_id}/premium", headers=parent2)
    assert r.status_code == 200
    assert r.json()["plan"] == "premium"
    assert r.json()["subscription"]["cancel_at_period_end"] is True

    departure = [t for t in outbox_texts(tmp_path) if "no longer part of the family" in t]
    assert len(departure) == 1
    assert "To: parent2@example.com" in departure[0]  # never to the departed owner


def test_removed_owner_cancels_subscription_at_period_end(client, tmp_path):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    parent2 = make_member(client, parent, family_id, "parent2@example.com", "parent", "Sam")
    make_premium(client, parent, family_id)

    # Pat owns the subscription; Sam (also a parent) removes Pat. The billing
    # must follow Pat out the door.
    assert _remove(client, parent2, family_id, _user_id("parent@example.com")).status_code == 204

    assert _subscription(family_id).cancel_at_period_end is True
    departure = [t for t in outbox_texts(tmp_path) if "no longer part of the family" in t]
    assert len(departure) == 1
    assert "To: parent2@example.com" in departure[0]


def test_non_owner_departure_leaves_subscription_alone(client, tmp_path):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    parent2 = make_member(client, parent, family_id, "parent2@example.com", "parent", "Sam")
    make_premium(client, parent, family_id)  # Pat owns it

    assert _leave(client, parent2, family_id).status_code == 204  # Sam leaves

    assert _subscription(family_id).cancel_at_period_end is False
    assert not [t for t in outbox_texts(tmp_path) if "no longer part of the family" in t]


def test_non_owner_grandparent_removal_leaves_subscription_alone(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    make_grandparent(client, parent, family_id)
    make_premium(client, parent, family_id)

    assert _remove(client, parent, family_id, _user_id("gran@example.com")).status_code == 204
    assert _subscription(family_id).cancel_at_period_end is False


# --- coming back ---

def test_departed_member_can_be_reinvited(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id, name="June")
    assert _leave(client, gran, family_id).status_code == 204

    # A fresh invite reactivates the same membership row (unique per family+user).
    from app.models import FamilyInvite

    r = client.post(
        f"/families/{family_id}/invites",
        json={"email": "gran@example.com", "role": "grandparent"},
        headers=parent,
    )
    assert r.status_code == 201, r.text
    with TestingSession() as db:
        token = (
            db.query(FamilyInvite)
            .filter(FamilyInvite.email == "gran@example.com", FamilyInvite.accepted_at.is_(None))
            .one()
            .token
        )
    r = client.post("/invites/accept", json={"token": token}, headers=gran)
    assert r.status_code == 200, r.text
    assert client.get(f"/families/{family_id}", headers=gran).status_code == 200
