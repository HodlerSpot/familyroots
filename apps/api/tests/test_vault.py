from .conftest import add_child, create_family, media_token, signup

PNG_BYTES = b"\x89PNG\r\n\x1a\nfakeimagedata"


def upload_photo(client, headers, child_id) -> str:
    r = client.post(
        f"/children/{child_id}/media",
        json={"content_type": "image/png"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    media_id = r.json()["media_id"]
    upload_url = r.json()["upload_url"]
    r = client.put(upload_url, content=PNG_BYTES, headers=headers)
    assert r.status_code == 204, r.text
    r = client.post(f"/media/{media_id}/complete", headers=headers)
    assert r.status_code == 204, r.text
    return media_id


def test_photo_upload_and_vault_item(client):
    headers = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, headers)
    child_id = add_child(client, headers, family_id)
    media_id = upload_photo(client, headers, child_id)

    r = client.post(
        f"/children/{child_id}/vault",
        json={"type": "photo", "title": "First day of school", "media_id": media_id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["media_content_type"] == "image/png"
    assert r.json()["created_by_name"] == "Pat"

    r = client.get(f"/children/{child_id}/vault", headers=headers)
    assert len(r.json()) == 1


def test_declared_image_that_is_actually_video_is_rejected_on_complete(client):
    """Paywall bypass guard: a free family declares image/png on the ticket
    (which is not gated) but PUTs an MP4. The completion path sniffs the bytes
    and rejects — the declared type can't smuggle video past the Premium gate."""
    headers = signup(client, "parent@example.com")
    family_id = create_family(client, headers)
    child_id = add_child(client, headers, family_id)

    r = client.post(
        f"/children/{child_id}/media",
        json={"content_type": "image/png"},  # not gated — video ticket would be
        headers=headers,
    )
    assert r.status_code == 201, r.text
    media_id = r.json()["media_id"]
    upload_url = r.json()["upload_url"]

    # Minimal ISO-BMFF/MP4 header: box size, 'ftyp', brand 'isom'.
    mp4_bytes = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00mp41" + b"\x00" * 32
    r = client.put(upload_url, content=mp4_bytes, headers=headers)
    assert r.status_code == 204, r.text

    r = client.post(f"/media/{media_id}/complete", headers=headers)
    assert r.status_code == 415, r.text
    assert "video" in r.json()["detail"].lower()


def test_real_image_completes_normally(client):
    """The sniff must not false-positive on a genuine image declared as image."""
    headers = signup(client, "parent@example.com")
    family_id = create_family(client, headers)
    child_id = add_child(client, headers, family_id)
    # upload_photo asserts a clean 204 through PUT + complete.
    assert upload_photo(client, headers, child_id)


def test_media_download_requires_family_membership(client):
    headers = signup(client, "parent@example.com")
    family_id = create_family(client, headers)
    child_id = add_child(client, headers, family_id)
    media_id = upload_photo(client, headers, child_id)

    token = media_token(client, headers)
    r = client.get(f"/media/{media_id}?token={token}")
    assert r.status_code == 200
    assert r.content == PNG_BYTES

    # No token → 401; outsider's media token → 404 (child existence never leaks)
    assert client.get(f"/media/{media_id}").status_code == 401
    outsider = signup(client, "outsider@example.com")
    outsider_token = media_token(client, outsider)
    assert client.get(f"/media/{media_id}?token={outsider_token}").status_code == 404


def test_outsider_cannot_touch_vault(client):
    headers = signup(client, "parent@example.com")
    family_id = create_family(client, headers)
    child_id = add_child(client, headers, family_id)

    outsider = signup(client, "outsider@example.com")
    r = client.get(f"/children/{child_id}/vault", headers=outsider)
    assert r.status_code == 404
    r = client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": "hello"},
        headers=outsider,
    )
    assert r.status_code == 404
    r = client.post(
        f"/children/{child_id}/media",
        json={"content_type": "image/png"},
        headers=outsider,
    )
    assert r.status_code == 404


def test_grandparent_can_add_memory(client):
    """Memories are open to the whole family — that's the product."""
    from .conftest import TestingSession
    from app.models import FamilyInvite

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    client.post(
        f"/families/{family_id}/invites",
        json={"email": "gran@example.com", "role": "grandparent"},
        headers=parent,
    )
    with TestingSession() as db:
        token = db.query(FamilyInvite).first().token
    gran = signup(client, "gran@example.com", "Gran")
    client.post("/invites/accept", json={"token": token}, headers=gran)

    r = client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": "A note from Gran", "body": "So proud of you!"},
        headers=gran,
    )
    assert r.status_code == 201


def test_vault_item_with_foreign_media_rejected(client):
    """Media uploaded for one child can't be attached to another child's vault."""
    headers = signup(client, "parent@example.com")
    family_id = create_family(client, headers)
    child_a = add_child(client, headers, family_id, "Emma")
    child_b = add_child(client, headers, family_id, "Liam")
    media_id = upload_photo(client, headers, child_a)

    r = client.post(
        f"/children/{child_b}/vault",
        json={"type": "photo", "title": "Wrong vault", "media_id": media_id},
        headers=headers,
    )
    assert r.status_code == 422


def test_upload_size_limit(client):
    headers = signup(client, "parent@example.com")
    family_id = create_family(client, headers)
    child_id = add_child(client, headers, family_id)
    r = client.post(
        f"/children/{child_id}/media", json={"content_type": "image/png"}, headers=headers
    )
    upload_url = r.json()["upload_url"]
    r = client.put(upload_url, content=b"x" * (25 * 1024 * 1024 + 1), headers=headers)
    assert r.status_code == 413


def test_milestone_creates_vault_item_and_notifies_family(client, tmp_path, monkeypatch):
    from app.services import email as email_module

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    from .conftest import TestingSession
    from app.models import FamilyInvite

    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    client.post(
        f"/families/{family_id}/invites",
        json={"email": "gran@example.com", "role": "grandparent"},
        headers=parent,
    )
    with TestingSession() as db:
        token = db.query(FamilyInvite).first().token
    gran = signup(client, "gran@example.com", "Gran")
    client.post("/invites/accept", json={"token": token}, headers=gran)
    for f in outbox.glob("*.txt"):
        f.unlink()  # drop the invite email; we're testing milestone notifications

    r = client.post(
        f"/children/{child_id}/milestones",
        json={"title": "First piano recital", "description": "She played beautifully."},
        headers=parent,
    )
    assert r.status_code == 201
    assert r.json()["type"] == "achievement"

    # Gran got an email; Pat (the actor) did not
    emails = [f.read_text(encoding="utf-8") for f in sorted(outbox.glob("*.txt"))]
    assert len(emails) == 1
    assert "To: gran@example.com" in emails[0]
    assert "Emma" in emails[0]
    assert "First piano recital" in emails[0]
