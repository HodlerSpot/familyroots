import uuid

from fastapi import APIRouter, HTTPException, status

from ..deps import (
    CurrentUser,
    DbSession,
    get_child_with_access,
    require_guardian_role,
    require_not_supporter,
)
from ..models import (
    Badge,
    CapsuleStatus,
    FeedEventType,
    Goal,
    GoalCompletion,
    GoalStatus,
    RewardType,
    TimeCapsule,
)
from ..schemas import BadgeOut, GoalComplete, GoalCreate, GoalOut
from ..services.feed import emit
from ..testnet.service import award

router = APIRouter(tags=["goals"])


def _goal_out(goal: Goal, completed_at=None) -> GoalOut:
    out = GoalOut.model_validate(goal)
    out.completed_at = completed_at
    return out


@router.post(
    "/children/{child_id}/goals",
    response_model=GoalOut,
    status_code=status.HTTP_201_CREATED,
)
def create_goal(
    child_id: uuid.UUID, payload: GoalCreate, db: DbSession, user: CurrentUser
) -> GoalOut:
    """Goals are child-critical: parents/guardians only."""
    _, membership = get_child_with_access(db, child_id, user)
    require_guardian_role(membership)
    if payload.reward_type in (RewardType.cash, RewardType.fund_contribution):
        if not payload.reward_amount_cents:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "A money reward needs an amount",
            )
    goal = Goal(
        child_id=child_id,
        created_by=user.id,
        title=payload.title,
        description=payload.description,
        reward_type=payload.reward_type,
        reward_amount_cents=payload.reward_amount_cents,
        due_at=payload.due_at,
    )
    db.add(goal)
    award(db, user.id, "create_goal")  # testnet points; no-op in the family product
    db.commit()
    return _goal_out(goal)


@router.get("/children/{child_id}/goals", response_model=list[GoalOut])
def list_goals(child_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[GoalOut]:
    _, membership = get_child_with_access(db, child_id, user)
    require_not_supporter(membership)
    rows = (
        db.query(Goal, GoalCompletion)
        .outerjoin(GoalCompletion, GoalCompletion.goal_id == Goal.id)
        .filter(Goal.child_id == child_id, Goal.status != GoalStatus.archived)
        .order_by(Goal.created_at.desc())
        .all()
    )
    return [_goal_out(g, c.completed_at if c else None) for g, c in rows]


@router.post("/goals/{goal_id}/complete", response_model=GoalOut)
def complete_goal(
    goal_id: uuid.UUID, payload: GoalComplete, db: DbSession, user: CurrentUser
) -> GoalOut:
    """Completion is verified by a parent/guardian. It never writes the fund
    ledger — money rewards route the parent into the real payment flow, so
    the ledger only ever holds settled money."""
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal not found")
    child, membership = get_child_with_access(db, goal.child_id, user)
    require_guardian_role(membership)
    if goal.status != GoalStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "This goal is already completed")

    goal.status = GoalStatus.completed
    completion = GoalCompletion(goal_id=goal.id, verified_by=user.id, notes=payload.notes)
    db.add(completion)

    if goal.reward_type == RewardType.badge:
        db.add(Badge(child_id=child.id, label=goal.title, source_goal_id=goal.id))

    db.flush()
    emit(
        db,
        family_id=child.family_id,
        actor_user_id=user.id,
        type=FeedEventType.achievement,
        child_id=child.id,
        payload={
            "goal_id": str(goal.id),
            "title": goal.title,
            "child_name": child.first_name,
            "reward_type": goal.reward_type.value,
        },
    )

    # A goal-linked time capsule unlocks the moment its goal is achieved.
    from .capsules import _release

    linked_capsules = (
        db.query(TimeCapsule)
        .filter(
            TimeCapsule.release_goal_id == goal.id,
            TimeCapsule.status == CapsuleStatus.sealed,
        )
        .all()
    )
    for capsule in linked_capsules:
        _release(db, capsule, child)

    db.commit()
    return _goal_out(goal, completion.completed_at)


@router.get("/children/{child_id}/badges", response_model=list[BadgeOut])
def list_badges(child_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[BadgeOut]:
    _, membership = get_child_with_access(db, child_id, user)
    require_not_supporter(membership)
    badges = (
        db.query(Badge)
        .filter(Badge.child_id == child_id)
        .order_by(Badge.awarded_at.desc())
        .all()
    )
    return [BadgeOut.model_validate(b) for b in badges]
