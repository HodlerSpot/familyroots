import uuid
from typing import Annotated, Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Family, FamilyMember, FamilyRole, MemberStatus, User
from .security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_active_membership(db: Session, family_id: uuid.UUID, user: User) -> FamilyMember:
    """A user may touch a family only through an active membership."""
    membership = (
        db.query(FamilyMember)
        .filter(
            FamilyMember.family_id == family_id,
            FamilyMember.user_id == user.id,
            FamilyMember.status == MemberStatus.active,
        )
        .first()
    )
    if membership is None:
        # 404, not 403: don't reveal that the family exists
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Family not found")
    return membership


def require_guardian_role(membership: FamilyMember) -> None:
    """Child-critical writes require a parent or guardian."""
    if membership.role not in (FamilyRole.parent, FamilyRole.guardian):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only a parent or guardian may do this"
        )


def get_family_or_404(db: Session, family_id: uuid.UUID) -> Family:
    family = db.get(Family, family_id)
    if family is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Family not found")
    return family
