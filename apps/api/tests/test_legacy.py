from .conftest import add_child, create_family, signup
from .test_goals import make_grandparent

PNG_BYTES = b"\x89PNG\r\n\x1a\nfakeimagedata"


def test_family_adds_and_reads_legacy_items(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    gran = make_grandparent(client, parent, family_id, name="Grandma Rose")

    r = client.post(
        f"/families/{family_id}/legacy",
        json={
            "type": "recipe",
            "title": "Grandma Rose's apple pie",
            "body": "Six apples, a pinch of cinnamon, and no shortcuts.",
        },
        headers=gran,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/families/{family_id}/legacy", headers=parent)
    assert len(r.json()) == 1
    item = r.json()[0]
    assert item["type"] == "recipe"
    assert item["created_by_name"] == "Grandma Rose"
    assert "no shortcuts" in item["body"]


def test_legacy_item_with_family_media(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)

    r = client.post(
        f"/families/{family_id}/media",
        json={"content_type": "image/png"},
        headers=parent,
    )
    assert r.status_code == 201
    media_id = r.json()["media_id"]
    r = client.put(r.json()["upload_url"], content=PNG_BYTES, headers=parent)
    assert r.status_code == 204

    r = client.post(
        f"/families/{family_id}/legacy",
        json={"type": "photo", "title": "The old family house", "media_id": media_id},
        headers=parent,
    )
    assert r.status_code == 201
    assert r.json()["media_content_type"] == "image/png"

    # Family members can download family-scoped media...
    token = parent["Authorization"].removeprefix("Bearer ")
    assert client.get(f"/media/{media_id}?token={token}").status_code == 200

    # ...outsiders cannot
    outsider = signup(client, "outsider@example.com")
    outsider_token = outsider["Authorization"].removeprefix("Bearer ")
    assert client.get(f"/media/{media_id}?token={outsider_token}").status_code == 404


def test_family_media_cannot_attach_to_child_vault(client):
    """Family-scoped media has no child; the vault must reject it."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)

    r = client.post(
        f"/families/{family_id}/media", json={"content_type": "image/png"}, headers=parent
    )
    media_id = r.json()["media_id"]
    client.put(r.json()["upload_url"], content=PNG_BYTES, headers=parent)

    r = client.post(
        f"/children/{child_id}/vault",
        json={"type": "photo", "title": "sneaky", "media_id": media_id},
        headers=parent,
    )
    assert r.status_code == 422


def test_legacy_requires_content(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    r = client.post(
        f"/families/{family_id}/legacy",
        json={"type": "story", "title": "Empty"},
        headers=parent,
    )
    assert r.status_code == 422


def test_outsider_cannot_touch_legacy(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    outsider = signup(client, "outsider@example.com")

    assert client.get(f"/families/{family_id}/legacy", headers=outsider).status_code == 404
    r = client.post(
        f"/families/{family_id}/legacy",
        json={"type": "story", "title": "Intrusion", "body": "x"},
        headers=outsider,
    )
    assert r.status_code == 404
    r = client.post(
        f"/families/{family_id}/media", json={"content_type": "image/png"}, headers=outsider
    )
    assert r.status_code == 404
