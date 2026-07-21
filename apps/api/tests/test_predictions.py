"""Future Predictions — the yearly family word-cloud game.

Covers: the up-to-3-per-member cap, cloud aggregation, per-item edit/delete,
the full supporter matrix, birthday sealing (+ idempotency), empty-round skip,
the 18th-birthday finale (Book of Predictions), deterministic PNG rendering,
and the sealed-round download guard.

No freezegun in this codebase, so tests seed explicit dates: children are
created with the conftest birthdate, then the open round's `seals_on` (and,
for the finale, the child's birthdate) are set directly on the DB.
"""

import io
import uuid
from datetime import date

from PIL import Image

from app.models import (
    Child,
    FeedEvent,
    FeedEventType,
    MediaObject,
    MediaStatus,
    PredictionRound,
    PredictionRoundStatus,
)
from app.services.predictions import cloud_words, render_cloud_png, seal_due_prediction_rounds

from .conftest import (
    TestingSession,
    add_child,
    create_family,
    make_member,
    media_token,
    signup,
)

_EMPTY_COUNTS = {
    "prediction_rounds_sealed": 0,
    "prediction_rounds_skipped": 0,
    "prediction_rounds_released": 0,
}


def _open_round_id(child: str) -> uuid.UUID:
    with TestingSession() as db:
        return (
            db.query(PredictionRound)
            .filter_by(child_id=uuid.UUID(child), status=PredictionRoundStatus.open)
            .one()
            .id
        )


def _set_seals_on(child: str, when: date) -> uuid.UUID:
    with TestingSession() as db:
        rnd = (
            db.query(PredictionRound)
            .filter_by(child_id=uuid.UUID(child), status=PredictionRoundStatus.open)
            .one()
        )
        rnd.seals_on = when
        db.commit()
        return rnd.id


# --- the up-to-3 cap + cloud aggregation + per-item edit/delete --------------


def test_up_to_three_cap_edit_delete_and_aggregation(client):
    parent = signup(client, "p@example.com")
    fam = create_family(client, parent)
    child = add_child(client, parent, fam, "Emma")

    ids = []
    for body in ["astronaut and brave", "brave and kind", "brave explorer"]:
        r = client.post(f"/children/{child}/predictions", json={"body": body}, headers=parent)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    # The 4th is rejected with a warm 409.
    r = client.post(f"/children/{child}/predictions", json={"body": "one more"}, headers=parent)
    assert r.status_code == 409
    assert "all 3" in r.json()["detail"]

    # prediction_added fires exactly once (first submit), never on later adds.
    with TestingSession() as db:
        assert db.query(FeedEvent).filter_by(type=FeedEventType.prediction_added).count() == 1

    # The cloud aggregates all three distinct predictions ("brave" is in all 3).
    r = client.get(f"/children/{child}/predictions", headers=parent)
    game = r.json()
    cloud = {w["word"]: w["weight"] for w in game["round"]["cloud"]}
    assert cloud["brave"] == 3
    assert cloud["astronaut"] == 1
    assert "and" not in cloud  # stopword dropped
    assert "emma" not in cloud  # child first name dropped
    assert len(game["round"]["my_prediction_ids"]) == 3
    assert game["round"]["max_per_member"] == 3

    # Each of the three is independently editable and deletable.
    r = client.patch(f"/predictions/{ids[0]}", json={"body": "astronaut forever"}, headers=parent)
    assert r.status_code == 200 and r.json()["body"] == "astronaut forever"
    assert client.delete(f"/predictions/{ids[1]}", headers=parent).status_code == 204
    r = client.get(f"/children/{child}/predictions", headers=parent)
    assert len(r.json()["round"]["predictions"]) == 2

    # Editing added no feed noise.
    with TestingSession() as db:
        assert db.query(FeedEvent).filter_by(type=FeedEventType.prediction_added).count() == 1


def test_one_members_cap_does_not_block_another(client):
    parent = signup(client, "p@example.com")
    fam = create_family(client, parent)
    child = add_child(client, parent, fam)
    gp = make_member(client, parent, fam, "grandparent", "gp@example.com", "Grandpa")

    for i in range(3):
        r = client.post(f"/children/{child}/predictions", json={"body": f"parent guess {i}"}, headers=parent)
        assert r.status_code == 201
    assert client.post(f"/children/{child}/predictions", json={"body": "extra"}, headers=parent).status_code == 409

    # A different member is entirely unaffected by the first member's cap.
    assert client.post(f"/children/{child}/predictions", json={"body": "grandpa guess"}, headers=gp).status_code == 201


