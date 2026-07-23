import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from .push_targets import validate_push_endpoint
from .security import validate_password_complexity

from .models import (
    CapsuleStatus,
    CapsuleType,
    ConsentType,
    ContributionStatus,
    FamilyRole,
    FeedEventType,
    FundAccountStatus,
    GoalStatus,
    LegacyType,
    MediaStatus,
    MemberStatus,
    ReactionTargetType,
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
    # "Stay logged in": unticked by default (safe on shared computers). True
    # issues a long remember_me_ttl_days session instead of the 30-min default.
    remember_me: bool = False


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


class StepUpRequest(BaseModel):
    """Re-authentication for a destructive/irreversible action (account, child,
    or family erasure). The caller re-supplies their current password server-side
    so a stolen live session alone cannot trigger an erasure."""

    password: str = Field(max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # Session lifetime; lets the web client schedule its silent refresh (mirrors
    # MediaTokenResponse.expires_in_seconds). Omitted where not applicable.
    expires_in_seconds: int | None = None


class MediaTokenResponse(BaseModel):
    """Short-lived, media-only token the client appends to <img>/<video> URLs
    (?token=...). Valid solely on GET /media/{id} — never a session credential."""

    media_token: str
    expires_in_seconds: int


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    role: UserRole = UserRole.user
    avatar_media_id: uuid.UUID | None = None

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
    # Derived server-side; the list carries the badge only — no billing detail.
    plan: Literal["free", "premium"] = "free"


class ChildOut(BaseModel):
    id: uuid.UUID
    first_name: str
    # Null for supporters: a child's date of birth is sensitive PII they don't need.
    birthdate: date | None = None
    avatar_media_id: uuid.UUID | None = None
    avatar_content_type: str | None = None
    # Estimated "meaningful time preserved" for this child (Future Gifts).
    # Null for supporters — it aggregates content they can't see (capsules etc.).
    future_gifts_seconds: int | None = None

    model_config = {"from_attributes": True}


class FamilyDetail(BaseModel):
    id: uuid.UUID
    name: str
    members: list[MemberOut]
    children: list[ChildOut]
    plan: Literal["free", "premium"] = "free"
    premium_until: datetime | None = None
    capabilities: list[str] = []


# --- children ---

class ChildCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    birthdate: date
    parental_consent: bool = Field(
        description="Explicit confirmation that the requesting parent/guardian "
        "consents to creating this child's profile."
    )


class ChildAvatarSet(BaseModel):
    media_id: uuid.UUID


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
    visible_to_supporters: bool = False
    created_by_name: str
    created_at: datetime


class VaultItemVisibilityUpdate(BaseModel):
    visible: bool


class MilestoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    media_id: uuid.UUID | None = None


# --- reactions & comments ---

class ReactionSummary(BaseModel):
    emoji: str
    count: int
    reacted: bool


class ReactionSummaryOut(BaseModel):
    reactions: list[ReactionSummary]


class ReactionToggle(BaseModel):
    target_type: ReactionTargetType
    target_id: uuid.UUID
    emoji: str


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class CommentOut(BaseModel):
    id: uuid.UUID
    author_name: str
    author_user_id: uuid.UUID
    body: str
    created_at: datetime
    reactions: list[ReactionSummary] = []
    can_delete: bool = False


# --- feed ---

class FeedEventOut(BaseModel):
    id: uuid.UUID
    type: FeedEventType
    child_id: uuid.UUID | None
    actor_name: str
    payload: dict
    created_at: datetime
    reactions: list[ReactionSummary] = []
    comment_count: int = 0


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
    account_status: FundAccountStatus
    setup_by_name: str | None
    # Number of gifts that still stand: contribution entries minus fully-refunded
    # ones. A full refund drops the gift (-1); a partial refund leaves it. Derived
    # server-side because it needs each contribution's refund status, which the
    # ledger `entries` (a raw transaction history, refunds included) doesn't carry.
    gift_count: int
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
    release_goal_id: uuid.UUID | None = None


class CapsuleOut(BaseModel):
    """Sealed capsules from other people: body/media/media_content_type are None."""

    id: uuid.UUID
    type: CapsuleType
    status: CapsuleStatus
    release_condition: ReleaseCondition
    release_age: int | None
    release_date: date | None
    release_milestone: str | None
    release_goal_id: uuid.UUID | None = None
    release_goal_title: str | None = None
    created_by_name: str
    is_mine: bool
    release_votes: int = 0
    i_voted: bool = False
    can_vote: bool = False
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


# --- FutureRoots Premium ---

class PremiumCheckoutIn(BaseModel):
    plan: Literal["monthly", "annual"]


class GiftCheckoutIn(BaseModel):
    message: str | None = Field(default=None, max_length=500)


class CheckoutSessionOut(BaseModel):
    checkout_url: str          # browser navigates here (Stripe-hosted, or the
                               # success URL directly on the local backend)


class PremiumSubscriptionOut(BaseModel):
    plan: Literal["monthly", "annual"]
    status: Literal["active", "past_due", "canceled"]
    current_period_end: datetime
    cancel_at_period_end: bool
    owner_name: str
    is_owner: bool             # viewer == owner (enables the Portal button)


class PremiumGrantOut(BaseModel):
    gifter_name: str
    starts_at: datetime
    ends_at: datetime
    message: str | None


class PremiumStatusOut(BaseModel):
    plan: Literal["free", "premium"]
    premium_until: datetime | None
    capabilities: list[str]
    can_manage: bool                              # viewer is an active parent
    can_gift: bool                                # viewer is an active non-parent
    subscription: PremiumSubscriptionOut | None   # PARENTS ONLY (billing trouble is private)
    grants: list[PremiumGrantOut]                 # non-supporter members; [] for supporters


class PremiumPortalOut(BaseModel):
    portal_url: str


class PremiumSyncIn(BaseModel):
    session_id: str | None = None


# --- me: notification preferences & contributions ---

class NotificationPrefs(BaseModel):
    """The full per-user switch matrix: eleven kinds across Email + Push (22
    booleans). PUT accepts all 22; push_public_key is read-only (echoed on
    GET so the browser can subscribe without an Amplify env var) and ignored
    on input."""

    # original four email kinds
    email_new_member: bool
    email_milestone: bool
    email_memory: bool
    email_legacy: bool
    # push mirrors of the original four
    push_new_member: bool
    push_milestone: bool
    push_memory: bool
    push_legacy: bool
    # six new kinds, both channels
    email_call_live: bool
    push_call_live: bool
    email_contribution: bool
    push_contribution: bool
    email_fund_activated: bool
    push_fund_activated: bool
    email_capsule_sealed: bool
    push_capsule_sealed: bool
    email_capsule_released: bool
    push_capsule_released: bool
    email_announcements: bool
    push_announcements: bool
    # monthly memory request
    email_memory_request: bool
    push_memory_request: bool
    # read-only: the server's VAPID public key ("" ⇒ push feature is dark)
    push_public_key: str = ""


class MemoryPromptChild(BaseModel):
    """The child-of-the-month named in the card CTA (no sensitive PII)."""

    id: uuid.UUID
    first_name: str


class MemoryPromptOut(BaseModel):
    """The monthly Memory Request card state, computed on read.
    ``satisfied`` flips true once the caller has added any memory this month
    (the card auto-hides). Null is returned for supporters or childless
    families — see GET /families/{id}/memory-prompt."""

    period: str  # "YYYY-MM"
    child: MemoryPromptChild
    satisfied: bool


class PushSubscribeIn(BaseModel):
    """A browser PushSubscription, flattened. The client maps
    subscription.toJSON(): endpoint + keys.p256dh + keys.auth."""

    endpoint: str = Field(min_length=1, max_length=500)
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)
    ua_label: str | None = Field(default=None, max_length=200)

    @field_validator("endpoint")
    @classmethod
    def _endpoint_is_a_push_service(cls, v: str) -> str:
        # Shape guard against SSRF: the stored endpoint is later POSTed to from
        # inside the VPC. Reject anything but a known https push origin.
        return validate_push_endpoint(v)


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=500)


class InboxItemOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    url: str | None = None
    family_id: uuid.UUID | None = None
    read_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class InboxPage(BaseModel):
    items: list[InboxItemOut]
    # Opaque keyset cursor ("<iso>|<id>"); pass it back as ?cursor= for the
    # next page. None means there are no older items.
    next_cursor: str | None = None


class UnreadCountOut(BaseModel):
    count: int


class MyContributionOut(BaseModel):
    id: uuid.UUID
    child_name: str
    family_name: str
    amount_cents: int
    currency: str
    fee_cents: int
    status: ContributionStatus
    refunded_cents: int
    message: str | None
    created_at: datetime


# --- member avatars ---

class AvatarSet(BaseModel):
    media_id: uuid.UUID


# --- family video call ---

class CallParticipantOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    agora_uid: int
    avatar_media_id: uuid.UUID | None = None
    is_you: bool = False


class CallChildPresenceOut(BaseModel):
    child_id: uuid.UUID
    first_name: str
    avatar_media_id: uuid.UUID | None = None
    marked_by: uuid.UUID


class PlannedCallOut(BaseModel):
    id: uuid.UUID
    scheduled_for: datetime
    note: str | None = None
    set_by: uuid.UUID
    set_by_name: str
    updated_at: datetime


class CallStateOut(BaseModel):
    active: bool
    call_id: uuid.UUID | None = None
    channel_name: str | None = None
    started_at: datetime | None = None
    participants: list[CallParticipantOut] = []
    children_present: list[CallChildPresenceOut] = []
    planned_call: PlannedCallOut | None = None


