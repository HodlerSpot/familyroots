import uuid

from fastapi import APIRouter, HTTPException, status

from ..deps import (
    CurrentUser,
    DbSession,
    get_active_membership,
    is_supporter,
    require_parent_role,
)
from ..models import Family, FamilyMember, FamilyRole, FeedEventType, MemberStatus, utcnow
from ..schemas import (
    FamilyCreate,
    FamilyDetail,
    FamilySummary,
    MemoryPromptChild,
    MemoryPromptOut,
)
from ..services.entitlements import (
    family_capabilities,
    plans_for_families,
    premium_until,
)
from ..services.feed import emit
from ..services.future_gifts import future_gifts_seconds_for_children
from ..services.memory_prompts import (
    active_children,
    child_of_the_month,
    has_added_memory_this_month,
    period_for,
)
from ..services.premium import handle_owner_departure, run_lazy_lifecycle
from ..testnet.service import award
from .children import child_out

router = APIRouter(prefix="/families", tags=["families"])


@router.post("", response_model=FamilySummary, status_code=status.HTTP_201_CREATED)
def create_family(payload: FamilyCreate, db: DbSession, user: CurrentUser) -> FamilySummary:
    family = Family(name=payload.name, created_by=user.id)
    db.add(family)
    db.flush()
    db.add(
        FamilyMember(
            family_id=family.id,
            user_id=user.id,
            role=FamilyRole.parent,
            status=MemberStatus.active,
        )
    )
    award(db, user.id, "create_family")  # testnet points; no-op in the family product
    db.commit()
    return FamilySummary(id=family.id, name=family.name, role=FamilyRole.parent, plan="free")


@router.get("", response_model=list[FamilySummary])
def my_families(db: DbSession, user: CurrentUser) -> list[FamilySummary]:
    rows = (
        db.query(Family, FamilyMember)
        .join(FamilyMember, FamilyMember.family_id == Family.id)
        .filter(
            FamilyMember.user_id == user.id,
            FamilyMember.status == MemberStatus.active,
        )
        .all()
    )
    # One grouped entitlement query for the whole list (no N+1); the list
    # carries the badge only — billing detail stays on the premium endpoints.
    plans = plans_for_families(db, [f.id for f, _ in rows])
    return [
        FamilySummary(
            id=f.id,
            name=f.name,
            role=m.role,
            plan="premium" if plans.get(f.id) else "free",
        )
        for f, m in rows
    ]


def _active_parent_count(db, family_id: uuid.UUID) -> int:
    return (
        db.query(FamilyMember)
        .filter(
            FamilyMember.family_id == family_id,
            FamilyMember.status == MemberStatus.active,
            FamilyMember.role == FamilyRole.parent,
        )
        .count()
    )


def _depart(db, membership: FamilyMember, actor_user_id: uuid.UUID) -> None:
    """Shared exit path for leave and remove.

    Marks the membership removed, then (after the flush, so the departing
    member is out of every recipient query) lets the Premium hook cancel the
    family's subscription at period end when the leaver owns it, and finally
    tells the feed. Nothing the member authored is touched: memories,
    contributions, capsules, and legacy items stay with the family — they are
    family history, not personal property that leaves with them.
    """
    membership.status = MemberStatus.removed
    db.flush()
    # A person shouldn't silently keep paying for a family they're no longer
    # in (spec §7.4): if they own the live subscription, stop auto-renewal at
    # period end and email the remaining parents. No-op for everyone else.
    handle_owner_departure(db, membership.family_id, membership.user_id)
    emit(
        db,
        family_id=membership.family_id,
        actor_user_id=actor_user_id,
        type=FeedEventType.member_left,
        payload={
            "member_name": membership.user.display_name,
            "role": membership.role.value,
        },
    )


@router.post("/{family_id}/members/me/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_family(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    """Any active member may step away from a family.

    Guard: the last active parent can never leave — children must never be
    orphaned inside FutureRoots, and a family always needs at least one
    parent at the helm. Everything the leaver shared stays with the family
    (nothing is deleted), and a parent can re-invite them any time.
    """
    membership = get_active_membership(db, family_id, user)
    if membership.role == FamilyRole.parent and _active_parent_count(db, family_id) <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You're the only parent here, and your family needs you. "
            "Invite another parent first if you'd like to step away.",
        )
    _depart(db, membership, actor_user_id=user.id)
    db.commit()


@router.delete(
    "/{family_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_member(
    family_id: uuid.UUID, user_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> None:
    """A parent may remove another member (including another parent in a
    multi-parent family).

    Not allowed: removing yourself (use the leave endpoint) and removing the
    last active parent. Non-members get a 404, never a 403, so a family's
    existence doesn't leak. Nothing the removed member authored is deleted —
    their memories and contributions remain part of the family's history —
    and they can be re-invited later.
    """
    membership = get_active_membership(db, family_id, user)
    require_parent_role(membership)
    if user_id == user.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "To step away yourself, use Leave this family instead.",
        )
    target = (
        db.query(FamilyMember)
        .filter(
            FamilyMember.family_id == family_id,
            FamilyMember.user_id == user_id,
            FamilyMember.status == MemberStatus.active,
        )
        .first()
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    # Unreachable today (the caller is an active parent and can't target
    # themselves), but kept as an explicit safety net for the invariant.
    if target.role == FamilyRole.parent and _active_parent_count(db, family_id) <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A family always needs at least one parent, so this parent can't be removed.",
        )
    _depart(db, target, actor_user_id=user.id)
    db.commit()


@router.get("/{family_id}", response_model=FamilyDetail)
def family_detail(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> FamilyDetail:
    membership = get_active_membership(db, family_id, user)
    # Request-driven lifecycle (gift-ending-soon / gift-only-lapse emails) —
    # the deliberate no-cron substitute; send-once guarded by premium_email_log.
    run_lazy_lifecycle(db, family_id)
    hide = is_supporter(membership.role)
    family = db.get(Family, family_id)
    active_members = [m for m in family.members if m.status == MemberStatus.active]
    # Precompute Future Gifts once for all children (no N+1); skip for
    # supporters, who must not see the estimate (it aggregates hidden content).
    gifts = (
        {}
        if hide
        else future_gifts_seconds_for_children(db, [c.id for c in family.children])
    )
    return FamilyDetail(
        id=family.id,
        name=family.name,
        members=active_members,
        children=[
            child_out(db, c, hide_birthdate=hide, future_gifts_seconds=gifts.get(c.id))
            for c in family.children
        ],
        plan="premium" if plans_for_families(db, [family_id])[family_id] else "free",
        premium_until=premium_until(db, family_id),
        capabilities=family_capabilities(db, family_id),
    )


@router.get("/{family_id}/memory-prompt", response_model=MemoryPromptOut | None)
def memory_prompt(
    family_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> MemoryPromptOut | None:
    """The monthly Memory Request card, computed on read (no table). Names the
    family's rotating child-of-the-month and whether the caller has already
    added a memory this month (the card auto-hides once satisfied). Returns
    null for supporters (they cannot add memories) and childless families —
    the same deterministic rule the daily sweep uses, so card and bell agree."""
    membership = get_active_membership(db, family_id, user)
    if is_supporter(membership.role):
        return None
    now = utcnow()
    child = child_of_the_month(active_children(db, family_id), now)
    if child is None:
        return None
    return MemoryPromptOut(
        period=period_for(now),
        child=MemoryPromptChild(id=child.id, first_name=child.first_name),
        satisfied=has_added_memory_this_month(db, family_id, user.id, now),
    )
