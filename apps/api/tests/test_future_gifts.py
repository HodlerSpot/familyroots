"""Future Gifts — the per-child "meaningful time preserved" estimate.

Service-level tests build content directly through the models (deterministic
byte sizes / bodies), then call the service. One API test confirms the
supporter-visibility rule on ChildOut.
"""

import uuid
from datetime import date

import pytest

from app.models import (
    CapsuleStatus,
    CapsuleType,
    Child,
    Contribution,
    ContributionStatus,
    Family,
    MediaObject,
    MediaStatus,
    ReleaseCondition,
    TimeCapsule,
    User,
    VaultItem,
    VaultItemType,
)
from app.services.future_gifts import (
    ACHIEVEMENT_SECONDS,
    AUDIO_BYTES_PER_SECOND,
    CAPSULE_LETTER_FLOOR_SECONDS,
    CAPSULE_MEDIA_FLOOR_SECONDS,
    MIN_ITEM_SECONDS,
    PHOTO_SECONDS,
    READING_CHARS_PER_SECOND,
    READING_MIN_SECONDS,
    VIDEO_BYTES_PER_SECOND,
    future_gifts_seconds_for_child,
    future_gifts_seconds_for_children,
)
from app.db import Base

from .conftest import (
    TestingSession,
    add_child,
    create_family,
    engine,
    signup,
)
from .test_supporter_access import make_supporter