class CallJoinOut(BaseModel):
    """The join / token responses carry the App ID (public) and a short-lived
    RTC token. The App Certificate is NEVER part of any response."""

    app_id: str
    channel_name: str
    token: str
    agora_uid: int
    expires_at: int
    call: CallStateOut


class CallTokenOut(BaseModel):
    app_id: str
    channel_name: str
    token: str
    agora_uid: int
    expires_at: int


class PlannedCallSet(BaseModel):
    scheduled_for: datetime
    note: str | None = Field(default=None, max_length=200)


class ChildrenPresenceSet(BaseModel):
    child_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


# --- future predictions ---

class CloudWordOut(BaseModel):
    word: str
    weight: int


class PredictionOut(BaseModel):
    id: uuid.UUID
    body: str
    author_name: str
    is_mine: bool
    can_delete: bool  # mine, or the viewer is a parent/guardian of the child
    created_at: datetime


class OpenRoundOut(BaseModel):
    id: uuid.UUID
    year: int | None                       # seals_on.year; None for supporters (date leak)
    seals_on: date | None                  # ALWAYS None for supporters
    cloud: list[CloudWordOut]              # server-tokenized; identical for everyone
    predictions: list[PredictionOut]       # newest first — the list panel
    my_prediction_ids: list[uuid.UUID]     # the caller's own, for edit/delete + slots
    max_per_member: int                    # 3 — the per-round cap


class PredictionGameOut(BaseModel):
    child_first_name: str
    round: OpenRoundOut | None             # None: game complete (family) / idle (supporter)
    completed: bool                        # true only for family once released; false for supporters


class PredictionCreate(BaseModel):
    body: str

    @field_validator("body")
    @classmethod
    def _trim(cls, value: str) -> str:
        value = (value or "").strip()
        if not 2 <= len(value) <= 120:
            raise ValueError("A prediction is 2 to 120 characters.")
        return value


class SealedRoundOut(BaseModel):
    id: uuid.UUID
    year: int
    sealed_at: datetime
    opens_on: date                         # the 18th birthday (family-facing; fine)


class BookPredictionOut(BaseModel):
    body: str
    author_name: str
    created_at: datetime


class BookChapterOut(BaseModel):
    round_id: uuid.UUID
    year: int
    age: int                               # ordinal birthday it sealed on
    cloud_media_id: uuid.UUID | None
    media_content_type: str | None         # "image/png"
    predictions: list[BookPredictionOut]


class PredictionBookOut(BaseModel):
    child_first_name: str
    chapters: list[BookChapterOut]         # chronological; skipped years silently absent
