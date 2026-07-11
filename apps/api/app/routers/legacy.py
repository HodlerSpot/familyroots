import uuid

from fastapi import APIRouter, HTTPException, status

from ..deps import CurrentUser, DbSession, get_active_membership
from ..models import LegacyItem, MediaObject, MediaStatus
from ..schemas import LegacyCreate, LegacyOut, MediaCreate, MediaUploadTicket

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
    get_active_membership(db, family_id, user)
    media = MediaObject(
        family_id=family_id,
        storage_key=str(uuid.uuid4()),
        content_type=payload.content_type,
        uploaded_by=user.id,
    )
    db.add(media)
    db.commit()
    return MediaUploadTicket(media_id=media.id, upload_url=f"/media/{media.id}/content")


@router.post(
    "/families/{family_id}/legacy",
    response_model=LegacyOut,
    status_code=status.HTTP_201_CREATED,
)
def add_legacy_item(
    family_id: uuid.UUID, payload: LegacyCreate, db: DbSession, user: CurrentUser
) -> LegacyOut:
    """Every family member can add to the archive — heritage is everyone's."""
    get_active_membership(db, family_id, user)
    if not payload.body and not payload.media_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Add the story itself — words, a photo, or a recording",
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
    db.commit()
    return _legacy_out(item)


@router.get("/families/{family_id}/legacy", response_model=list[LegacyOut])
def list_legacy(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[LegacyOut]:
    get_active_membership(db, family_id, user)
    items = (
        db.query(LegacyItem)
        .filter(LegacyItem.family_id == family_id)
        .order_by(LegacyItem.created_at.desc())
        .all()
    )
    return [_legacy_out(i) for i in items]
