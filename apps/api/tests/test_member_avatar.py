"""Member profile headshots: user-scoped media, avatar set, and download
access (owner + co-family members only)."""

from .conftest import add_child, create_family, signup
from .test_goals import make_grandparent
from .test_vault import PNG_BYTES


def upload_my_photo(client, headers) -> str:
    r = client.post("/me/media", json={"content_type": "image/png"}, headers=headers)
    assert r.status_code == 201, r.text
    media_id = r.json()["media_id"]
    assert client.put(r.json()["upload_url"], content=PNG_BYTES, headers=headers).status_code == 204
    assert client.post(f"/media/{media_id}/complete", headers=headers).status_code == 204
    return media_id


def _tok(headers: dict) -> str:
    return headers["Authorization"].removeprefix("Bearer ")


def test_avatar_upload_set_and_co_member_download(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id)  # co-member

    media_id = upload_my_photo(client, parent)
    r = client.post("/me/avatar", json={"media_id": media_id}, headers=parent)
    assert r.status_code == 200, r.text
    assert r.json()["avatar_media_id"] == media_id

    # /auth/me reflects the headshot.
    me = client.get("/auth/me", headers=parent).json()
    assert me["avatar_media_id"] == media_id

    # It also surfaces on the member in the family detail (MemberOut.user).
    detail = client.get(f"/families/{family_id}", headers=parent).json()
    pat = next(m for m in detail["members"] if m["user"]["display_name"] == "Pat")
    assert pat["user"]["avatar_media_id"] == media_id

    # Owner and a co-family member can fetch the image; a stranger cannot.
    assert client.get(f"/media/{media_id}?token={_tok(parent)}").status_code in (200, 307)
    assert client.get(f"/media/{media_id}?token={_tok(gran)}").status_code in (200, 307)

    stranger = signup(client, "stranger@example.com")
    assert client.get(f"/media/{media_id}?token={_tok(stranger)}").status_code == 404


def test_cannot_set_someone_elses_media_as_avatar(client):
    parent = signup(client, "parent@example.com")
    create_family(client, parent)
    other = signup(client, "other@example.com")

    others_media = upload_my_photo(client, other)
    r = client.post("/me/avatar", json={"media_id": others_media}, headers=parent)
    assert r.status_code == 422


def test_cannot_set_incomplete_media_as_avatar(client):
    parent = signup(client, "parent@example.com")
    # Create the upload ticket but never complete it.
    media_id = client.post(
        "/me/media", json={"content_type": "image/png"}, headers=parent
    ).json()["media_id"]
    r = client.post("/me/avatar", json={"media_id": media_id}, headers=parent)
    assert r.status_code == 422
