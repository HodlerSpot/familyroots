import uuid

from fastapi import APIRouter, status

from ..deps import CurrentUser, DbSession, get_active_membership
from ..models import Family, FamilyMember, FamilyRole, MemberStatus
from ..schemas import FamilyCreate, FamilyDetail, FamilySummary
from ..testnet.service import award

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
    return FamilySummary(id=family.id, name=family.name, role=FamilyRole.parent)


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
    return [FamilySummary(id=f.id, name=f.name, role=m.role) for f, m in rows]


@router.get("/{family_id}", response_model=FamilyDetail)
def family_detail(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> FamilyDetail:
    get_active_membership(db, family_id, user)
    family = db.get(Family, family_id)
    active_members = [m for m in family.members if m.status == MemberStatus.active]
    return FamilyDetail(
        id=family.id,
        name=family.name,
        members=active_members,
        children=family.children,
    )
