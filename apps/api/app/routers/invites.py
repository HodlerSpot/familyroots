import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, HTTPException, status

from ..config import settings
from ..deps import CurrentUser, DbSession, get_active_membership, require_guardian_role
from ..models import (
    Child,
    ChildRelationship,
    FamilyInvite,
    FamilyMember,
    MemberStatus,
    User,
    utcnow,
)
from ..models import FeedEventType
from ..schemas import FamilySummary, InviteAccept, InviteCreate, InviteOut, InvitePreview
from ..services.email import get_email_sender
from ..services.feed import emit
from ..services.text import family_phrase

router = APIRouter(tags=["invites"])


@router.post(
    "/families/{family_id}/invites",
    response_model=InviteOut,
    status_code=status.HTTP_201_CREATED,
)
def create_invite(
    family_id: uuid.UUID, payload: InviteCreate, db: DbSession, user: CurrentUser
) -> InviteOut:
    membership = get_active_membership(db, family_id, user)
    require_guardian_role(membership)

    email = payload.email.lower()
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        already_member = (
            db.query(FamilyMember)
            .filter(
                FamilyMember.family_id == family_id,
                FamilyMember.user_id == existing_user.id,
                FamilyMember.status == MemberStatus.active,
            )
            .first()
        )
        if already_member:
            raise HTTPException(status.HTTP_409_CONFLICT, "They're already part of this family")

    invite = FamilyInvite(
        family_id=family_id,
        email=email,
        role=payload.role,
        token=secrets.token_urlsafe(32),
        invited_by=user.id,
        expires_at=utcnow() + timedelta(days=settings.invite_ttl_days),
    )
    db.add(invite)
    db.commit()

    family = family_phrase(invite.family.name)
    accept_url = f"{settings.web_base_url}/invites/{invite.token}"
    get_email_sender().send(
        to=email,
        subject=f"{user.display_name} invited you to join {family} on FutureRoots",
        body=(
            f"Hi!\n\n"
            f"{user.display_name} has invited you to join {family} on "
            f"FutureRoots — a private space where your family shares memories, celebrates "
            f"milestones, and builds a future together.\n\n"
            f"Join here: {accept_url}\n\n"
            f"This invitation expires in {settings.invite_ttl_days} days.\n\n"
            f"With warmth,\nThe FutureRoots team"
        ),
    )
    return InviteOut.model_validate(invite)


def _get_valid_invite(db, token: str) -> FamilyInvite:
    invite = db.query(FamilyInvite).filter(FamilyInvite.token == token).first()
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    if invite.accepted_at is not None:
        raise HTTPException(status.HTTP_410_GONE, "This invitation has already been used")
    expires_at = invite.expires_at
    if expires_at.tzinfo is None:  # SQLite loses tz info in tests
        from datetime import timezone

        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < utcnow():
        raise HTTPException(status.HTTP_410_GONE, "This invitation has expired")
    return invite


@router.get("/invites/{token}", response_model=InvitePreview)
def preview_invite(token: str, db: DbSession) -> InvitePreview:
    """Unauthenticated preview so the invite page can greet the person by context."""
    invite = _get_valid_invite(db, token)
    inviter = db.get(User, invite.invited_by)
    return InvitePreview(
        family_name=invite.family.name,
        role=invite.role,
        invited_by=inviter.display_name,
    )


@router.post("/invites/accept", response_model=FamilySummary)
def accept_invite(payload: InviteAccept, db: DbSession, user: CurrentUser) -> FamilySummary:
    invite = _get_valid_invite(db, payload.token)
    if user.email != invite.email:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This invitation was sent to a different email address",
        )

    existing = (
        db.query(FamilyMember)
        .filter(
            FamilyMember.family_id == invite.family_id,
            FamilyMember.user_id == user.id,
            FamilyMember.status == MemberStatus.active,
        )
        .first()
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "You're already part of this family")

    db.add(
        FamilyMember(
            family_id=invite.family_id,
            user_id=user.id,
            role=invite.role,
            status=MemberStatus.active,
            invited_by=invite.invited_by,
        )
    )

    # New member gets a Family Graph edge to every existing child
    children = db.query(Child).filter(Child.family_id == invite.family_id).all()
    for child in children:
        db.add(
            ChildRelationship(
                child_id=child.id,
                user_id=user.id,
                relationship_type=invite.role,
            )
        )

    invite.accepted_at = utcnow()
    emit(
        db,
        family_id=invite.family_id,
        actor_user_id=user.id,
        type=FeedEventType.member_joined,
        payload={"member_name": user.display_name, "role": invite.role.value},
    )
    db.commit()
    return FamilySummary(id=invite.family_id, name=invite.family.name, role=invite.role)
