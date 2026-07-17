import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from ..config import settings
from ..deps import (
    CurrentUser,
    DbSession,
    bearer_scheme,
    get_active_membership,
    get_child_with_access,
    is_supporter,
    require_guardian_role,
    require_not_supporter,
)
from ..models import (
    CapsuleStatus,
    Child,
    Family,
    FamilyMember,
    FamilyRole,
    FeedEventType,
    MediaObject,
    MediaStatus,
    MemberStatus,
    TimeCapsule,
    User,
    VaultItem,
    VaultItemType,
)
from ..schemas import (
    ChildAvatarSet,
    ChildOut,
    MediaCreate,
    MediaUploadTicket,
    MilestoneCreate,
    VaultItemCreate,
    VaultItemOut,
    VaultItemVisibilityUpdate,
)
from ..security import decode_access_token, decode_media_token
from ..services.email_templates import render_email
from ..services.entitlements import Capability, require_capability
from ..services.feed import emit
from ..services.notify import (
    EmailPayload,
    NotificationKind,
    family_recipients,
    notify,
)
from ..services.future_gifts import future_gifts_seconds_for_child
from ..services.storage import get_storage
from .children import child_out

router = APIRouter(tags=["vault"])

DEFAULT_MAX_UPLOAD_MB = 10  # default attachment cap; families can be raised/lowered by an admin

# Common video-container ISO-BMFF brands (mp4/mov/m4v/3gp...). Deliberately an
# ALLOWLIST of clearly-video brands so we never mis-flag HEIC/AVIF stills
# (which also use the `ftyp` box) or m4a audio as video.
_VIDEO_FTYP_BRANDS = {
    b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1",
    b"mmp4", b"m4v ", b"qt  ", b"dash", b"msnv", b"3gp4", b"3gp5", b"3gp6",
    b"3g2a",
}


def _sniffed_is_video(head: bytes) -> bool:
    """Cheap, dependency-free container-signature sniff: True when the leading
    bytes look like a video container. Covers the realistic paywall bypass
    (rename a .mp4 to .jpg and declare image/*). Residual gap: exotic or
    fragmented containers with uncommon brands aren't caught — acceptable for a
    lightweight signature check; robust probing would need a media library."""
    if len(head) < 12:
        return False
    # ISO base media (mp4/mov/m4v/3gp): `ftyp` box at offset 4, brand at 8.
    if head[4:8] == b"ftyp" and head[8:12].lower() in _VIDEO_FTYP_BRANDS:
        return True
    # Matroska / WebM: EBML magic.
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return True
    # AVI: RIFF....AVI  (RIFF is shared with WAV/WebP, so require the AVI tag).
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return True
    # Flash Video.
    if head[:3] == b"FLV":
        return True
    # MPEG program stream / video sequence header.
    if head[:4] in (b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3"):
        return True
    return False


def _max_upload_bytes(db, media: MediaObject) -> int:
    """The attachment size cap for this media, from its owning family's setting
    (falling back to the default). Tester media (testnet) uses the default."""
    family = None
    if media.child_id is not None:
        child = db.get(Child, media.child_id)
        family = db.get(Family, child.family_id) if child else None
    elif media.family_id is not None:
        family = db.get(Family, media.family_id)
    mb = family.max_upload_mb if family else DEFAULT_MAX_UPLOAD_MB
    return mb * 1024 * 1024


def _vault_item_out(item: VaultItem) -> VaultItemOut:
    return VaultItemOut(
        id=item.id,
        type=item.type,
        title=item.title,
        body=item.body,
        media_id=item.media_id,
        media_content_type=item.media.content_type if item.media else None,
        visible_to_supporters=item.visible_to_supporters,
        created_by_name=item.author.display_name,
        created_at=item.created_at,
    )


# --- media ---

@router.post(
    "/children/{child_id}/media",
    response_model=MediaUploadTicket,
    status_code=status.HTTP_201_CREATED,
)
def create_media(
    child_id: uuid.UUID, payload: MediaCreate, db: DbSession, user: CurrentUser
) -> MediaUploadTicket:
    child, _ = get_child_with_access(db, child_id, user)
    # Video is a Premium capability (photos/voice/text stay free). Server-side
    # enforcement — the client's inline upsell is never the gate. Uploads in
    # flight at downgrade still complete: only the ticket is gated.
    if payload.content_type.startswith("video/"):
        require_capability(db, child.family_id, Capability.video_upload)
    media = MediaObject(
        child_id=child_id,
        storage_key=str(uuid.uuid4()),
        content_type=payload.content_type,
        uploaded_by=user.id,
    )
    db.add(media)
    db.commit()
    # Local: an API path the client PUTs to. S3: a presigned URL — bytes never
    # flow through the API. Same client contract either way.
    return MediaUploadTicket(media_id=media.id, upload_url=get_storage().upload_target(media))


@router.put("/media/{media_id}/content", status_code=status.HTTP_204_NO_CONTENT)
async def upload_media_content(
    media_id: uuid.UUID, request: Request, db: DbSession, user: CurrentUser
) -> None:
    """Local-backend upload path (S3 clients PUT to the presigned URL instead)."""
    media = db.get(MediaObject, media_id)
    if media is None or media.uploaded_by != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    if media.status != MediaStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "This upload is already complete")

    limit = _max_upload_bytes(db, media)
    body = await request.body()
    if len(body) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"That file is too large ({limit // (1024 * 1024)} MB max)",
        )
    get_storage().save(media.storage_key, io.BytesIO(body))
    db.commit()


