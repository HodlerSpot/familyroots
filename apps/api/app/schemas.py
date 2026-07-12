import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from .security import validate_password_complexity

from .models import (
    CapsuleStatus,
    CapsuleType,
    ConsentType,
    ContributionStatus,
    FamilyRole,
    FeedEventType,
    GoalStatus,
    LegacyType,
    MediaStatus,
    MemberStatus,
    ReleaseCondition,
    RewardType,
    UserRole,
    VaultItemType,
)


# --- auth ---

class SignupRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(max_length=128)

    _pw = field_validator("password")(validate_password_complexity)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(max_length=128)

    _pw = field_validator("new_password")(validate_password_complexity)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(max_length=128)

    _pw = field_validator("new_password")(validate_password_complexity)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    role: UserRole = UserRole.user

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


# --- media & vault ---

class MediaCreate(BaseModel):
    content_type: str = Field(pattern=r"^(image|video|audio)/[\w.+-]+$")


class MediaUploadTicket(BaseModel):
    media_id: uuid.UUID
    upload_url: str


class VaultItemCreate(BaseModel):
    type: VaultItemType
    title: str = Field(min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=5000)
    media_id: uuid.UUID | None = None


class VaultItemOut(BaseModel):
    id: uuid.UUID
    type: VaultItemType
    title: str
    body: str | None
    media_id: uuid.UUID | None
    media_content_type: str | None = None
    created_by_name: str
    created_at: datetime


class MilestoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    media_id: uuid.UUID | None = None


# --- feed ---

class FeedEventOut(BaseModel):
    id: uuid.UUID
    type: FeedEventType
    child_id: uuid.UUID | None
    actor_name: str
    payload: dict
    created_at: datetime


# --- goals & badges ---

class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    reward_type: RewardType
    reward_amount_cents: int | None = Field(default=None, ge=0, le=1_000_000_00)
    due_at: datetime | None = None


class GoalOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    reward_type: RewardType
    reward_amount_cents: int | None
    currency: str
    status: GoalStatus
    due_at: datetime | None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class GoalComplete(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


class BadgeOut(BaseModel):
    id: uuid.UUID
    label: str
    icon: str
    awarded_at: datetime

    model_config = {"from_attributes": True}


# --- contributions & fund ---

class ContributionCreate(BaseModel):
    amount_cents: int = Field(ge=100, le=10_000_00, description="1.00 to 10,000.00")
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    message: str | None = Field(default=None, max_length=2000)
    media_id: uuid.UUID | None = None
    trigger_feed_event_id: uuid.UUID | None = None


class ContributionOut(BaseModel):
    id: uuid.UUID
    amount_cents: int
    currency: str
    fee_cents: int
    message: str | None
    status: ContributionStatus
    created_at: datetime
    # Stripe mode only, returned once at creation for Stripe Elements
    client_secret: str | None = None

    model_config = {"from_attributes": True}


class LedgerEntryOut(BaseModel):
    id: uuid.UUID
    amount_cents: int
    entry_type: str
    contributor_name: str | None
    message: str | None
    created_at: datetime


class FundOut(BaseModel):
    child_id: uuid.UUID
    currency: str
    balance_cents: int
    entries: list[LedgerEntryOut]


# --- time capsules ---

class CapsuleCreate(BaseModel):
    type: CapsuleType
    body: str | None = Field(default=None, max_length=20_000)
    media_id: uuid.UUID | None = None
    release_condition: ReleaseCondition
    release_age: int | None = Field(default=None, ge=1, le=120)
    release_date: date | None = None
    release_milestone: str | None = Field(default=None, max_length=200)


class CapsuleOut(BaseModel):
    """Sealed capsules from other people: body/media/media_content_type are None."""

    id: uuid.UUID
    type: CapsuleType
    status: CapsuleStatus
    release_condition: ReleaseCondition
    release_age: int | None
    release_date: date | None
    release_milestone: str | None
    created_by_name: str
    is_mine: bool
    body: str | None = None
    media_id: uuid.UUID | None = None
    media_content_type: str | None = None
    released_at: datetime | None = None
    created_at: datetime


# --- legacy archive ---

class LegacyCreate(BaseModel):
    type: LegacyType
    title: str = Field(min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=20_000)
    media_id: uuid.UUID | None = None


class LegacyOut(BaseModel):
    id: uuid.UUID
    type: LegacyType
    title: str
    body: str | None
    media_id: uuid.UUID | None
    media_content_type: str | None
    created_by_name: str
    created_at: datetime
