"""Future Gifts — a per-child "meaningful time preserved" indicator.

Future Gifts is a warm, motivating estimate of how much meaningful time of
memories, stories, wisdom, and love a family has preserved for a child. It sums
an estimated "meaningful consumption seconds" figure over the child's OWN
content (vault items, time capsules, and the notes/videos attached to settled
contributions). It is computed live on read — like `fund_balance_cents` — with
no stored column and no cache, so it naturally rises with every addition.

    ⚠️ THE PER-TYPE VALUES BELOW ARE ESTIMATES, NOT MEASUREMENTS.

There is no real media duration anywhere in the schema (`MediaObject` stores
only `byte_size` + `content_type`), so photo/text/media time is *estimated* from
a heuristic per content type and, for audio/video, from byte size. The constants
are deliberately gathered here and named so they stay easy to tune; changing one
simply shifts the estimate, it never changes what counts.

Excluded by design: child avatar media, soft-deleted vault items
(`deleted_at IS NOT NULL`), family-level Legacy Archive items, and goals/badges.
"""

import uuid

from sqlalchemy.orm import Session

from ..models import (
    CapsuleType,
    Contribution,
    ContributionStatus,
    MediaObject,
    MediaStatus,
    TimeCapsule,
    VaultItem,
    VaultItemType,
)

# --- Per-type ESTIMATE constants (tunable; see module docstring) -------------

# Flat estimates for fixed-shape items.
PHOTO_SECONDS = 30
ACHIEVEMENT_SECONDS = 60          # VaultItemType.achievement (a milestone)
DOCUMENT_MEDIA_ONLY_SECONDS = 60  # a document with no written body

# Reading time (~200 wpm ≈ 17 characters/second), with a gentle floor so a
# one-line memory still reads as meaningful.
READING_CHARS_PER_SECOND = 17
READING_MIN_SECONDS = 20

# Media time estimated from byte size (no duration is stored):
#   video ≈ 2.5 MB/min → 41_667 bytes/sec; audio/voice ≈ 1 MB/min → 16_667.
VIDEO_BYTES_PER_SECOND = 41_667
AUDIO_BYTES_PER_SECOND = 16_667

# Time-capsule floors — a sealed capsule is a preserved gift either way.
CAPSULE_LETTER_FLOOR_SECONDS = 60
CAPSULE_MEDIA_FLOOR_SECONDS = 30

# Global per-item floor so every addition is meaningful (a 3-second clip counts).
MIN_ITEM_SECONDS = 15


def _reading_seconds(body: str | None) -> int:
    """Estimated reading time of `body` in whole seconds (0 for empty)."""
    if not body:
        return 0
    return len(body) // READING_CHARS_PER_SECOND


def _media_uploaded(status, byte_size: int | None) -> bool:
    """Media counts only once it has actually uploaded with real bytes;
    pending/deleted media and empty (byte_size 0) media do not."""
    return status == MediaStatus.uploaded and (byte_size or 0) > 0


def _byte_seconds(status, byte_size: int | None, bytes_per_second: int) -> int:
    """Estimated media seconds from byte size (0 for media that hasn't
    uploaded). Callers apply their own floor to counted items."""
    if _media_uploaded(status, byte_size):
        return (byte_size or 0) // bytes_per_second
    return 0


def future_gifts_seconds_for_children(
    db: Session, child_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Batch: estimated Future Gifts seconds for each child id, in a bounded
    number of grouped queries (never N+1 per child). A child with nothing maps
    to 0. Modeled on the batch shape of `entitlements.plans_for_families` and
    the aggregate shape of `payments.fund_balance_cents`."""
    result: dict[uuid.UUID, int] = {cid: 0 for cid in child_ids}
    if not child_ids:
        return result

    # --- Vault items (⨝ their optional media), soft-deleted excluded ---------
    vault_rows = (
        db.query(
            VaultItem.child_id,
            VaultItem.type,
            VaultItem.body,
            MediaObject.status,
            MediaObject.byte_size,
        )
        .outerjoin(MediaObject, VaultItem.media_id == MediaObject.id)
        .filter(
            VaultItem.child_id.in_(child_ids),
            VaultItem.deleted_at.is_(None),
        )
        .all()
    )
    for child_id, item_type, body, media_status, byte_size in vault_rows:
        if item_type == VaultItemType.photo:
            secs = PHOTO_SECONDS
        elif item_type == VaultItemType.achievement:
            secs = ACHIEVEMENT_SECONDS
        elif item_type == VaultItemType.message:
            secs = max(READING_MIN_SECONDS, _reading_seconds(body))
        elif item_type == VaultItemType.document:
            secs = (
                max(READING_MIN_SECONDS, _reading_seconds(body))
                if body
                else DOCUMENT_MEDIA_ONLY_SECONDS
            )
        elif item_type == VaultItemType.video:
            if not _media_uploaded(media_status, byte_size):
                continue  # media not uploaded / no bytes → nothing preserved yet
            secs = byte_size // VIDEO_BYTES_PER_SECOND  # tiny clips floor to MIN
        elif item_type == VaultItemType.voice:
            if not _media_uploaded(media_status, byte_size):
                continue
            secs = byte_size // AUDIO_BYTES_PER_SECOND
        else:  # pragma: no cover — enum is exhaustive above
            continue
        result[child_id] += max(MIN_ITEM_SECONDS, secs)

    # --- Time capsules (⨝ their optional media); sealed OR released count -----
    capsule_rows = (
        db.query(
            TimeCapsule.child_id,
            TimeCapsule.type,
            TimeCapsule.body,
            MediaObject.status,
            MediaObject.byte_size,
        )
        .outerjoin(MediaObject, TimeCapsule.media_id == MediaObject.id)
        .filter(TimeCapsule.child_id.in_(child_ids))
        .all()
    )
    for child_id, capsule_type, body, media_status, byte_size in capsule_rows:
        if capsule_type == CapsuleType.letter:
            secs = max(CAPSULE_LETTER_FLOOR_SECONDS, _reading_seconds(body))
        else:  # audio / video
            per_second = (
                VIDEO_BYTES_PER_SECOND
                if capsule_type == CapsuleType.video
                else AUDIO_BYTES_PER_SECOND
            )
            secs = max(
                CAPSULE_MEDIA_FLOOR_SECONDS,
                _byte_seconds(media_status, byte_size, per_second),
            )
        result[child_id] += max(MIN_ITEM_SECONDS, secs)

    # --- Settled contributions: the note + any attached video message --------
    # (The money itself is the Future Fund, a separate concept — not counted.)
    contribution_rows = (
        db.query(
            Contribution.child_id,
            Contribution.message,
            MediaObject.status,
            MediaObject.byte_size,
        )
        .outerjoin(MediaObject, Contribution.media_id == MediaObject.id)
        .filter(
            Contribution.child_id.in_(child_ids),
            Contribution.status == ContributionStatus.succeeded,
        )
        .all()
    )
    for child_id, message, media_status, byte_size in contribution_rows:
        secs = _reading_seconds(message) + _byte_seconds(
            media_status, byte_size, VIDEO_BYTES_PER_SECOND
        )
        result[child_id] += max(MIN_ITEM_SECONDS, secs)

    return result


def future_gifts_seconds_for_child(db: Session, child_id: uuid.UUID) -> int:
    """Convenience single-child wrapper over the batch computation."""
    return future_gifts_seconds_for_children(db, [child_id])[child_id]
