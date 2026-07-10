import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from .models import ConsentType, FamilyRole, MemberStatus


# --- auth ---

class SignupRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str

    model_config = {"from_attributes": True}


# --- families ---

class FamilyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MemberOut(BaseModel):
    id: uuid.UUID
    user: UserOut
    role: FamilyRole
    status: MemberStatus

    model_config = {"from_attributes": True}


class FamilySummary(BaseModel):
    id: uuid.UUID
    name: str
    role: FamilyRole


class ChildOut(BaseModel):
    id: uuid.UUID
    first_name: str
    birthdate: date

    model_config = {"from_attributes": True}


class FamilyDetail(BaseModel):
    id: uuid.UUID
    name: str
    members: list[MemberOut]
    children: list[ChildOut]


# --- children ---

class ChildCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    birthdate: date
    parental_consent: bool = Field(
        description="Explicit confirmation that the requesting parent/guardian "
        "consents to creating this child's profile."
    )


# --- invites ---

class InviteCreate(BaseModel):
    email: EmailStr
    role: FamilyRole


class InviteOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: FamilyRole
    expires_at: datetime
    accepted_at: datetime | None

    model_config = {"from_attributes": True}


class InviteAccept(BaseModel):
    token: str


class InvitePreview(BaseModel):
    family_name: str
    role: FamilyRole
    invited_by: str
