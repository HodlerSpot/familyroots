from .conftest import create_family, signup


def test_create_and_list_family(client):
    headers = signup(client, "parent@example.com")
    family_id = create_family(client, headers, "The Salignas")

    r = client.get("/families", headers=headers)
    assert r.status_code == 200
    assert [f["id"] for f in r.json()] == [family_id]
    assert r.json()[0]["role"] == "parent"


def test_family_detail_shows_members(client):
    headers = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, headers)

    r = client.get(f"/families/{family_id}", headers=headers)
    assert r.status_code == 200
    members = r.json()["members"]
    assert len(members) == 1
    assert members[0]["role"] == "parent"
    assert members[0]["user"]["display_name"] == "Pat"


def test_no_cross_family_access(client):
    """A user must never see a family they don't belong to — and must not
    even learn that it exists (404, not 403)."""
    headers_a = signup(client, "a@example.com")
    family_a = create_family(client, headers_a, "Family A")

    headers_b = signup(client, "b@example.com")
    r = client.get(f"/families/{family_a}", headers=headers_b)
    assert r.status_code == 404

    r = client.get(f"/families/{family_a}/children", headers=headers_b)
    assert r.status_code == 404

    r = client.get("/families", headers=headers_b)
    assert r.json() == []
