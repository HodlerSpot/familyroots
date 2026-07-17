"""The signed-in user's own cross-family views: notification switches, the
in-app notification inbox (bell), web-push subscriptions, a history of their
contributions, and their profile headshot."""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import and_, or_

from ..config import settings
from ..deps import CurrentUser, DbSession
from ..push_targets import validate_push_endpoint
from ..models import (
    Child,
    Contribution,
    Family,
    MediaObject,
    MediaStatus,
    Notification,
    NotificationPreference,
    PushSubscription,
    utcnow,
)
from ..schemas import (
    AvatarSet,
    InboxItemOut,
    InboxPage,
    MediaCreate,
    MediaUploadTicket,
    MyContributionOut,
    NotificationPrefs,
    PushSubscribeIn,
    PushUnsubscribeIn,
    UnreadCountOut,
    UserOut,
)
from ..services.notifications import DEFAULT_PREFS
from ..services.storage import get_storage

router = APIRouter(prefix="/me", tags=["me"])

# The 20 preference booleans (order-independent); push_public_key is read-only.
_PREF_FIELDS = tuple(DEFAULT_PREFS.keys())


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


def _prefs_out(pref: NotificationPreference | None) -> NotificationPrefs:
    """Serialize prefs (or the defaults) and stamp in the read-only VAPID
    public key so the browser can enroll for push without an Amplify env var."""
    values = (
        {f: getattr(pref, f) for f in _PREF_FIELDS} if pref is not None else dict(DEFAULT_PREFS)
    )
    return NotificationPrefs(**values, push_public_key=settings.vapid_public_key)


@router.get("/notifications", response_model=NotificationPrefs)
def get_notification_prefs(db: DbSession, user: CurrentUser) -> NotificationPrefs:
    pref = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user.id)
        .first()
    )
    return _prefs_out(pref)


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
    for field in _PREF_FIELDS:
        setattr(pref, field, getattr(payload, field))
    db.commit()
    return _prefs_out(pref)


# --- web push subscriptions ---

# The stored endpoint is later POSTed to from inside the VPC (see
# services.notify._deliver_push), so an arbitrary URL here is an SSRF sink.
# PushSubscribeIn.endpoint is validated at the schema; we re-check at the
# router as defense in depth (schema validation could be bypassed if this
# handler is ever called with a hand-built payload).
MAX_PUSH_SUBSCRIPTIONS_PER_USER = 20


@router.post("/push-subscriptions", status_code=status.HTTP_201_CREATED)
def subscribe_push(payload: PushSubscribeIn, db: DbSession, user: CurrentUser) -> dict:
    """Register this browser for web push. 503 when the feature is dark (no
    VAPID key). The endpoint is unique: re-subscribing reassigns it to whoever
    holds it now (shared-device handoff) and refreshes the encryption keys.
    Capped at MAX_PUSH_SUBSCRIPTIONS_PER_USER active rows per user; the oldest
    are evicted so the table can't grow without bound."""
    if not settings.vapid_private_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Push notifications aren't set up yet"
        )
    try:
        validate_push_endpoint(payload.endpoint)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    sub = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == payload.endpoint)
        .first()
    )
    if sub is None:
        sub = PushSubscription(
            user_id=user.id,
            endpoint=payload.endpoint,
            p256dh=payload.p256dh,
            auth=payload.auth,
            ua_label=payload.ua_label,
        )
        db.add(sub)
    else:
        sub.user_id = user.id
        sub.p256dh = payload.p256dh
        sub.auth = payload.auth
        sub.ua_label = payload.ua_label
    db.flush()  # assign created_at to a new row so the cap orders correctly
    _evict_excess_subscriptions(db, user.id)
    db.commit()
    return {"subscribed": True}


def _evict_excess_subscriptions(db: DbSession, user_id: uuid.UUID) -> None:
    """Keep only the newest MAX_PUSH_SUBSCRIPTIONS_PER_USER subscriptions for a
    user, deleting the oldest by created_at. Upserting an existing endpoint
    doesn't add a row, so a re-subscribe never triggers eviction."""
    subs = (
        db.query(PushSubscription)
        .filter(PushSubscription.user_id == user_id)
        .order_by(PushSubscription.created_at.desc(), PushSubscription.id.desc())
        .all()
    )
    for stale in subs[MAX_PUSH_SUBSCRIPTIONS_PER_USER:]:
        db.delete(stale)


@router.post("/push-subscriptions/unsubscribe")
def unsubscribe_push(
    payload: PushUnsubscribeIn, db: DbSession, user: CurrentUser
) -> dict:
    """Drop this browser's subscription. Scoped to the caller so one user can
    never delete another's row by guessing an endpoint."""
    db.query(PushSubscription).filter(
        PushSubscription.endpoint == payload.endpoint,
        PushSubscription.user_id == user.id,
    ).delete(synchronize_session=False)
    db.commit()
    return {"unsubscribed": True}


# --- in-app inbox (bell) ---

def _inbox_cursor(item: Notification) -> str:
    return f"{item.created_at.isoformat()}|{item.id}"


@router.get("/inbox", response_model=InboxPage)
def list_inbox(
    db: DbSession,
    user: CurrentUser,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> InboxPage:
    """The caller's bell items, newest first, keyset-paginated on
    (created_at, id)."""
    query = db.query(Notification).filter(Notification.user_id == user.id)
    if cursor:
        try:
            ts_str, _, id_str = cursor.partition("|")
            c_ts = datetime.fromisoformat(ts_str)
            c_id = uuid.UUID(id_str)
        except (ValueError, TypeError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Bad cursor")
        query = query.filter(
            or_(
                Notification.created_at < c_ts,
                and_(Notification.created_at == c_ts, Notification.id < c_id),
            )
        )
    rows = (
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit + 1)
        .all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return InboxPage(
        items=[InboxItemOut.model_validate(r) for r in rows],
        next_cursor=_inbox_cursor(rows[-1]) if has_more and rows else None,
    )


@router.get("/inbox/unread-count", response_model=UnreadCountOut)
def inbox_unread_count(db: DbSession, user: CurrentUser) -> UnreadCountOut:
    count = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .count()
    )
    return UnreadCountOut(count=count)


@router.post("/inbox/read-all")
def inbox_read_all(db: DbSession, user: CurrentUser) -> dict:
    now = utcnow()
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .update({Notification.read_at: now}, synchronize_session=False)
    )
    db.commit()
    return {"marked": updated}


@router.post("/inbox/{notification_id}/read", response_model=InboxItemOut)
def inbox_mark_read(
    notification_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> InboxItemOut:
    item = db.get(Notification, notification_id)
    # 404 (not 403) for another user's item, so ownership never leaks.
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    if item.read_at is None:
        item.read_at = utcnow()
        db.commit()
    return InboxItemOut.model_validate(item)


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
            fee_cents=contribution.fee_cents,
            status=contribution.status,
            refunded_cents=contribution.refunded_cents,
            message=contribution.message,
            created_at=contribution.created_at,
        )
        for contribution, child, family in rows
    ]