def test_body_validation(client):
    parent = signup(client, "p@example.com")
    fam = create_family(client, parent)
    child = add_child(client, parent, fam)
    assert client.post(f"/children/{child}/predictions", json={"body": " "}, headers=parent).status_code == 422
    assert client.post(f"/children/{child}/predictions", json={"body": "a"}, headers=parent).status_code == 422
    assert client.post(f"/children/{child}/predictions", json={"body": "x" * 121}, headers=parent).status_code == 422
    # Trimmed to a valid length.
    r = client.post(f"/children/{child}/predictions", json={"body": "  kind soul  "}, headers=parent)
    assert r.status_code == 201 and r.json()["body"] == "kind soul"


def test_non_member_cannot_touch_predictions(client):
    parent = signup(client, "p@example.com")
    fam = create_family(client, parent)
    child = add_child(client, parent, fam)
    stranger = signup(client, "stranger@example.com")
    assert client.get(f"/children/{child}/predictions", headers=stranger).status_code == 404
    assert client.post(f"/children/{child}/predictions", json={"body": "sneaky"}, headers=stranger).status_code == 404


# --- supporter matrix --------------------------------------------------------


def test_supporter_matrix(client):
    parent = signup(client, "p@example.com")
    fam = create_family(client, parent)
    child = add_child(client, parent, fam, "Emma")
    sup = make_member(client, parent, fam, "supporter", "s@example.com", "Sam")

    # A supporter may predict and view the open cloud...
    r = client.post(f"/children/{child}/predictions", json={"body": "world traveler"}, headers=sup)
    assert r.status_code == 201
    sup_pred_id = r.json()["id"]

    r = client.get(f"/children/{child}/predictions", headers=sup)
    assert r.status_code == 200
    game = r.json()
    # ...but NEVER the seal date, and never a "completed" signal. `year` is
    # `seals_on.year` (the next birthday) and alone reveals whether the birthday
    # has passed this year, so it too is withheld from supporters.
    assert game["round"]["seals_on"] is None
    assert game["round"]["year"] is None
    assert game["completed"] is False
    assert any(w["word"] in {"world", "traveler"} for w in game["round"]["cloud"])

    # The supporter's prediction_added feed payload must not carry the seal year.
    r = client.get(f"/families/{fam}/feed", headers=sup)
    added = next(e for e in r.json() if e["type"] == "prediction_added")
    assert "year" not in added["payload"]

    # A family member does see a real seal date and year.
    r = client.get(f"/children/{child}/predictions", headers=parent)
    assert r.json()["round"]["seals_on"] is not None
    assert r.json()["round"]["year"] is not None

    # A supporter can edit/delete their OWN, but not others'.
    assert client.patch(f"/predictions/{sup_pred_id}", json={"body": "globe trotter"}, headers=sup).status_code == 200
    parent_pred = client.post(f"/children/{child}/predictions", json={"body": "great cook"}, headers=parent).json()["id"]
    assert client.delete(f"/predictions/{parent_pred}", headers=sup).status_code == 403

    # Sealed-years and the book are family-only.
    assert client.get(f"/children/{child}/predictions/rounds", headers=sup).status_code == 403
    assert client.get(f"/children/{child}/predictions/book", headers=sup).status_code == 403

    # The feed shows a supporter prediction_added, never seal/release events.
    r = client.get(f"/families/{fam}/feed", headers=sup)
    types = {e["type"] for e in r.json()}
    assert "prediction_added" in types
    assert "predictions_sealed" not in types and "predictions_released" not in types


# --- sealing ------------------------------------------------------------------


