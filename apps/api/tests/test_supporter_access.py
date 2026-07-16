"""Section E: the supporter role sees a deliberately narrow slice of a family
and is locked out of funds, capsules, goals, and the legacy archive."""

from .conftest import TestingSession, add_child, create_family, media_token, setup_fund, signup
from .test_capsules import seal_capsule
from .test_vault import PNG_BYTES, upload_photo


def make_supporter(client, parent, family_id, email="coach@example.com", name="Coach"):
    from app.models import FamilyInvite

    client.post(
        f"/families/{family_id}/invites",
        json={"email": email, "role": "supporter"},
        headers=parent,
    )
    with TestingSession() as db:
        token = db.query(FamilyInvite).filter(FamilyInvite.email == email).first().token
    supporter = signup(client, email, name)
    r = client.post("/invites/accept", json={"token": token}, headers=supporter)
    assert r.status_code == 200, r.text
    return supporter


def _share(client, parent, item_id):
    r = client.patch(
        f"/vault-items/{item_id}/visibility", json={"visible": True}, headers=parent
    )
    assert r.status_code == 200, r.text
    return r


def test_supporter_blocked_from_family_only_surfaces(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    supporter = make_supporter(client, parent, family_id)

    # Vault writes
    assert client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": "hi"},
        headers=supporter,
    ).status_code == 403
    assert client.post(
        f"/children/{child_id}/milestones",
        json={"title": "First steps"},
        headers=supporter,
    ).status_code == 403

    # Fund
    assert client.get(f"/children/{child_id}/fund", headers=supporter).status_code == 403

    # Capsules
    assert client.get(f"/children/{child_id}/capsules", headers=supporter).status_code == 403
    assert seal_capsule(client, supporter, child_id).status_code == 403

    # Goals & badges
    assert client.get(f"/children/{child_id}/goals", headers=supporter).status_code == 403
    assert client.get(f"/children/{child_id}/badges", headers=supporter).status_code == 403
    assert client.post(
        f"/children/{child_id}/goals",
        json={"title": "Read", "reward_type": "badge"},
        headers=supporter,
    ).status_code == 403

    # Legacy
    assert client.get(f"/families/{family_id}/legacy", headers=supporter).status_code == 403
    assert client.post(
        f"/families/{family_id}/legacy",
        json={"type": "story", "title": "x", "body": "y"},
        headers=supporter,
    ).status_code == 403
    assert client.post(
        f"/families/{family_id}/media",
        json={"content_type": "image/png"},
        headers=supporter,
    ).status_code == 403

    # Child-critical guardian ops
    assert client.post(
        f"/families/{family_id}/children",
        json={"first_name": "Liam", "birthdate": "2020-01-01", "parental_consent": True},
        headers=supporter,
    ).status_code == 403
    assert client.post(
        f"/families/{family_id}/invites",
        json={"email": "someone@example.com", "role": "relative"},
        headers=supporter,
    ).status_code == 403