@router.post("/media/{media_id}/complete", status_code=status.HTTP_204_NO_CONTENT)
def complete_media_upload(media_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    """Client signals the bytes are in storage; we verify before marking usable."""
    media = db.get(MediaObject, media_id)
    if media is None or media.uploaded_by != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    if media.status != MediaStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "This upload is already complete")

    size = get_storage().confirm_upload(media)
    if size is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The file never arrived. Please try again"
        )
    limit = _max_upload_bytes(db, media)
    if size > limit:
        get_storage().delete(media.storage_key)
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"That file is too large ({limit // (1024 * 1024)} MB max)",
        )
    # Video is a Premium capability and is gated at ticket time on the DECLARED
    # content_type. Verify the bytes don't smuggle a video in under an image/
    # audio declaration (a free family renaming clip.mp4 to photo.jpg). We only
    # sniff the non-video declarations — a legitimately declared video/* was
    # already entitlement-gated when its ticket was issued.
    declared = (media.content_type or "").lower()
    if declared.startswith(("image/", "audio/")):
        head = get_storage().read_head(media, 16)
        if head and _sniffed_is_video(head):
            get_storage().delete(media.storage_key)
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                "That file looks like a video. Video memories are part of "
                "FutureRoots Premium.",
            )
    media.byte_size = size
    media.status = MediaStatus.uploaded
    db.commit()


@router.get("/media/{media_id}")
def download_media(
    media_id: uuid.UUID,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    token: str | None = None,
):
    """Serves media to <img>/<video> tags, which can't send an Authorization
    header — so a credential must ride in the query string, a known leak
    surface (proxy logs, browser history, Referer). Trade-off: we keep
    ?token=, but it now accepts ONLY the short-lived media-scoped token (see
    security.create_media_token) — a full access JWT in the query string is
    rejected outright, so URLs never carry a session credential. API clients
    may instead send a normal Authorization: Bearer <access token> header.
    Local backend streams the file; S3 backend 307-redirects to a presigned URL."""
    if token:
        user_id = decode_media_token(token)  # media-scoped only; access JWTs fail
    elif credentials is not None:
        user_id = decode_access_token(credentials.credentials)
    else:
        user_id = None
    user = db.get(User, user_id) if user_id else None
    if user is None or user.disabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    media = db.get(MediaObject, media_id)
    if media is None or media.status != MediaStatus.uploaded:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")

    # A sealed capsule's attachment is for its creator's eyes only — never
    # fetchable by anyone else, even with a direct media URL.
    sealed_capsule = (
        db.query(TimeCapsule)
        .filter(
            TimeCapsule.media_id == media.id,
            TimeCapsule.status == CapsuleStatus.sealed,
        )
        .first()
    )
    if sealed_capsule is not None and sealed_capsule.created_by != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")

    if media.child_id is not None:
        child, membership = get_child_with_access(db, media.child_id, user)
        if is_supporter(membership.role):
            # A supporter may fetch only a child's avatar or media attached to a
            # memory/milestone explicitly shared with supporters — never anything
            # else, even holding a direct media id (e.g. after it was un-shared).
            is_avatar = child.avatar_media_id == media.id
            shared_item = (
                db.query(VaultItem)
                .filter(
                    VaultItem.media_id == media.id,
                    VaultItem.visible_to_supporters.is_(True),
                    VaultItem.deleted_at.is_(None),
                )
                .first()
            )
            if not is_avatar and shared_item is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    elif media.family_id is not None:
        membership = get_active_membership(db, media.family_id, user)
        # Family/legacy media is entirely off-limits to supporters.
        if is_supporter(membership.role):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    elif media.user_id is not None:
        # A member headshot: visible to the owner, or to anyone who shares an
        # active family with them (a co-member — including supporters, who see
        # each other's faces on shared surfaces).
        if media.user_id != user.id:
            my_families = db.query(FamilyMember.family_id).filter(
                FamilyMember.user_id == user.id,
                FamilyMember.status == MemberStatus.active,
            )
            co_member = (
                db.query(FamilyMember)
                .filter(
                    FamilyMember.user_id == media.user_id,
                    FamilyMember.status == MemberStatus.active,
                    FamilyMember.family_id.in_(my_families),
                )
                .first()
            )
            if co_member is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    elif media.tester_id is not None:
        # testnet bug-report screenshot: viewable only by the tester who uploaded it
        if media.uploaded_by != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    else:  # orphaned media is unreachable
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")

    return get_storage().download(media)