def test_birthday_seal_opens_new_round_and_is_idempotent(client):
    parent = signup(client, "p@example.com")
    fam = create_family(client, parent)
    child = add_child(client, parent, fam, "Emma")
    assert client.post(f"/children/{child}/predictions", json={"body": "future astronaut"}, headers=parent).status_code == 201

    old_id = _set_seals_on(child, date.today())

    with TestingSession() as db:
        counts, _ = seal_due_prediction_rounds(db)
        db.commit()
    assert counts == {"prediction_rounds_sealed": 1, "prediction_rounds_skipped": 0, "prediction_rounds_released": 0}

    with TestingSession() as db:
        cid = uuid.UUID(child)
        sealed = db.get(PredictionRound, old_id)
        assert sealed.status == PredictionRoundStatus.sealed
        assert sealed.sealed_at is not None
        # A real image/png MediaObject was produced.
        media = db.get(MediaObject, sealed.cloud_media_id)
        assert media is not None
        assert media.content_type == "image/png"
        assert media.status == MediaStatus.uploaded
        assert media.child_id == cid and media.byte_size > 0
        # A fresh round opened; exactly one seal feed event fired.
        openrows = db.query(PredictionRound).filter_by(child_id=cid, status=PredictionRoundStatus.open).all()
        assert len(openrows) == 1 and openrows[0].id != old_id
        assert db.query(FeedEvent).filter_by(type=FeedEventType.predictions_sealed).count() == 1

    # Idempotent: a second sweep does nothing (no double seal, no second image).
    with TestingSession() as db:
        counts2, _ = seal_due_prediction_rounds(db)
        db.commit()
    assert counts2 == _EMPTY_COUNTS
    with TestingSession() as db:
        assert db.query(FeedEvent).filter_by(type=FeedEventType.predictions_sealed).count() == 1
        assert db.query(MediaObject).filter_by(child_id=uuid.UUID(child)).count() == 1

    # The sealed round is hidden from the game view (shows the NEW open round)...
    r = client.get(f"/children/{child}/predictions", headers=parent)
    assert r.json()["round"]["id"] != str(old_id)
    # ...but it appears in the family-only sealed-years list.
    r = client.get(f"/children/{child}/predictions/rounds", headers=parent)
    assert any(sr["id"] == str(old_id) for sr in r.json())


def test_empty_round_skips_without_fanfare(client):
    parent = signup(client, "p@example.com")
    fam = create_family(client, parent)
    child = add_child(client, parent, fam, "Emma")  # no predictions

    old_id = _set_seals_on(child, date.today())
    with TestingSession() as db:
        counts, _ = seal_due_prediction_rounds(db)
        db.commit()
    assert counts == {"prediction_rounds_sealed": 0, "prediction_rounds_skipped": 1, "prediction_rounds_released": 0}

    with TestingSession() as db:
        cid = uuid.UUID(child)
        skipped = db.get(PredictionRound, old_id)
        assert skipped.status == PredictionRoundStatus.skipped
        assert skipped.cloud_media_id is None
        assert db.query(MediaObject).filter_by(child_id=cid).count() == 0
        assert db.query(FeedEvent).filter_by(type=FeedEventType.predictions_sealed).count() == 0
        # The next round still opened the same day.
        assert db.query(PredictionRound).filter_by(child_id=cid, status=PredictionRoundStatus.open).count() == 1


def test_lazy_seal_on_read(client):
    """A read seals a due round inline (no maintenance sweep needed)."""
    parent = signup(client, "p@example.com")
    fam = create_family(client, parent)
    child = add_child(client, parent, fam, "Emma")
    assert client.post(f"/children/{child}/predictions", json={"body": "brave heart"}, headers=parent).status_code == 201
    old_id = _set_seals_on(child, date.today())

    r = client.get(f"/children/{child}/predictions", headers=parent)
    assert r.status_code == 200
    assert r.json()["round"]["id"] != str(old_id)  # a new round opened lazily
    with TestingSession() as db:
        assert db.get(PredictionRound, old_id).status == PredictionRoundStatus.sealed


def test_write_after_seal_is_rejected(client):
    parent = signup(client, "p@example.com")
    fam = create_family(client, parent)
    child = add_child(client, parent, fam, "Emma")
    r = client.post(f"/children/{child}/predictions", json={"body": "kind soul"}, headers=parent)
    pred_id = r.json()["id"]
    _set_seals_on(child, date.today())
    with TestingSession() as db:
        seal_due_prediction_rounds(db)
        db.commit()
    # Editing/deleting a now-sealed prediction is refused.
    assert client.patch(f"/predictions/{pred_id}", json={"body": "changed"}, headers=parent).status_code == 409
    assert client.delete(f"/predictions/{pred_id}", headers=parent).status_code == 409


# --- 18th-birthday finale -----------------------------------------------------


