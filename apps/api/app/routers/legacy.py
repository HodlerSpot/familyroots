import uuid

from fastapi import APIRouter, HTTPException, status

from ..config import settings
from ..deps import (
    CurrentUser,
    DbSession,
    get_active_membership,
    require_not_supporter,
)
from ..models import Family, LegacyItem, MediaObject, MediaStatus
from ..schemas import LegacyCreate, LegacyOut, MediaCreate, MediaUploadTicket
from ..services.email_templates import render_email
from ..services.entitlements import Capability, require_capability
from ..services.notify import (
    EmailPayload,
    NotificationKind,
    family_recipients,
    notify,
)
from ..services.storage import get_storage
from ..testnet.service import award

router = APIRouter(tags=["legacy"])


def _legacy_out(item: LegacyItem) -> LegacyOut:
    return LegacyOut(
        id=item.id,
        type=item.type,
        title=item.title,
        body=item.body,
        media_id=item.media_id,
        media_content_type=item.media.content_type if item.media else None,
        created_by_name=item.author.display_name,
        created_at=item.created_at,
    )


@router.post(
    "/families/{family_id}/media",
    response_model=MediaUploadTicket,
    status_code=status.HTTP_201_CREATED,
)
def create_family_media(
    family_id: uuid.UUID, payload: MediaCreate, db: DbSession, user: CurrentUser
) -> MediaUploadTicket:
    """Family-scoped media for the legacy archive (child media stays under
    /children/{id}/media)."""
    membership = get_active_membership(db, family_id, user)
    require_not_supporter(membership)
    # Video is a Premium capability here too (defense in depth at every
    # media-ticket choke point).
    if payload.content_type.startswith("video/"):
        require_capability(db, family_id, Capability.video_upload)
    media = MediaObject(
        family_id=family_id,
        storage_key=str(uuid.uuid4()),
        content_type=payload.content_type,
        uploaded_by=user.id,
    )
    db.add(media)
    db.commit()
    return MediaUploadTicket(media_id=media.id, upload_url=get_storage().upload_target(media))


@router.post(
    "/families/{family_id}/legacy",
    response_model=LegacyOut,
    status_code=status.HTTP_201_CREATED,
)
def add_legacy_item(
    family_id: uuid.UUID, payload: LegacyCreate, db: DbSession, user: CurrentUser
) -> LegacyOut:
    """Every family member (but not a supporter) can add to the archive —
    heritage is the family's."""
    membership = get_active_membership(db, family_id, user)
    require_not_supporter(membership)
    if not payload.body and not payload.media_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Add the story itself: words, a photo, or a recording",
        )
    if payload.media_id is not None:
        media = db.get(MediaObject, payload.media_id)
        if media is None or media.family_id != family_id or media.status != MediaStatus.uploaded:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Media not ready")

    item = LegacyItem(
        family_id=family_id,
        type=payload.type,
        title=payload.title,
        body=payload.body,
        media_id=payload.media_id,
        created_by=user.id,
    )
    db.add(item)
    award(db, user.id, "legacy_added")  # testnet points; no-op in the family product
    db.commit()

    # Legacy notifications: email off by default (email_legacy); bell always,
    # push default off (mirrors the email default). Byte-identical email copy;
    # supporters and the author excluded.
    family = db.get(Family, family_id)
    archive_url = f"{settings.web_base_url}/family/{family_id}/legacy"

    def legacy_email(_recipient) -> EmailPayload:
        return EmailPayload(
            subject=f"A new story in {family.name}'s legacy archive",
            body=(
                f"Hello,\n\n"
                f"A new piece was just added to your family's legacy archive:\n\n"
                f"  {item.title}\n\n"
                f"Read it here: {archive_url}\n\n"
                f"With warmth,\nThe FutureRoots team"
            ),
            html=render_email(
                preheader="A new story was added to your family's legacy archive.",
                greeting="Hello,",
                paragraphs=["A new piece was just added to your family's legacy archive."],
                highlight=item.title,
                cta_label="Read it in the archive",
                cta_url=archive_url,
            ),
        )

    batch = notify(
        db,
        kind=NotificationKind.legacy,
        recipients=family_recipients(db, family_id, exclude_user_id=user.id),
        title="A new story in the family archive",
        body=f"{item.title} just joined your family's legacy archive.",
        url=f"/family/{family_id}/legacy",
        family_id=family_id,
        email_builder=legacy_email,
    )
    db.commit()
    batch.deliver(db)
    return _legacy_out(item)


@router.get("/families/{family_id}/legacy", response_model=list[LegacyOut])
def list_legacy(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[LegacyOut]:
    membership = get_active_membership(db, family_id, user)
    require_not_supporter(membership)
    items = (
        db.query(LegacyItem)
        .filter(LegacyItem.family_id == family_id)
        .order_by(LegacyItem.created_at.desc())
        .all()
    )
    return [_legacy_out(i) for i in items]
