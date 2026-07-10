import uuid

from fastapi import APIRouter, HTTPException, status

from ..deps import CurrentUser, DbSession, get_active_membership, require_guardian_role
from ..models import (
    Child,
    ChildRelationship,
    ConsentRecord,
    ConsentType,
    FamilyMember,
    MemberStatus,
)
from ..schemas import ChildCreate, ChildOut

router = APIRouter(prefix="/families/{family_id}/children", tags=["children"])


@router.post("", response_model=ChildOut, status_code=status.HTTP_201_CREATED)
def add_child(
    family_id: uuid.UUID, payload: ChildCreate, db: DbSession, user: CurrentUser
) -> ChildOut:
    membership = get_active_membership(db, family_id, user)
    require_guardian_role(membership)
    if not payload.parental_consent:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Parental consent is required to create a child profile",
        )

    child = Child(
        family_id=family_id,
        first_name=payload.first_name,
        birthdate=payload.birthdate,
        created_by=user.id,
    )
    db.add(child)
    db.flush()

    # Consent is recorded data, not an assumption (COPPA/GDPR/PIPEDA)
    db.add(
        ConsentRecord(
            child_id=child.id,
            granted_by=user.id,
            consent_type=ConsentType.profile_creation,
        )
    )

    # Every active family member gets an explicit Family Graph edge to the child
    active_members = (
        db.query(FamilyMember)
        .filter(
            FamilyMember.family_id == family_id,
            FamilyMember.status == MemberStatus.active,
        )
        .all()
    )
    for member in active_members:
        db.add(
            ChildRelationship(
                child_id=child.id,
                user_id=member.user_id,
                relationship_type=member.role,
            )
        )

    db.commit()
    return ChildOut.model_validate(child)


@router.get("", response_model=list[ChildOut])
def list_children(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[ChildOut]:
    get_active_membership(db, family_id, user)
    children = db.query(Child).filter(Child.family_id == family_id).all()
    return [ChildOut.model_validate(c) for c in children]