def test_eighteenth_birthday_releases_the_book(client):
    parent = signup(client, "p@example.com")
    fam = create_family(client, parent)
    child = add_child(client, parent, fam, "Emma")
    assert client.post(f"/children/{child}/predictions", json={"body": "kind and brilliant"}, headers=parent).status_code == 201

    today = date.today()
    cid = uuid.UUID(child)
    # Make Emma turn 18 today, with the open round sealing on that 18th birthday
    # (a "joined at 17" one-chapter book).
    with TestingSession() as db:
        db.get(Child, cid).birthdate = date(today.year - 18, today.month, today.day)
        rnd = db.query(PredictionRound).filter_by(child_id=cid, status=PredictionRoundStatus.open).one()
        rnd.seals_on = today
        db.commit()

    with TestingSession() as db:
        counts, _ = seal_due_prediction_rounds(db)
        db.commit()
    assert counts["prediction_rounds_sealed"] == 1
    assert counts["prediction_rounds_released"] == 1

    with TestingSession() as db:
        rounds = db.query(PredictionRound).filter_by(child_id=cid).all()
        assert len(rounds) == 1
        assert rounds[0].status == PredictionRoundStatus.released
        # No new round opens ever again.
        assert db.query(PredictionRound).filter_by(child_id=cid, status=PredictionRoundStatus.open).count() == 0
        # Exactly one predictions_released event; the seal fanfare is folded in.
        assert db.query(FeedEvent).filter_by(type=FeedEventType.predictions_released).count() == 1
        assert db.query(FeedEvent).filter_by(type=FeedEventType.predictions_sealed).count() == 0

    # The book shows the chapter with its keepsake PNG.
    r = client.get(f"/children/{child}/predictions/book", headers=parent)
    assert r.status_code == 200
    chapters = r.json()["chapters"]
    assert len(chapters) == 1
    assert chapters[0]["media_content_type"] == "image/png"
    assert chapters[0]["predictions"][0]["author_name"]  # attributed

    # The released image is now fetchable by family via download_media.
    tok = media_token(client, parent)
    r = client.get(f"/media/{chapters[0]['cloud_media_id']}?token={tok}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")

    # The game reads as complete; further writes are refused.
    r = client.get(f"/children/{child}/predictions", headers=parent)
    assert r.json()["round"] is None and r.json()["completed"] is True
    r = client.post(f"/children/{child}/predictions", json={"body": "too late"}, headers=parent)
    assert r.status_code == 409 and "complete" in r.json()["detail"]


# --- sealed-media guard -------------------------------------------------------


def test_sealed_round_image_is_hidden_from_everyone(client):
    parent = signup(client, "p@example.com")
    fam = create_family(client, parent)
    child = add_child(client, parent, fam, "Emma")
    assert client.post(f"/children/{child}/predictions", json={"body": "future scientist"}, headers=parent).status_code == 201
    old_id = _set_seals_on(child, date.today())
    with TestingSession() as db:
        seal_due_prediction_rounds(db)
        db.commit()
        media_id = db.get(PredictionRound, old_id).cloud_media_id

    # The sealed (not-yet-released) round image is 404 even for the parent —
    # the system sealed it, so there is no creator exception.
    tok = media_token(client, parent)
    r = client.get(f"/media/{media_id}?token={tok}")
    assert r.status_code == 404


# --- PNG rendering ------------------------------------------------------------


def test_png_is_deterministic_and_valid():
    rnd = PredictionRound(id=uuid.UUID("12345678-1234-5678-1234-567812345678"))
    words = cloud_words(
        ["astronaut brave kind", "brave explorer", "kind brave heart"],
        child_first_name="Emma",
    )
    kwargs = dict(child_first_name="Emma", ordinal_age=8, year=2027, prediction_count=3)
    first = render_cloud_png(rnd, words, **kwargs)
    second = render_cloud_png(rnd, words, **kwargs)

    # Same round id + same words -> byte-identical image.
    assert first == second
    # A real PNG that opens as a 1200x900 image.
    assert first[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(io.BytesIO(first))
    assert img.format == "PNG"
    assert img.size == (1200, 900)


def test_cloud_words_weighting_and_fallback():
    # Per-prediction dedupe: repeating a word in one prediction does not inflate.
    words = cloud_words(["brave brave brave", "brave kind"], child_first_name="Emma")
    weights = {w.word: w.weight for w in words}
    assert weights["brave"] == 2  # two distinct predictions contain it
    assert weights["kind"] == 1

    # Fallback: an all-stopword round still yields a cloud rather than nothing.
    words = cloud_words(["she will be"], child_first_name="Emma")
    assert words  # not empty (stopwords included on fallback)