# --- vault ---

@router.post(
    "/children/{child_id}/vault",
    response_model=VaultItemOut,
    status_code=status.HTTP_201_CREATED,
)
def add_vault_item(
    child_id: uuid.UUID, payload: VaultItemCreate, db: DbSession, user: CurrentUser
) -> VaultItemOut:
    """Any family member may add memories — that's the point of FutureRoots.
    Supporters are guests, not contributors: they can view what's shared but
    not add to a child's vault."""
    child, membership = get_child_with_access(db, child_id, user)
    require_not_supporter(membership)

    if payload.media_id is not None:
        media = db.get(MediaObject, payload.media_id)
        if media is None or media.child_id != child_id or media.status != MediaStatus.uploaded:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Media not ready")

    item = VaultItem(
        child_id=child_id,
        type=payload.type,
        title=payload.title,
        body=payload.body,
        media_id=payload.media_id,
        created_by=user.id,
    )
    db.add(item)
    db.flush()
    emit(
        db,
        family_id=child.family_id,
        actor_user_id=user.id,
        type=FeedEventType.memory_added,
        child_id=child_id,
        payload={
            "vault_item_id": str(item.id),
            "item_type": item.type.value,
            "title": item.title,
            "child_name": child.first_name,
            "media_id": str(item.media_id) if item.media_id else None,
        },
    )
    db.commit()

    # New-memory notifications: bell + push (default on) + email (off by
    # default). Byte-identical email copy; supporters and the author excluded.
    family_url = f"{settings.web_base_url}/family/{child.family_id}/child/{child.id}"

    def memory_email(_recipient) -> EmailPayload:
        return EmailPayload(
            subject=f"A new memory for {child.first_name}",
            body=(
                f"Hello,\n\n"
                f"A new memory was just added to {child.first_name}'s vault:\n\n"
                f"  {item.title}\n\n"
                f"See it on the family feed: {family_url}\n\n"
                f"With warmth,\nThe FutureRoots team"
            ),
            html=render_email(
                preheader=f"A new memory was added to {child.first_name}'s vault.",
                greeting="Hello,",
                paragraphs=[
                    f"A new memory was just added to {child.first_name}'s vault."
                ],
                highlight=item.title,
                cta_label="See it on the family feed",
                cta_url=family_url,
            ),
        )

    batch = notify(
        db,
        kind=NotificationKind.memory,
        recipients=family_recipients(db, child.family_id, exclude_user_id=user.id),
        title=f"A new memory for {child.first_name}",
        body=f"Take a look: {item.title} just joined the vault.",
        url=f"/family/{child.family_id}/child/{child.id}",
        family_id=child.family_id,
        email_builder=memory_email,
    )
    db.commit()
    batch.deliver(db)
    return _vault_item_out(item)


