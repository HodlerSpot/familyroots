import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, status

from ..config import settings
from ..deps import CurrentUser, DbSession, get_child_with_access
from ..models import (
    CapsuleStatus,
    Child,
    FamilyMember,
    FamilyRole,
    FeedEventType,
    MediaObject,
    MediaStatus,
    MemberStatus,
    ReleaseCondition,
    TimeCapsule,
    User,
    utcnow,
)
from ..schemas import CapsuleCreate, CapsuleOut
from ..services.email import get_email_sender
from ..services.email_templates import render_email
from ..services.feed import emit

router = APIRouter(tags=["capsules"])


def _age_on(birthdate: date, on: date) -> int:
    return on.year - birthdate.year - ((on.month, on.day) < (birthdate.month, birthdate.day))


def _capsule_out(capsule: TimeCapsule, viewer_id: uuid.UUID) -> CapsuleOut:
    is_mine = capsule.created_by == viewer_id
    revealed = is_mine or capsule.status == CapsuleStatus.released
    return CapsuleOut(
        id=capsule.id,
        type=capsule.type,
        status=capsule.status,
        release_condition=capsule.release_condition,
        release_age=capsule.release_age,
        release_date=capsule.release_date,
        release_milestone=capsule.release_milestone,
        created_by_name=capsule.author.display_name,
        is_mine=is_mine,
        body=capsule.body if revealed else None,
        media_id=capsule.media_id if revealed else None,
        media_content_type=(
            capsule.media.content_type if revealed and capsule.media else None
        ),
        released_at=capsule.released_at,
        created_at=capsule.created_at,
    )


def _release(db, capsule: TimeCapsule, child: Child) -> None:
    """Open a capsule: status flip + feed event + tell the parents."""
    capsule.status = CapsuleStatus.released
    capsule.released_at = utcnow()
    emit(
        db,
        family_id=child.family_id,
        actor_user_id=capsule.created_by,
        type=FeedEventType.capsule_released,
        child_id=child.id,
        payload={
            "capsule_id": str(capsule.id),
            "child_name": child.first_name,
            "created_by_name": capsule.author.display_name,
            "capsule_type": capsule.type.value,
        },
    )
    parents = (
        db.query(User)
        .join(FamilyMember, FamilyMember.user_id == User.id)
        .filter(
            FamilyMember.family_id == child.family_id,
            FamilyMember.status == MemberStatus.active,
            FamilyMember.role.in_([FamilyRole.parent, FamilyRole.guardian]),
        )
        .all()
    )
    sender = get_email_sender()
    url = f"{settings.web_base_url}/family/{child.family_id}/child/{child.id}"
    for parent in parents:
        sender.send(
            to=parent.email,
            subject=f"A time capsule for {child.first_name} just opened",
            body=(
                f"Hi {parent.display_name},\n\n"
                f"A moment years in the making: the time capsule "
                f"{capsule.author.display_name} sealed for {child.first_name} has "
                f"opened today.\n\n"
                f"Open it together: {url}\n\n"
                f"With warmth,\nThe FutureRoots team"
            ),
            html=render_email(
                preheader=(
                    f"The time capsule {capsule.author.display_name} sealed for "
                    f"{child.first_name} has opened today."
                ),
                greeting=f"Hi {parent.display_name},",
                paragraphs=[
                    f"A moment years in the making: the time capsule "
                    f"{capsule.author.display_name} sealed for {child.first_name} "
                    f"has opened today."
                ],
                cta_label="Open it together",
                cta_url=url,
            ),
        )


def release_due_capsules(db, child: Child) -> None:
    """Lazy scheduler: open any sealed age/date capsules that have come due.
    (Prod grows an EventBridge cron doing the same sweep — same function.)"""
    today = utcnow().date()
    due = []
    for capsule in (
        db.query(TimeCapsule)
        .filter(
            TimeCapsule.child_id == child.id,
            TimeCapsule.status == CapsuleStatus.sealed,
        )
        .all()
    ):
        if capsule.release_condition == ReleaseCondition.date:
            if capsule.release_date is not None and capsule.release_date <= today:
                due.append(capsule)
        elif capsule.release_condition == ReleaseCondition.age:
            if (
                capsule.release_age is not None
                and _age_on(child.birthdate, today) >= capsule.release_age
            ):
                due.append(capsule)
    for capsule in due:
        _release(db, capsule, child)
    if due:
        db.commit()


@router.post(
    "/children/{child_id}/capsules",
    response_model=CapsuleOut,
    status_code=status.HTTP_201_CREATED,
)
def create_capsule(
    child_id: uuid.UUID, payload: CapsuleCreate, db: DbSession, user: CurrentUser
) -> CapsuleOut:
    """Any family member can seal a capsule — grandparents leaving letters for
    the future is the heart of this feature."""
    child, _ = get_child_with_access(db, child_id, user)

    condition_value = {
        ReleaseCondition.age: payload.release_age,
        ReleaseCondition.date: payload.release_date,
        ReleaseCondition.milestone: payload.release_milestone,
    }[payload.release_condition]
    if condition_value is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"A {payload.release_condition.value}-released capsule needs its "
            f"release_{payload.release_condition.value}",
        )
    if not payload.body and not payload.media_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "A capsule needs a letter or a recording"
        )
    if payload.media_id is not None:
        media = db.get(MediaObject, payload.media_id)
        if media is None or media.child_id != child_id or media.status != MediaStatus.uploaded:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Media not ready")

    capsule = TimeCapsule(
        child_id=child_id,
        created_by=user.id,
        type=payload.type,
        body=payload.body,
        media_id=payload.media_id,
        release_condition=payload.release_condition,
        release_age=payload.release_age,
        release_date=payload.release_date,
        release_milestone=payload.release_milestone,
    )
    db.add(capsule)
    db.flush()
    emit(
        db,
        family_id=child.family_id,
        actor_user_id=user.id,
        type=FeedEventType.capsule_created,
        child_id=child_id,
        payload={
            "capsule_id": str(capsule.id),
            "child_name": child.first_name,
            "created_by_name": user.display_name,
            "release_condition": capsule.release_condition.value,
            "release_age": capsule.release_age,
        },
    )
    db.commit()
    return _capsule_out(capsule, user.id)


@router.get("/children/{child_id}/capsules", response_model=list[CapsuleOut])
def list_capsules(child_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[CapsuleOut]:
    child, _ = get_child_with_access(db, child_id, user)
    release_due_capsules(db, child)
    capsules = (
        db.query(TimeCapsule)
        .filter(TimeCapsule.child_id == child_id)
        .order_by(TimeCapsule.created_at.desc())
        .all()
    )
    return [_capsule_out(c, user.id) for c in capsules]


@router.post("/capsules/{capsule_id}/release", response_model=CapsuleOut)
def release_capsule(capsule_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CapsuleOut:
    """Milestone-conditioned capsules open when the moment arrives — the
    creator or a parent/guardian declares it."""
    capsule = db.get(TimeCapsule, capsule_id)
    if capsule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Capsule not found")
    child, membership = get_child_with_access(db, capsule.child_id, user)
    if capsule.status == CapsuleStatus.released:
        raise HTTPException(status.HTTP_409_CONFLICT, "This capsule is already open")
    if capsule.release_condition != ReleaseCondition.milestone:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This capsule opens on its own when the time comes",
        )
    is_creator = capsule.created_by == user.id
    is_guardian = membership.role in (FamilyRole.parent, FamilyRole.guardian)
    if not (is_creator or is_guardian):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only its creator or a parent can open this capsule"
        )
    _release(db, capsule, child)
    db.commit()
    return _capsule_out(capsule, user.id)
