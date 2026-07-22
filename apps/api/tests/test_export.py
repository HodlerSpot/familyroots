"""DSAR export (compliance WS3/WS5/WS6): bundle completeness for each scope,
standing enforcement, and — the load-bearing property — NO cross-family leak."""

import uuid

from .conftest import add_child, create_family, make_member, setup_fund, signup
from .test_erasure import _add_media_vault, _contribute


def _seed_child_content(client, parent, cid):
    setup_fund(client, parent, cid)
    _add_media_vault(client, parent, cid, title="Beach day")
    _contribute(client, parent, cid)
    client.post(f"/children/{cid}/predictions", json={"body": "a kind doctor"}, headers=parent)


def test_member_export_completeness(client):
    parent = signup(client, "m@ex.com", "Parent")
    fid = create_family(client, parent)
    cid = add_child(client, parent, fid)
    _seed_child_content(client, parent, cid)

    r = client.post("/me/data-export", headers=parent)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope"] == "member"
    assert body["profile"]["email"] == "m@ex.com"
    # every member-scoped section is represented
    for key in ("notification_preferences", "families", "contributions", "premium", "authored", "media"):
        assert key in body
    assert len(body["families"]) == 1
    assert len(body["contributions"]) == 1
    assert body["contributions"][0]["amount_cents"] == 1500
    # the adult's own authored memory + prediction are their personal data
    assert any(v["title"] == "Beach day" for v in body["authored"]["vault_items"])
    assert any(p["body"] == "a kind doctor" for p in body["authored"]["predictions"])


def test_child_export_completeness(client):
    parent = signup(client, "cp@ex.com", "Parent")
    fid = create_family(client, parent)
    cid = add_child(client, parent, fid)
    _seed_child_content(client, parent, cid)

    r = client.post(f"/families/{fid}/children/{cid}/data-export", headers=parent)
    assert r.status_code == 200, r.text
    child = r.json()["child"]
    for key in (
        "profile",
        "consent_records",
        "vault_items",
        "badges",
        "goals",
        "goal_completions",
        "time_capsules",
        "predictions",
        "contributions",
        "fund",
        "feed_events",
        "media",
    ):
        assert key in child, key
    assert child["profile"]["first_name"] == "Emma"
    assert len(child["consent_records"]) >= 1
    assert child["fund"]["balance_cents"] > 0
    assert len(child["media"]) >= 1


def test_export_no_cross_family_leak(client):
    parent_a = signup(client, "fa@ex.com", "Parent A")
    fid_a = create_family(client, parent_a, name="Alpha Family")
    cid_a = add_child(client, parent_a, fid_a, first_name="Aria")
    _seed_child_content(client, parent_a, cid_a)

    parent_b = signup(client, "fb@ex.com", "Parent B")
    fid_b = create_family(client, parent_b, name="Bravo Family")
    cid_b = add_child(client, parent_b, fid_b, first_name="Bruno")
    _seed_child_content(client, parent_b, cid_b)

    # A exports its whole family; nothing about B may appear anywhere.
    r = client.post(f"/families/{fid_a}/data-export", headers=parent_a)
    assert r.status_code == 200, r.text
    import json

    blob = json.dumps(r.json())
    for needle in (fid_b, cid_b, "Bravo Family", "Bruno", "fb@ex.com"):
        assert needle not in blob, f"cross-family leak: {needle}"

    # A cannot export B's family at all (no membership -> 404, no existence leak).
    assert client.post(f"/families/{fid_b}/data-export", headers=parent_a).status_code == 404
    # A cannot export B's child.
    assert (
        client.post(f"/families/{fid_b}/children/{cid_b}/data-export", headers=parent_a).status_code
        == 404
    )


def test_export_media_manifest_hides_storage_key(client):
    """Art. 20 fix #5: no manifest anywhere exposes the internal storage_key;
    every entry is retrievable by media_id + content_type instead."""
    parent = signup(client, "mk@ex.com", "Parent")
    fid = create_family(client, parent)
    cid = add_child(client, parent, fid)
    _seed_child_content(client, parent, cid)

    for path in (
        "/me/data-export",
        f"/families/{fid}/children/{cid}/data-export",
        f"/families/{fid}/data-export",
    ):
        r = client.post(path, headers=parent)
        assert r.status_code == 200, r.text
        body = r.json()
        import json as _json

        assert '"storage_key"' not in _json.dumps(body), f"storage_key leaked in {path}"

    # spot-check the shape of a child media entry: retrievable id, no raw key
    child = client.post(
        f"/families/{fid}/children/{cid}/data-export", headers=parent
    ).json()["child"]
    assert len(child["media"]) >= 1
    entry = child["media"][0]
    assert "storage_key" not in entry
    assert entry["media_id"] and "content_type" in entry and "filename" in entry


def test_family_export_omits_member_emails(client):
    """Art. 15(4) fix #6: a family export lists other members by display_name +
    role only — never their email addresses."""
    parent = signup(client, "fe@ex.com", "Parent")
    fid = create_family(client, parent)
    make_member(client, parent, fid, "grandparent", "grandma@ex.com", "Grandma")

    r = client.post(f"/families/{fid}/data-export", headers=parent)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["members"]) == 2
    for m in body["members"]:
        assert "email" not in m
        assert set(m.keys()) == {"display_name", "role"}
    import json as _json

    # neither member's email appears anywhere in the family bundle
    blob = _json.dumps(body)
    assert "fe@ex.com" not in blob and "grandma@ex.com" not in blob


def test_member_export_includes_broadened_own_data(client):
    """Art. 15 breadth fix #10: the member export carries the member's own
    notifications, push subscriptions (endpoint only), fund nudges, memory
    prompts, capsule release votes, and consent records they granted."""
    parent = signup(client, "br@ex.com", "Parent")
    fid = create_family(client, parent)
    add_child(client, parent, fid)  # granting parental_consent records a consent row

    r = client.post("/me/data-export", headers=parent)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "notifications",
        "push_subscriptions",
        "fund_nudges",
        "memory_prompts",
        "capsule_release_votes",
        "consent_granted",
        "media_retrieval",
    ):
        assert key in body, key
    # the parent granted a consent record when adding the child
    assert len(body["consent_granted"]) >= 1
    # push subscription encryption keys are never exported (endpoint only)
    import json as _json

    assert "p256dh" not in _json.dumps(body)


def test_child_export_denied_to_supporter(client):
    parent = signup(client, "sp@ex.com", "Parent")
    fid = create_family(client, parent)
    cid = add_child(client, parent, fid)
    supporter = make_member(client, parent, fid, "supporter", "sup@ex.com", "Coach")
    # a supporter holds no parent/guardian edge to the child
    r = client.post(f"/families/{fid}/children/{cid}/data-export", headers=supporter)
    assert r.status_code == 403, r.text


def test_family_export_requires_parent(client):
    parent = signup(client, "gp@ex.com", "Parent")
    fid = create_family(client, parent)
    grandparent = make_member(client, parent, fid, "grandparent", "gpa@ex.com", "Grandpa")
    r = client.post(f"/families/{fid}/data-export", headers=grandparent)
    assert r.status_code == 403, r.text
    # but a grandparent CAN export their own member data
    assert client.post("/me/data-export", headers=grandparent).status_code == 200