@router.get("/children/{child_id}/vault", response_model=list[VaultItemOut])
def list_vault(child_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[VaultItemOut]:
    _, membership = get_child_with_access(db, child_id, user)
    query = db.query(VaultItem).filter(
        VaultItem.child_id == child_id, VaultItem.deleted_at.is_(None)
    )
    if membership.role == FamilyRole.supporter:
        # Supporters see only items a parent has explicitly shared with them.
        query = query.filter(VaultItem.visible_to_supporters.is_(True))
    items = query.order_by(VaultItem.created_at.desc()).all()
    return [_vault_item_out(i) for i in items]


@router.patch("/vault-items/{item_id}/visibility", response_model=VaultItemOut)
def set_vault_item_visibility(
    item_id: uuid.UUID,
    payload: VaultItemVisibilityUpdate,
    db: DbSession,
    user: CurrentUser,
) -> VaultItemOut:
    """Any parent decides what supporters can see, item by item."""
    item = db.get(VaultItem, item_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Memory not found")
    _, membership = get_child_with_access(db, item.child_id, user)
    if membership.role != FamilyRole.parent:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only a parent can change who sees this"
        )
    item.visible_to_supporters = payload.visible
    db.commit()
    return _vault_item_out(item)


@router.post("/children/{child_id}/avatar", response_model=ChildOut)
def set_child_avatar(
    child_id: uuid.UUID, payload: ChildAvatarSet, db: DbSession, user: CurrentUser
) -> ChildOut:
    """Set a child's headshot from an already-uploaded, child-scoped image.
    Child-critical, so parent/guardian only (not supporters)."""
    child, membership = get_child_with_access(db, child_id, user)
    require_guardian_role(membership)
    media = db.get(MediaObject, payload.media_id)
    if media is None or media.child_id != child_id or media.status != MediaStatus.uploaded:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Media not ready")
    child.avatar_media_id = media.id
    db.commit()
    # Guardian-only endpoint, so the estimate is always shown (never a supporter).
    return child_out(
        db, child, future_gifts_seconds=future_gifts_seconds_for_child(db, child.id)
    )


# --- milestones ---

@router.post(
    "/children/{child_id}/milestones",
    response_model=VaultItemOut,
    status_code=status.HTTP_201_CREATED,
)
def post_milestone(
    child_id: uuid.UUID, payload: MilestoneCreate, db: DbSession, user: CurrentUser
) -> VaultItemOut:
    """A milestone lands in the vault, on the feed, and in the family's inboxes —
    this notification is what brings grandparents to the door."""
    child, membership = get_child_with_access(db, child_id, user)
    require_not_supporter(membership)

    if payload.media_id is not None:
        media = db.get(MediaObject, payload.media_id)
        if media is None or media.child_id != child_id or media.status != MediaStatus.uploaded:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Media not ready")

    item = VaultItem(
        child_id=child_id,
        type=VaultItemType.achievement,
        title=payload.title,
        body=payload.description,
        media_id=payload.media_id,
        created_by=user.id,
    )
    db.add(item)
    db.flush()
    emit(
        db,
        family_id=child.family_id,
        actor_user_id=user.id,
        type=FeedEventType.milestone,
        child_id=child_id,
        payload={
            "vault_item_id": str(item.id),
            "title": item.title,
            "description": payload.description,
            "child_name": child.first_name,
            "media_id": str(item.media_id) if item.media_id else None,
        },
    )
    db.commit()

    # Milestone notifications: bell + push + email (all on by default) — the
    # nudge that brings grandparents to the door. Byte-identical email copy;
    # supporters and the author excluded.
    family_url = f"{settings.web_base_url}/family/{child.family_id}"
    contribute_url = f"{family_url}/child/{child.id}/contribute"
    highlight = payload.title + (f"\n{payload.description}" if payload.description else "")

    def milestone_email(_recipient) -> EmailPayload:
        return EmailPayload(
            subject=f"🎉 {child.first_name}: {payload.title}",
            body=(
                f"Hi there,\n\n"
                f"Wonderful news from your family: {child.first_name} just reached a "
                f"milestone.\n\n"
                f"  {payload.title}\n"
                + (f"  {payload.description}\n" if payload.description else "")
                + f"\nCelebrate with a gift to {child.first_name}'s future: {contribute_url}\n"
                f"Share in the moment on the family feed: {family_url}\n\n"
                f"With warmth,\nThe FutureRoots team"
            ),
            html=render_email(
                preheader=f"{child.first_name} just reached a milestone. Come celebrate!",
                greeting="Hi there,",
                paragraphs=[
                    f"Wonderful news from your family: {child.first_name} just "
                    f"reached a milestone."
                ],
                highlight=highlight,
                cta_label=f"Celebrate with a gift to {child.first_name}'s future",
                cta_url=contribute_url,
                secondary_label="Share in the moment on the family feed",
                secondary_url=family_url,
            ),
        )

    batch = notify(
        db,
        kind=NotificationKind.milestone,
        recipients=family_recipients(db, child.family_id, exclude_user_id=user.id),
        title=f"{child.first_name} just hit a milestone",
        body=f"{payload.title}. Tap in to celebrate with the family.",
        url=f"/family/{child.family_id}/child/{child.id}",
        family_id=child.family_id,
        email_builder=milestone_email,
    )
    db.commit()
    batch.deliver(db)
    return _vault_item_out(item)
