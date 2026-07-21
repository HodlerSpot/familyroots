import uuid

from fastapi import APIRouter, HTTPException, status

from ..deps import (
    CurrentUser,
    DbSession,
    get_active_membership,
    is_supporter,
    require_guardian_role,
)
from ..models import (
    Child,
    ChildRelationship,
    ConsentRecord,
    ConsentType,
    FamilyMember,
    MediaObject,
    MemberStatus,
)
from ..schemas import ChildCreate, ChildOut
from ..services.future_gifts import (
    future_gifts_seconds_for_child,
    future_gifts_seconds_for_children,
)
from ..services.predictions import ensure_open_round
from ..testnet.service import award

router = APIRouter(prefix="/families/{family_id}/children", tags=["children"])


def child_out(
    db,
    child: Child,
    *,
    hide_birthdate: bool = False,
    future_gifts_seconds: int | None = None,
) -> ChildOut:
    """Serialize a child, resolving the avatar's content type for the client.
    Supporters (hide_birthdate=True) never receive the child's date of birth,
    and callers pass future_gifts_seconds=None for them so the Future Gifts
    estimate (which aggregates content supporters can't see) never leaks."""
    content_type = None
    if child.avatar_media_id is not None:
        media = db.get(MediaObject, child.avatar_media_id)
        content_type = media.content_type if media else None
    return ChildOut(
        id=child.id,
        first_name=child.first_name,
        birthdate=None if hide_birthdate else child.birthdate,
        avatar_media_id=child.avatar_media_id,
        avatar_content_type=content_type,
        future_gifts_seconds=future_gifts_seconds,
    )


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

    # Open the child's first Future Predictions round (under-18 with a
    # birthdate). Silent — no feed event; discovery is the child-page card.
    ensure_open_round(db, child)

    award(db, user.id, "add_child")  # testnet points; no-op in the family product
    db.commit()
    # A brand-new child has no content yet, so this is 0 — but compute it so the
    # created payload carries the same field the list/detail views return. The
    # creator is a guardian (not a supporter), so the estimate is always shown.
    return child_out(
        db, child, future_gifts_seconds=future_gifts_seconds_for_child(db, child.id)
    )


@router.get("", response_model=list[ChildOut])
def list_children(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> list[ChildOut]:
    membership = get_active_membership(db, family_id, user)
    hide = is_supporter(membership.role)
    children = db.query(Child).filter(Child.family_id == family_id).all()
    # Precompute Future Gifts once for all children (no N+1); skip entirely for
    # supporters, who must not see the estimate.
    gifts = (
        {}
        if hide
        else future_gifts_seconds_for_children(db, [c.id for c in children])
    )
    return [
        child_out(db, c, hide_birthdate=hide, future_gifts_seconds=gifts.get(c.id))
        for c in children
    ]
