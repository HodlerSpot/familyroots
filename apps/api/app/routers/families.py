import uuid

from fastapi import APIRouter, status

from ..deps import CurrentUser, DbSession, get_active_membership, is_supporter
from ..models import Family, FamilyMember, FamilyRole, MemberStatus
from ..schemas import FamilyCreate, FamilyDetail, FamilySummary
from ..services.entitlements import (
    family_capabilities,
    plans_for_families,
    premium_until,
)
from ..services.premium import run_lazy_lifecycle
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


@router.get("/{family_id}", response_model=FamilyDetail)
def family_detail(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> FamilyDetail:
    membership = get_active_membership(db, family_id, user)
    # Request-driven lifecycle (gift-ending-soon / gift-only-lapse emails) —
    # the deliberate no-cron substitute; send-once guarded by premium_email_log.
    run_lazy_lifecycle(db, family_id)
    hide = is_supporter(membership.role)
    family = db.get(Family, family_id)
    active_members = [m for m in family.members if m.status == MemberStatus.active]
    return FamilyDetail(
        id=family.id,
        name=family.name,
        members=active_members,
        children=[child_out(db, c, hide_birthdate=hide) for c in family.children],
        plan="premium" if plans_for_families(db, [family_id])[family_id] else "free",
        premium_until=premium_until(db, family_id),
        capabilities=family_capabilities(db, family_id),
    )