def test_supporter_can_contribute(client):
    """Supporters are welcome to give — that's the point of inviting them."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)
    supporter = make_supporter(client, parent, family_id)

    r = client.post(
        f"/children/{child_id}/contributions",
        json={"amount_cents": 2500, "message": "Go get 'em!"},
        headers=supporter,
    )
    assert r.status_code == 201, r.text
    contribution_id = r.json()["id"]
    assert client.post(
        f"/contributions/{contribution_id}/confirm", headers=supporter
    ).status_code == 200


def test_supporter_vault_is_filtered_to_shared_items(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)

    shared = client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": "Shared note"},
        headers=parent,
    ).json()
    client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": "Private note"},
        headers=parent,
    )
    _share(client, parent, shared["id"])

    supporter = make_supporter(client, parent, family_id)
    items = client.get(f"/children/{child_id}/vault", headers=supporter).json()
    assert [i["title"] for i in items] == ["Shared note"]
    assert items[0]["visible_to_supporters"] is True

    # A guardian still sees everything
    assert len(client.get(f"/children/{child_id}/vault", headers=parent).json()) == 2


def test_visibility_toggle_is_parent_only(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    gran = _gran(client, parent, family_id)

    item = client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": "note"},
        headers=parent,
    ).json()

    # A grandparent (guardian, but not a parent) cannot change sharing
    assert client.patch(
        f"/vault-items/{item['id']}/visibility", json={"visible": True}, headers=gran
    ).status_code == 403
    assert client.patch(
        f"/vault-items/{item['id']}/visibility", json={"visible": True}, headers=parent
    ).status_code == 200


def test_supporter_feed_is_filtered(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)

    shared = client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": "Shared memory"},
        headers=parent,
    ).json()
    client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": "Private memory"},
        headers=parent,
    )
    _share(client, parent, shared["id"])
    # A milestone (not shared) and a settled contribution must stay hidden
    client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    )
    setup_fund(client, parent, child_id)
    c = client.post(
        f"/children/{child_id}/contributions", json={"amount_cents": 2500}, headers=parent
    ).json()
    client.post(f"/contributions/{c['id']}/confirm", headers=parent)

    supporter = make_supporter(client, parent, family_id)
    events = client.get(f"/families/{family_id}/feed", headers=supporter).json()
    types = {e["type"] for e in events}
    assert types <= {"member_joined", "memory_added"}
    memory_events = [e for e in events if e["type"] == "memory_added"]
    assert len(memory_events) == 1
    assert memory_events[0]["payload"]["vault_item_id"] == shared["id"]

    # A guardian sees the full picture
    guardian_types = {
        e["type"] for e in client.get(f"/families/{family_id}/feed", headers=parent).json()
    }
    assert "milestone" in guardian_types
    assert "contribution" in guardian_types


def test_supporter_never_sees_child_birthdate(client):
    """A child's date of birth is sensitive PII a supporter has no need for."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    add_child(client, parent, family_id)
    supporter = make_supporter(client, parent, family_id)

    detail = client.get(f"/families/{family_id}", headers=supporter).json()
    assert detail["children"][0]["birthdate"] is None
    assert detail["children"][0]["first_name"]  # identity still present (to contribute)

    kids = client.get(f"/families/{family_id}/children", headers=supporter).json()
    assert kids[0]["birthdate"] is None

    # A guardian still gets the birthdate
    gdetail = client.get(f"/families/{family_id}", headers=parent).json()
    assert gdetail["children"][0]["birthdate"] is not None


def test_supporter_is_never_emailed_family_content(client, tmp_path):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    _gran(client, parent, family_id)  # guardian, milestone email on by default
    make_supporter(client, parent, family_id)  # coach@example.com

    before = set(tmp_path.glob("*.txt"))
    assert client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    ).status_code == 201
    new_mail = "\n".join(
        f.read_text(encoding="utf-8") for f in set(tmp_path.glob("*.txt")) - before
    )
    assert "gran@example.com" in new_mail  # guardian notified
    assert "coach@example.com" not in new_mail  # supporter never gets family content


def test_supporter_media_download_is_gated(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)

    media_id = upload_photo(client, parent, child_id)
    item = client.post(
        f"/children/{child_id}/vault",
        json={"type": "photo", "title": "pic", "media_id": media_id},
        headers=parent,
    ).json()

    avatar_id = upload_photo(client, parent, child_id)
    client.post(f"/children/{child_id}/avatar", json={"media_id": avatar_id}, headers=parent)

    # family/legacy media the supporter must never reach
    r = client.post(
        f"/families/{family_id}/media", json={"content_type": "image/png"}, headers=parent
    ).json()
    fam_media = r["media_id"]
    client.put(r["upload_url"], content=PNG_BYTES, headers=parent)
    client.post(f"/media/{fam_media}/complete", headers=parent)

    supporter = make_supporter(client, parent, family_id)
    tok = media_token(client, supporter)

    # Unshared memory media: blocked. Avatar: allowed. Family media: blocked.
    assert client.get(f"/media/{media_id}?token={tok}").status_code == 404
    assert client.get(f"/media/{avatar_id}?token={tok}").status_code in (200, 307)
    assert client.get(f"/media/{fam_media}?token={tok}").status_code == 404

    # Once the memory is shared, its media becomes reachable
    _share(client, parent, item["id"])
    assert client.get(f"/media/{media_id}?token={tok}").status_code in (200, 307)


def _gran(client, parent, family_id, email="gran@example.com", name="Gran"):
    from .test_goals import make_grandparent

    return make_grandparent(client, parent, family_id, email=email, name=name)