@pytest.fixture()
def db():
    """A direct session over the shared in-memory engine (tables per test)."""
    Base.metadata.create_all(engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _make_child(db, first_name: str = "Emma") -> Child:
    user = User(
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Pat",
        password_hash="x",
    )
    db.add(user)
    db.flush()
    family = Family(name="Fam", created_by=user.id)
    db.add(family)
    db.flush()
    child = Child(
        family_id=family.id,
        first_name=first_name,
        birthdate=date(2018, 5, 1),
        created_by=user.id,
    )
    db.add(child)
    db.flush()
    return child


def _uploaded_media(db, child_id, byte_size: int, content_type: str = "video/mp4") -> MediaObject:
    media = MediaObject(
        child_id=child_id,
        storage_key=f"k/{uuid.uuid4().hex}",
        content_type=content_type,
        byte_size=byte_size,
        uploaded_by=_creator_of(db, child_id),
        status=MediaStatus.uploaded,
    )
    db.add(media)
    db.flush()
    return media


def _creator_of(db, child_id) -> uuid.UUID:
    return db.get(Child, child_id).created_by


def _add_vault(db, child, item_type, *, body=None, media=None, deleted_at=None):
    item = VaultItem(
        child_id=child.id,
        type=item_type,
        title="t",
        body=body,
        media_id=media.id if media else None,
        created_by=child.created_by,
        deleted_at=deleted_at,
    )
    db.add(item)
    db.flush()
    return item


# --- empty ------------------------------------------------------------------

def test_empty_child_is_zero(db):
    child = _make_child(db)
    assert future_gifts_seconds_for_child(db, child.id) == 0


def test_unknown_child_id_is_zero(db):
    assert future_gifts_seconds_for_child(db, uuid.uuid4()) == 0
    assert future_gifts_seconds_for_children(db, []) == {}


# --- each content type contributes -----------------------------------------

def test_photo_contributes_flat(db):
    child = _make_child(db)
    _add_vault(db, child, VaultItemType.photo)
    assert future_gifts_seconds_for_child(db, child.id) == PHOTO_SECONDS


def test_message_contributes_reading_time(db):
    child = _make_child(db)
    body = "a" * (READING_CHARS_PER_SECOND * 40)  # 40s of reading, above the floor
    _add_vault(db, child, VaultItemType.message, body=body)
    assert future_gifts_seconds_for_child(db, child.id) == 40


def test_short_message_hits_reading_floor(db):
    child = _make_child(db)
    _add_vault(db, child, VaultItemType.message, body="hi")
    assert future_gifts_seconds_for_child(db, child.id) == READING_MIN_SECONDS


def test_document_media_only_uses_document_floor(db):
    child = _make_child(db)
    media = _uploaded_media(db, child.id, 500, content_type="application/pdf")
    _add_vault(db, child, VaultItemType.document, media=media)
    from app.services.future_gifts import DOCUMENT_MEDIA_ONLY_SECONDS

    assert future_gifts_seconds_for_child(db, child.id) == DOCUMENT_MEDIA_ONLY_SECONDS


def test_video_contributes_byte_estimate(db):
    child = _make_child(db)
    byte_size = VIDEO_BYTES_PER_SECOND * 120  # ~2 minutes
    media = _uploaded_media(db, child.id, byte_size)
    _add_vault(db, child, VaultItemType.video, media=media)
    assert future_gifts_seconds_for_child(db, child.id) == 120


def test_voice_contributes_byte_estimate(db):
    child = _make_child(db)
    byte_size = AUDIO_BYTES_PER_SECOND * 45
    media = _uploaded_media(db, child.id, byte_size, content_type="audio/mpeg")
    _add_vault(db, child, VaultItemType.voice, media=media)
    assert future_gifts_seconds_for_child(db, child.id) == 45


def test_tiny_video_hits_global_floor(db):
    child = _make_child(db)
    media = _uploaded_media(db, child.id, 100)  # < 1 sec of bytes
    _add_vault(db, child, VaultItemType.video, media=media)
    assert future_gifts_seconds_for_child(db, child.id) == MIN_ITEM_SECONDS


def test_milestone_achievement_contributes_flat(db):
    child = _make_child(db)
    _add_vault(db, child, VaultItemType.achievement)
    assert future_gifts_seconds_for_child(db, child.id) == ACHIEVEMENT_SECONDS


def _add_capsule(db, child, capsule_type, *, body=None, media=None, status=CapsuleStatus.sealed):
    capsule = TimeCapsule(
        child_id=child.id,
        created_by=child.created_by,
        type=capsule_type,
        body=body,
        media_id=media.id if media else None,
        release_condition=ReleaseCondition.age,
        release_age=18,
        status=status,
    )
    db.add(capsule)
    db.flush()
    return capsule


def test_sealed_letter_capsule_counted(db):
    child = _make_child(db)
    _add_capsule(db, child, CapsuleType.letter, body="short", status=CapsuleStatus.sealed)
    assert future_gifts_seconds_for_child(db, child.id) == CAPSULE_LETTER_FLOOR_SECONDS


def test_released_video_capsule_counted(db):
    child = _make_child(db)
    media = _uploaded_media(db, child.id, VIDEO_BYTES_PER_SECOND * 90)
    _add_capsule(db, child, CapsuleType.video, media=media, status=CapsuleStatus.released)
    assert future_gifts_seconds_for_child(db, child.id) == 90


def test_audio_capsule_without_media_hits_floor(db):
    child = _make_child(db)
    _add_capsule(db, child, CapsuleType.audio)
    assert future_gifts_seconds_for_child(db, child.id) == CAPSULE_MEDIA_FLOOR_SECONDS


def _add_contribution(db, child, *, message=None, media=None, status=ContributionStatus.succeeded):
    contribution = Contribution(
        child_id=child.id,
        contributor_user_id=child.created_by,
        amount_cents=5000,
        currency="USD",
        fee_cents=175,
        message=message,
        media_id=media.id if media else None,
        status=status,
    )
    db.add(contribution)
    db.flush()
    return contribution


def test_succeeded_contribution_counts_message_and_video(db):
    child = _make_child(db)
    message = "b" * (READING_CHARS_PER_SECOND * 30)  # 30s reading
    media = _uploaded_media(db, child.id, VIDEO_BYTES_PER_SECOND * 20)  # 20s video
    _add_contribution(db, child, message=message, media=media)
    assert future_gifts_seconds_for_child(db, child.id) == 50


# --- exclusions -------------------------------------------------------------

def test_deleted_vault_item_excluded(db):
    child = _make_child(db)
    from datetime import datetime, timezone

    _add_vault(db, child, VaultItemType.photo, deleted_at=datetime.now(timezone.utc))
    assert future_gifts_seconds_for_child(db, child.id) == 0


def test_pending_video_media_excluded(db):
    child = _make_child(db)
    media = MediaObject(
        child_id=child.id,
        storage_key=f"k/{uuid.uuid4().hex}",
        content_type="video/mp4",
        byte_size=0,
        uploaded_by=child.created_by,
        status=MediaStatus.pending,
    )
    db.add(media)
    db.flush()
    _add_vault(db, child, VaultItemType.video, media=media)
    assert future_gifts_seconds_for_child(db, child.id) == 0


def test_zero_byte_uploaded_video_excluded(db):
    child = _make_child(db)
    media = _uploaded_media(db, child.id, 0)
    _add_vault(db, child, VaultItemType.video, media=media)
    assert future_gifts_seconds_for_child(db, child.id) == 0


def test_pending_and_failed_contributions_not_counted(db):
    child = _make_child(db)
    _add_contribution(db, child, message="x" * 400, status=ContributionStatus.pending)
    _add_contribution(db, child, message="x" * 400, status=ContributionStatus.failed)
    assert future_gifts_seconds_for_child(db, child.id) == 0


def test_family_legacy_item_never_counted(db):
    from app.models import LegacyItem, LegacyType

    child = _make_child(db)
    # A family-scoped legacy item (with media) must not touch any child total.
    media = MediaObject(
        family_id=child.family_id,
        storage_key=f"k/{uuid.uuid4().hex}",
        content_type="video/mp4",
        byte_size=VIDEO_BYTES_PER_SECOND * 600,
        uploaded_by=child.created_by,
        status=MediaStatus.uploaded,
    )
    db.add(media)
    db.flush()
    db.add(
        LegacyItem(
            family_id=child.family_id,
            type=LegacyType.story,
            title="Grandpa's story",
            body="c" * 5000,
            media_id=media.id,
            created_by=child.created_by,
        )
    )
    db.flush()
    assert future_gifts_seconds_for_child(db, child.id) == 0


# --- batch equals per-child -------------------------------------------------

def test_batch_equals_sum_of_singles(db):
    a = _make_child(db, "Ava")
    b = _make_child(db, "Ben")
    c = _make_child(db, "Cy")  # left empty
    _add_vault(db, a, VaultItemType.photo)
    _add_vault(db, a, VaultItemType.message, body="a" * 400)
    media = _uploaded_media(db, b.id, VIDEO_BYTES_PER_SECOND * 75)
    _add_vault(db, b, VaultItemType.video, media=media)
    _add_capsule(db, b, CapsuleType.letter, body="hello")

    ids = [a.id, b.id, c.id]
    batch = future_gifts_seconds_for_children(db, ids)
    assert batch == {cid: future_gifts_seconds_for_child(db, cid) for cid in ids}
    assert batch[c.id] == 0
    assert batch[a.id] > 0 and batch[b.id] > 0


# --- API visibility ---------------------------------------------------------

def test_supporter_sees_null_guardian_sees_number(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    # Give the child some content so a guardian sees a positive estimate.
    r = client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": "First words", "body": "z" * 400},
        headers=parent,
    )
    assert r.status_code == 201, r.text

    supporter = make_supporter(client, parent, family_id)

    guardian_view = client.get(f"/families/{family_id}", headers=parent)
    assert guardian_view.status_code == 200, guardian_view.text
    guardian_child = guardian_view.json()["children"][0]
    assert guardian_child["future_gifts_seconds"] is not None
    assert guardian_child["future_gifts_seconds"] > 0

    supporter_view = client.get(f"/families/{family_id}", headers=supporter)
    assert supporter_view.status_code == 200, supporter_view.text
    assert supporter_view.json()["children"][0]["future_gifts_seconds"] is None
