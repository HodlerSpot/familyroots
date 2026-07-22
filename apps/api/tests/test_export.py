"""DSAR export (compliance WS3/WS5/WS6): bundle completeness for each scope,
standing enforcement, and — the load-bearing property — NO cross-family leak."""

import uuid
from datetime import date

from app.models import (
    MediaObject,
    MediaStatus,
    Prediction,
    PredictionRound,
    PredictionRoundStatus,
    User,
    utcnow,
)
from app.services.storage import get_storage

from .conftest import TestingSession, add_child, create_family, make_member, setup_fund, signup
from .test_erasure import _add_media_vault, _contribute


def _seed_sealed_round_with_predictions(child_id, author_id, *, body, year=2029):
    """Seed a SEALED (not-yet-released) round with one prediction and its keepsake
    PNG — the state a DSAR must surface as TEXT (behind a spoiler) but never as the
    image. Returns the keepsake media id."""
    key = f"keepsake-{uuid.uuid4().hex}"
    get_storage().put_object(key, b"\x89PNGkeepsake", "image/png")
    with TestingSession() as db:
        media = MediaObject(
            child_id=child_id,
            storage_key=key,
            content_type="image/png",
            byte_size=11,
            uploaded_by=author_id,
            status=MediaStatus.uploaded,
        )
        db.add(media)
        db.flush()
        rnd = PredictionRound(
            child_id=child_id,
            seals_on=date(year, 5, 1),
            status=PredictionRoundStatus.sealed,
            cloud_media_id=media.id,
            sealed_at=utcnow(),
        )
        db.add(rnd)
        db.flush()
        db.add(Prediction(round_id=rnd.id, author_user_id=author_id, body=body))
        db.commit()
        return media.id


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


def test_child_export_includes_sealed_predictions_separated_without_image(client):
    """Sealed, not-yet-released predictions are the child's personal data, so a
    DSAR includes their TEXT + AUTHORS behind a spoiler warning — but NEVER the
    sealed keepsake image (media id absent; download_media guard untouched)."""
    parent = signup(client, "sp2@ex.com", "Grandpa Joe")
    fid = create_family(client, parent)
    cid = add_child(client, parent, fid)
    _seed_child_content(client, parent, cid)  # an OPEN round + released nothing yet

    with TestingSession() as db:
        author_id = db.query(User).filter(User.email == "sp2@ex.com").one().id
    media_id = _seed_sealed_round_with_predictions(
        uuid.UUID(cid), author_id, body="a brave firefighter", year=2029
    )

    r = client.post(f"/families/{fid}/children/{cid}/data-export", headers=parent)
    assert r.status_code == 200, r.text
    child = r.json()["child"]

    # Sealed predictions present as text + author, behind a spoiler warning.
    section = child["sealed_unreleased_predictions"]
    assert "sealed until the child turns 18" in section["spoiler"]
    bodies = [p["body"] for rnd in section["rounds"] for p in rnd["predictions"]]
    authors = [p["author_name"] for rnd in section["rounds"] for p in rnd["predictions"]]
    assert "a brave firefighter" in bodies
    assert "Grandpa Joe" in authors
    assert any(rnd["year"] == 2029 for rnd in section["rounds"])

    # The sealed keepsake image is ABSENT everywhere in the bundle.
    import json as _json

    blob = _json.dumps(child)
    assert str(media_id) not in blob, "sealed keepsake media id leaked"
    assert all(m["media_id"] != str(media_id) for m in child["media"])
    # The separated section never carries an image/cloud_media_id reference.
    for rnd in section["rounds"]:
        assert "cloud_media_id" not in rnd
        assert "media_id" not in rnd

    # Released content unchanged: the Book + sealed-year index are still present,
    # and the sealed round's year appears in the existing sealed-year index too.
    assert "book" in child["predictions"]
    assert 2029 in child["predictions"]["sealed_years"]


def test_child_export_sealed_predictions_no_cross_family_leak(client):
    """One family's sealed predictions never surface in another family's child
    export — the section is scoped to the subject child like everything else."""
    parent_a = signup(client, "spa@ex.com", "Parent A")
    fid_a = create_family(client, parent_a, name="Alpha Family")
    cid_a = add_child(client, parent_a, fid_a, first_name="Aria")
    with TestingSession() as db:
        author_a = db.query(User).filter(User.email == "spa@ex.com").one().id
    _seed_sealed_round_with_predictions(uuid.UUID(cid_a), author_a, body="a kind vet")

    parent_b = signup(client, "spb@ex.com", "Aunt Beth")
    fid_b = create_family(client, parent_b, name="Bravo Family")
    cid_b = add_child(client, parent_b, fid_b, first_name="Bruno")
    with TestingSession() as db:
        author_b = db.query(User).filter(User.email == "spb@ex.com").one().id
    _seed_sealed_round_with_predictions(
        uuid.UUID(cid_b), author_b, body="SECRET astronaut"
    )

    r = client.post(f"/families/{fid_a}/children/{cid_a}/data-export", headers=parent_a)
    assert r.status_code == 200, r.text
    import json as _json

    blob = _json.dumps(r.json())
    assert "SECRET astronaut" not in blob
    assert "Aunt Beth" not in blob


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
