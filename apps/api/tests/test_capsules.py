from datetime import date, timedelta

from .conftest import add_child, create_family, signup
from .test_goals import make_grandparent
from .test_vault import upload_photo


def seal_capsule(client, headers, child_id, **overrides):
    body = {
        "type": "letter",
        "body": "My dearest Emma, when you read this...",
        "release_condition": "age",
        "release_age": 18,
        **overrides,
    }
    return client.post(f"/children/{child_id}/capsules", json=body, headers=headers)


def test_sealed_capsule_hidden_from_everyone_but_creator(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")

    r = seal_capsule(client, gran, child_id)
    assert r.status_code == 201, r.text
    assert r.json()["body"] is not None  # creator sees their own words

    # The parent knows it exists but can never peek inside
    r = client.get(f"/children/{child_id}/capsules", headers=parent)
    assert len(r.json()) == 1
    sealed = r.json()[0]
    assert sealed["status"] == "sealed"
    assert sealed["created_by_name"] == "Gran"
    assert sealed["is_mine"] is False
    assert sealed["body"] is None
    assert sealed["media_id"] is None

    # The creator still sees the contents
    r = client.get(f"/children/{child_id}/capsules", headers=gran)
    assert r.json()[0]["body"].startswith("My dearest Emma")


def test_media_capsule_media_not_leaked_while_sealed(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id)
    media_id = upload_photo(client, gran, child_id)

    r = seal_capsule(client, gran, child_id, type="video", body=None, media_id=media_id)
    assert r.status_code == 201

    r = client.get(f"/children/{child_id}/capsules", headers=parent)
    assert r.json()[0]["media_id"] is None


def test_date_capsule_auto_releases_when_due(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id)

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    seal_capsule(
        client, gran, child_id, release_condition="date", release_age=None, release_date=yesterday
    )

    # Listing runs the lazy scheduler → capsule opens for everyone
    r = client.get(f"/children/{child_id}/capsules", headers=parent)
    capsule = r.json()[0]
    assert capsule["status"] == "released"
    assert capsule["body"] is not None
    assert capsule["released_at"] is not None

    # Release lands on the family feed
    r = client.get(f"/families/{family_id}/feed", headers=parent)
    assert r.json()[0]["type"] == "capsule_released"


def test_age_capsule_releases_at_birthday(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    # Emma born 2018-05-01 (see conftest) → she is 8 in July 2026
    child_id = add_child(client, parent, family_id, "Emma")

    seal_capsule(client, parent, child_id, release_age=8)  # already reached
    seal_capsule(client, parent, child_id, release_age=18)  # far future

    r = client.get(f"/children/{child_id}/capsules", headers=parent)
    statuses = sorted(c["release_age"] for c in r.json() if c["status"] == "released")
    assert statuses == [8]


def test_milestone_capsule_manual_release_permissions(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id)
    relative_headers = None

    # A relative joins too
    from .conftest import TestingSession
    from app.models import FamilyInvite

    client.post(
        f"/families/{family_id}/invites",
        json={"email": "uncle@example.com", "role": "relative"},
        headers=parent,
    )
    with TestingSession() as db:
        token = (
            db.query(FamilyInvite)
            .filter(FamilyInvite.email == "uncle@example.com")
            .first()
            .token
        )
    relative_headers = signup(client, "uncle@example.com", "Uncle Lee")
    client.post("/invites/accept", json={"token": token}, headers=relative_headers)

    r = seal_capsule(
        client,
        gran,
        child_id,
        release_condition="milestone",
        release_age=None,
        release_milestone="Graduation day",
    )
    capsule_id = r.json()["id"]

    # Direct release is creator-only now: neither a relative nor a parent who
    # didn't seal it can open it directly.
    assert client.post(f"/capsules/{capsule_id}/release", headers=relative_headers).status_code == 403
    assert client.post(f"/capsules/{capsule_id}/release", headers=parent).status_code == 403

    # The creator (Gran) can
    r = client.post(f"/capsules/{capsule_id}/release", headers=gran)
    assert r.status_code == 200
    assert r.json()["status"] == "released"
    assert r.json()["body"] is not None

    # Only once
    assert client.post(f"/capsules/{capsule_id}/release", headers=gran).status_code == 409


def test_creator_can_release_any_condition_directly(client):
    """#7: the creator may open their own capsule directly, whatever the
    condition — including an age capsule that hasn't come due."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    capsule_id = seal_capsule(client, parent, child_id, release_age=18).json()["id"]

    r = client.post(f"/capsules/{capsule_id}/release", headers=parent)
    assert r.status_code == 200
    assert r.json()["status"] == "released"

    # A non-creator guardian may not force an age capsule open directly.
    gran = make_grandparent(client, parent, family_id, name="Gran")
    other = seal_capsule(client, parent, child_id, release_age=18).json()["id"]
    assert client.post(f"/capsules/{other}/release", headers=gran).status_code == 403


def test_capsule_requires_condition_value_and_content(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)

    r = seal_capsule(client, parent, child_id, release_age=None)  # age condition, no age
    assert r.status_code == 422
    r = seal_capsule(client, parent, child_id, body=None)  # no letter, no media
    assert r.status_code == 422


def test_release_notifies_parents(client, tmp_path, monkeypatch):
    from app.services import email as email_module

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")
    for f in outbox.glob("*.txt"):
        f.unlink()

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    seal_capsule(
        client, gran, child_id, release_condition="date", release_age=None, release_date=yesterday
    )
    client.get(f"/children/{child_id}/capsules", headers=gran)  # triggers release

    emails = [f.read_text(encoding="utf-8") for f in sorted(outbox.glob("*.txt"))]
    assert len(emails) == 1
    assert "To: parent@example.com" in emails[0]
    assert "time capsule" in emails[0]


def test_outsider_cannot_touch_capsules(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    capsule_id = seal_capsule(client, parent, child_id).json()["id"]

    outsider = signup(client, "outsider@example.com")
    assert client.get(f"/children/{child_id}/capsules", headers=outsider).status_code == 404
    assert seal_capsule(client, outsider, child_id).status_code == 404
    assert client.post(f"/capsules/{capsule_id}/release", headers=outsider).status_code == 404
