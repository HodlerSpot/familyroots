from .conftest import add_child, create_family, signup
from .test_vault import upload_photo


def test_set_child_avatar(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    media_id = upload_photo(client, parent, child_id)

    r = client.post(
        f"/children/{child_id}/avatar", json={"media_id": media_id}, headers=parent
    )
    assert r.status_code == 200, r.text
    assert r.json()["avatar_media_id"] == media_id
    assert r.json()["avatar_content_type"] == "image/png"

    # It surfaces wherever the child is serialized
    detail = client.get(f"/families/{family_id}", headers=parent).json()
    assert detail["children"][0]["avatar_media_id"] == media_id
    assert detail["children"][0]["avatar_content_type"] == "image/png"
    listed = client.get(f"/families/{family_id}/children", headers=parent).json()
    assert listed[0]["avatar_content_type"] == "image/png"


def test_avatar_rejects_foreign_media(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    emma = add_child(client, parent, family_id, "Emma")
    liam = add_child(client, parent, family_id, "Liam")
    media_id = upload_photo(client, parent, emma)  # scoped to Emma

    r = client.post(
        f"/children/{liam}/avatar", json={"media_id": media_id}, headers=parent
    )
    assert r.status_code == 422


def test_grandparent_cannot_set_avatar(client):
    from .test_goals import make_grandparent

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    media_id = upload_photo(client, parent, child_id)
    gran = make_grandparent(client, parent, family_id, name="Gran")

    r = client.post(
        f"/children/{child_id}/avatar", json={"media_id": media_id}, headers=gran
    )
    assert r.status_code == 403


def test_parent_adds_child_with_consent(client):
    headers = signup(client, "parent@example.com")
    family_id = create_family(client, headers)
    add_child(client, headers, family_id, "Emma")

    r = client.get(f"/families/{family_id}/children", headers=headers)
    assert r.status_code == 200
    assert r.json()[0]["first_name"] == "Emma"


def test_child_creation_requires_explicit_consent(client):
    headers = signup(client, "parent@example.com")
    family_id = create_family(client, headers)

    r = client.post(
        f"/families/{family_id}/children",
        json={"first_name": "Emma", "birthdate": "2018-05-01", "parental_consent": False},
        headers=headers,
    )
    assert r.status_code == 422


def test_consent_is_recorded(client):
    from app.models import ConsentRecord, ConsentType
    from .conftest import TestingSession

    headers = signup(client, "parent@example.com")
    family_id = create_family(client, headers)
    child_id = add_child(client, headers, family_id)

    with TestingSession() as db:
        records = db.query(ConsentRecord).all()
        assert len(records) == 1
        assert str(records[0].child_id) == child_id
        assert records[0].consent_type == ConsentType.profile_creation
        assert records[0].revoked_at is None


def test_grandparent_cannot_add_child(client):
    """Child-critical writes require parent/guardian role."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)

    # Invite and join a grandparent
    r = client.post(
        f"/families/{family_id}/invites",
        json={"email": "gran@example.com", "role": "grandparent"},
        headers=parent,
    )
    assert r.status_code == 201
    from .conftest import TestingSession
    from app.models import FamilyInvite

    with TestingSession() as db:
        token = db.query(FamilyInvite).first().token

    gran = signup(client, "gran@example.com", "Gran")
    r = client.post("/invites/accept", json={"token": token}, headers=gran)
    assert r.status_code == 200

    r = client.post(
        f"/families/{family_id}/children",
        json={"first_name": "Emma", "birthdate": "2018-05-01", "parental_consent": True},
        headers=gran,
    )
    assert r.status_code == 403


def test_family_graph_edges_created(client):
    from app.models import ChildRelationship
    from .conftest import TestingSession

    headers = signup(client, "parent@example.com")
    family_id = create_family(client, headers)
    child_id = add_child(client, headers, family_id)

    with TestingSession() as db:
        edges = db.query(ChildRelationship).all()
        assert len(edges) == 1
        assert str(edges[0].child_id) == child_id
        assert edges[0].relationship_type.value == "parent"
