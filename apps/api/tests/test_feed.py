from .conftest import add_child, create_family, signup


def test_feed_events_emitted_and_ordered(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")

    client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": "Welcome to the world"},
        headers=parent,
    )
    client.post(
        f"/children/{child_id}/milestones",
        json={"title": "First steps"},
        headers=parent,
    )

    r = client.get(f"/families/{family_id}/feed", headers=parent)
    assert r.status_code == 200
    events = r.json()
    types = [e["type"] for e in events]
    assert types == ["milestone", "memory_added"]  # newest first
    assert events[0]["payload"]["title"] == "First steps"
    assert events[0]["payload"]["child_name"] == "Emma"
    assert events[0]["actor_name"] == "Pat"


def test_member_joined_appears_on_feed(client):
    from .conftest import TestingSession
    from app.models import FamilyInvite

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    client.post(
        f"/families/{family_id}/invites",
        json={"email": "gran@example.com", "role": "grandparent"},
        headers=parent,
    )
    with TestingSession() as db:
        token = db.query(FamilyInvite).first().token
    gran = signup(client, "gran@example.com", "Grandma Rose")
    client.post("/invites/accept", json={"token": token}, headers=gran)

    r = client.get(f"/families/{family_id}/feed", headers=gran)
    events = r.json()
    assert events[0]["type"] == "member_joined"
    assert events[0]["payload"]["member_name"] == "Grandma Rose"


def test_feed_is_family_private(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)

    outsider = signup(client, "outsider@example.com")
    assert client.get(f"/families/{family_id}/feed", headers=outsider).status_code == 404
