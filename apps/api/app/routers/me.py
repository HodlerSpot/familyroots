"""The signed-in user's own cross-family views: notification switches, a
history of their contributions, and their profile headshot."""

import uuid

from fastapi import APIRouter, HTTPException, status

from ..deps import CurrentUser, DbSession
from ..models import (
    Child,
    Contribution,
    Family,
    MediaObject,
    MediaStatus,
    NotificationPreference,
)
from ..schemas import (
    AvatarSet,
    MediaCreate,
    MediaUploadTicket,
    MyContributionOut,
    NotificationPrefs,
    UserOut,
)
from ..services.notifications import DEFAULT_PREFS
from ..services.storage import get_storage

router = APIRouter(prefix="/me", tags=["me"])


@router.post("/media", response_model=MediaUploadTicket, status_code=status.HTTP_201_CREATED)
def create_my_media(
    payload: MediaCreate, db: DbSession, user: CurrentUser
) -> MediaUploadTicket:
    """Start a user-scoped upload for the caller's profile headshot. Same
    upload contract as vault media: PUT to upload_url, then POST
    /media/{id}/complete (both already gate on uploaded_by == caller)."""
    media = MediaObject(
        user_id=user.id,
        storage_key=str(uuid.uuid4()),
        content_type=payload.content_type,
        uploaded_by=user.id,
    )
    db.add(media)
    db.commit()
    return MediaUploadTicket(media_id=media.id, upload_url=get_storage().upload_target(media))


@router.post("/avatar", response_model=UserOut)
def set_my_avatar(payload: AvatarSet, db: DbSession, user: CurrentUser) -> UserOut:
    """Set the caller's headshot from an already-uploaded, user-scoped image."""
    media = db.get(MediaObject, payload.media_id)
    if (
        media is None
        or media.user_id != user.id
        or media.status != MediaStatus.uploaded
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Media not ready")
    user.avatar_media_id = media.id
    db.commit()
    return UserOut.model_validate(user)


@router.get("/notifications", response_model=NotificationPrefs)
def get_notification_prefs(db: DbSession, user: CurrentUser) -> NotificationPrefs:
    pref = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user.id)
        .first()
    )
    if pref is None:
        return NotificationPrefs(**DEFAULT_PREFS)
    return NotificationPrefs.model_validate(pref, from_attributes=True)


@router.put("/notifications", response_model=NotificationPrefs)
def set_notification_prefs(
    payload: NotificationPrefs, db: DbSession, user: CurrentUser
) -> NotificationPrefs:
    pref = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user.id)
        .first()
    )
    if pref is None:
        pref = NotificationPreference(user_id=user.id)
        db.add(pref)
    pref.email_new_member = payload.email_new_member
    pref.email_milestone = payload.email_milestone
    pref.email_memory = payload.email_memory
    pref.email_legacy = payload.email_legacy
    db.commit()
    return NotificationPrefs.model_validate(pref, from_attributes=True)


@router.get("/contributions", response_model=list[MyContributionOut])
def my_contributions(db: DbSession, user: CurrentUser) -> list[MyContributionOut]:
    rows = (
        db.query(Contribution, Child, Family)
        .join(Child, Contribution.child_id == Child.id)
        .join(Family, Child.family_id == Family.id)
        .filter(Contribution.contributor_user_id == user.id)
        .order_by(Contribution.created_at.desc(), Contribution.id.desc())
        .all()
    )
    return [
        MyContributionOut(
            id=contribution.id,
            child_name=child.first_name,
            family_name=family.name,
            amount_cents=contribution.amount_cents,
            currency=contribution.currency,
            status=contribution.status,
            refunded_cents=contribution.refunded_cents,
            message=contribution.message,
            created_at=contribution.created_at,
        )
        for contribution, child, family in rows
    ]
