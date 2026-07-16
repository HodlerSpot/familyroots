import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FamilyRole(str, enum.Enum):
    parent = "parent"
    grandparent = "grandparent"
    relative = "relative"
    guardian = "guardian"
    # A trusted non-family adult (coach, mentor, friend, neighbour). Scoped
    # down: no legacy archive, no fund figures, no time capsules, no goals —
    # sees only memories/milestones explicitly shared with supporters.
    supporter = "supporter"


# Roles that hold full family trust (can create children, goals, capsules,
# see funds and the legacy archive). Everyone who is not a supporter.
GUARDIAN_ROLES = {
    FamilyRole.parent,
    FamilyRole.grandparent,
    FamilyRole.relative,
    FamilyRole.guardian,
}


class MemberStatus(str, enum.Enum):
    invited = "invited"
    active = "active"
    removed = "removed"


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"  # platform operator; access to the admin command center


class ConsentType(str, enum.Enum):
    profile_creation = "profile_creation"
    media_storage = "media_storage"
    contributions = "contributions"


class MediaStatus(str, enum.Enum):
    pending = "pending"
    uploaded = "uploaded"
    deleted = "deleted"


class VaultItemType(str, enum.Enum):
    photo = "photo"
    video = "video"
    voice = "voice"
    message = "message"
    document = "document"
    achievement = "achievement"


class FeedEventType(str, enum.Enum):
    milestone = "milestone"
    achievement = "achievement"
    contribution = "contribution"
    memory_added = "memory_added"
    capsule_created = "capsule_created"
    capsule_released = "capsule_released"
    member_joined = "member_joined"
    member_left = "member_left"
    premium_activated = "premium_activated"
    premium_gifted = "premium_gifted"


class SubscriptionPlan(str, enum.Enum):
    monthly = "monthly"
    annual = "annual"


class SubscriptionStatus(str, enum.Enum):
    active = "active"        # Stripe: active | trialing (we sell no trials)
    past_due = "past_due"    # Stripe: past_due — Smart Retries window = grace period
    canceled = "canceled"    # Stripe: canceled | unpaid | incomplete_expired


class CapsuleType(str, enum.Enum):
    letter = "letter"
    audio = "audio"
    video = "video"


class ReleaseCondition(str, enum.Enum):
    age = "age"
    date = "date"
    milestone = "milestone"  # "at a life moment" — released by creator or 2 guardians
    goal = "goal"  # unlocks automatically when a linked goal is completed


class ReactionTargetType(str, enum.Enum):
    feed_event = "feed_event"
    comment = "comment"


class CapsuleStatus(str, enum.Enum):
    sealed = "sealed"
    released = "released"


class LegacyType(str, enum.Enum):
    story = "story"
    recipe = "recipe"
    document = "document"
    photo = "photo"
    wisdom = "wisdom"


class RewardType(str, enum.Enum):
    cash = "cash"
    fund_contribution = "fund_contribution"
    badge = "badge"
    privilege = "privilege"


class GoalStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    archived = "archived"


class ContributionStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"


class LedgerEntryType(str, enum.Enum):
    contribution = "contribution"
    goal_reward = "goal_reward"
    adjustment = "adjustment"


class FundAccountStatus(str, enum.Enum):
    """Lifecycle of a child's real Future Fund (Stripe Express) account.
    Contributions are possible only while active."""

    none = "none"                # no connected account yet
    onboarding = "onboarding"    # account created, hosted onboarding unfinished
    active = "active"            # transfers capability active + payouts enabled
    restricted = "restricted"    # Stripe needs more info / paused the account


class CallStatus(str, enum.Enum):
    active = "active"
    ended = "ended"


def role_column() -> Enum:
    return Enum(FamilyRole, native_enum=False, length=20)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=20), default=UserRole.user
    )
    disabled: Mapped[bool] = mapped_column(default=False)  # admin can lock an account out
    # One Stripe Customer per adult user, created lazily on their first checkout
    # (subscribe OR gift). Server-only; never exposed in any API payload.
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )
    # Optional headshot shown on camera-off video-call tiles. Points at a
    # user-scoped media object (MediaObject.user_id == this user).
    avatar_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_objects.id"), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list["FamilyMember"]] = relationship(
        back_populates="user", foreign_keys="FamilyMember.user_id"
    )


class AdminAuditLog(Base):
    """A record of every consequential admin action, for accountability over
    the sensitive data (children, money) the command center exposes."""

    __tablename__ = "admin_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    admin_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(60))  # e.g. bug_verified, role_changed
    target: Mapped[str | None] = mapped_column(String(120), nullable=True)  # e.g. "user:<id>"
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Family(Base):
    __tablename__ = "families"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    max_upload_mb: Mapped[int] = mapped_column(default=10)  # per-family attachment size cap
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    members: Mapped[list["FamilyMember"]] = relationship(back_populates="family")
    children: Mapped[list["Child"]] = relationship(back_populates="family")


class FamilyMember(Base):
    __tablename__ = "family_members"
    __table_args__ = (UniqueConstraint("family_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[FamilyRole] = mapped_column(role_column())
    status: Mapped[MemberStatus] = mapped_column(
        Enum(MemberStatus, native_enum=False, length=20), default=MemberStatus.active
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    family: Mapped[Family] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships", foreign_keys=[user_id])


class FamilyInvite(Base):
    __tablename__ = "family_invites"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[FamilyRole] = mapped_column(role_column())
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    family: Mapped[Family] = relationship()


class Child(Base):
    __tablename__ = "children"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    first_name: Mapped[str] = mapped_column(String(120))
    birthdate: Mapped[date] = mapped_column(Date)
    # Optional headshot; the media object is child-scoped like any vault media.
    avatar_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_objects.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    family: Mapped[Family] = relationship(back_populates="children")
    relationships: Mapped[list["ChildRelationship"]] = relationship(back_populates="child")


class ChildRelationship(Base):
    __tablename__ = "child_relationships"
    __table_args__ = (UniqueConstraint("child_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    relationship_type: Mapped[FamilyRole] = mapped_column("relationship", role_column())

    child: Mapped[Child] = relationship(back_populates="relationships")
    user: Mapped[User] = relationship()


class MediaObject(Base):
    __tablename__ = "media_objects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Media is scoped to exactly one of child (vault, capsules), family
    # (legacy archive), user (member headshots), or tester (testnet bug-report
    # screenshots) so access control always follows that owner.
    child_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("children.id"), nullable=True, index=True
    )
    family_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("families.id"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    tester_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("testers.id"), nullable=True, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(BigInteger, default=0)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[MediaStatus] = mapped_column(
        Enum(MediaStatus, native_enum=False, length=20), default=MediaStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # child_id is one of two FK paths between children and media_objects (the
    # other is children.avatar_media_id), so the join column must be explicit.
    child: Mapped[Child | None] = relationship(foreign_keys=[child_id])


class VaultItem(Base):
    __tablename__ = "vault_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id"), index=True)
    type: Mapped[VaultItemType] = mapped_column(
        Enum(VaultItemType, native_enum=False, length=20)
    )
    media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_objects.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Off by default: supporters (non-family adults) only see items a parent
    # has explicitly shared with them. Any parent can toggle this at any time.
    visible_to_supporters: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    child: Mapped[Child] = relationship()
    media: Mapped[MediaObject | None] = relationship()
    author: Mapped[User] = relationship()


class FeedEvent(Base):
    __tablename__ = "feed_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    child_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("children.id"), nullable=True)
    type: Mapped[FeedEventType] = mapped_column(
        Enum(FeedEventType, native_enum=False, length=20)
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    actor: Mapped[User] = relationship()


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id"), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reward_type: Mapped[RewardType] = mapped_column(
        Enum(RewardType, native_enum=False, length=20)
    )
    reward_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[GoalStatus] = mapped_column(
        Enum(GoalStatus, native_enum=False, length=20), default=GoalStatus.active
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    child: Mapped[Child] = relationship()


class GoalCompletion(Base):
    __tablename__ = "goal_completions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    goal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goals.id"), unique=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    verified_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    goal: Mapped[Goal] = relationship()


class Badge(Base):
    __tablename__ = "badges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    icon: Mapped[str] = mapped_column(String(16), default="🏅")
    source_goal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("goals.id"), nullable=True)
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Contribution(Base):
    __tablename__ = "contributions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id"), index=True)
    contributor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    fee_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    refunded_cents: Mapped[int] = mapped_column(BigInteger, default=0)  # cumulative gross refunded
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_objects.id"), nullable=True
    )
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ContributionStatus] = mapped_column(
        Enum(ContributionStatus, native_enum=False, length=20),
        default=ContributionStatus.pending,
    )
    trigger_feed_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("feed_events.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    child: Mapped[Child] = relationship()
    contributor: Mapped[User] = relationship()


class FundAccount(Base):
    __tablename__ = "fund_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id"), unique=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    # --- Stripe Connect (Express): the child's real account. The account is
    # legally the parent's (setup_by), earmarked for the child; the id is
    # server-only and never serialized to clients. Status columns are a cache
    # of Stripe state (account.updated / accounts.retrieve) — informational,
    # never authoritative, and never money.
    stripe_account_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    account_status: Mapped[FundAccountStatus] = mapped_column(
        Enum(FundAccountStatus, native_enum=False, length=20),
        default=FundAccountStatus.none,
    )
    setup_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    charges_enabled: Mapped[bool] = mapped_column(default=False)
    payouts_enabled: Mapped[bool] = mapped_column(default=False)
    requirements_due: Mapped[bool] = mapped_column(default=False)
    onboarding_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FundNudge(Base):
    """A non-guardian member's gentle 'I'm ready to give' nudge to the
    parents to finish Future Fund setup. ONE row per (member, child) — the
    unique constraint is the race-safe 7-day throttle: a re-nudge after the
    window refreshes created_at in place, and a concurrent double-tap loses
    the insert race instead of double-sending. Rows older than 30 days are
    swept by the daily maintenance command (storage limitation)."""

    __tablename__ = "fund_nudges"
    __table_args__ = (
        UniqueConstraint("child_id", "user_id", name="uq_fund_nudges_member_child"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FundLedgerEntry(Base):
    """Append-only. Never UPDATE or DELETE a row; corrections are new
    compensating entries. Written only by record_payment_succeeded (verified
    payment events) — see services/payments.py."""

    __tablename__ = "fund_ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fund_accounts.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)  # signed
    entry_type: Mapped[LedgerEntryType] = mapped_column(
        Enum(LedgerEntryType, native_enum=False, length=20)
    )
    source_contribution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contributions.id"), nullable=True, unique=True
    )
    anchor_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TimeCapsule(Base):
    """Sealed capsules are visible in full only to their creator until released;
    everyone else sees existence + condition, never body or media."""

    __tablename__ = "time_capsules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id"), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    type: Mapped[CapsuleType] = mapped_column(Enum(CapsuleType, native_enum=False, length=20))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_objects.id"), nullable=True
    )
    release_condition: Mapped[ReleaseCondition] = mapped_column(
        Enum(ReleaseCondition, native_enum=False, length=20)
    )
    release_age: Mapped[int | None] = mapped_column(nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    release_milestone: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # "Specific goal completion": unlocks when this goal is completed.
    release_goal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("goals.id"), nullable=True
    )
    status: Mapped[CapsuleStatus] = mapped_column(
        Enum(CapsuleStatus, native_enum=False, length=20), default=CapsuleStatus.sealed
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    child: Mapped[Child] = relationship()
    author: Mapped[User] = relationship()
    media: Mapped[MediaObject | None] = relationship()


class LegacyItem(Base):
    __tablename__ = "legacy_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    type: Mapped[LegacyType] = mapped_column(Enum(LegacyType, native_enum=False, length=20))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_objects.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    media: Mapped[MediaObject | None] = relationship()
    author: Mapped[User] = relationship()


class CapsuleReleaseVote(Base):
    """A guardian's agreement that a 'life moment' capsule's condition has been
    met. Two distinct guardian votes (other than the creator) release it; the
    creator can always release directly. Supporters cannot vote."""

    __tablename__ = "capsule_release_votes"
    __table_args__ = (UniqueConstraint("capsule_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    capsule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("time_capsules.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Comment(Base):
    """A family member's comment on a feed event (Family Moment)."""

    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    feed_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feed_events.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    author: Mapped[User] = relationship()


class Reaction(Base):
    """An emoji reaction on a feed event or a comment. One row per
    (target, user, emoji); toggling removes the row."""

    __tablename__ = "reactions"
    __table_args__ = (UniqueConstraint("target_type", "target_id", "user_id", "emoji"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    target_type: Mapped[ReactionTargetType] = mapped_column(
        Enum(ReactionTargetType, native_enum=False, length=20)
    )
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    emoji: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationPreference(Base):
    """Per-user email notification switches. A missing row means defaults
    (milestone + new-member on, memory + legacy off)."""

    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    email_new_member: Mapped[bool] = mapped_column(default=True)
    email_milestone: Mapped[bool] = mapped_column(default=True)
    email_memory: Mapped[bool] = mapped_column(default=False)
    email_legacy: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PasswordReset(Base):
    """Single-use, short-lived reset tokens; only the SHA-256 of the token is stored."""

    __tablename__ = "password_resets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()


# --- Family Video Call (Agora RTC) ---
# A family-only "living room": at most one active call per family at a time.
# No A/V is ever stored and calls deliberately emit no feed events.


class FamilyCall(Base):
    __tablename__ = "family_calls"
    # DB-portable "one active call per family" guard: active_family_id equals
    # family_id while the call is active and is set NULL when it ends. Because
    # NULLs are distinct under a unique constraint (in both Postgres and
    # SQLite), any number of ended calls coexist but only one can be active.
    __table_args__ = (
        UniqueConstraint("active_family_id", name="uq_one_active_call_per_family"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    active_family_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    channel_name: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus, native_enum=False, length=20), default=CallStatus.active
    )
    started_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CallParticipant(Base):
    __tablename__ = "call_participants"
    __table_args__ = (
        UniqueConstraint("call_id", "user_id"),
        UniqueConstraint("call_id", "agora_uid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("family_calls.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    # Server-assigned Agora uid, stable for the life of the call (reused on
    # rejoin). Client never supplies it.
    agora_uid: Mapped[int] = mapped_column(BigInteger)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()


class CallChildPresence(Base):
    """A child a member has flagged as "in the room" on a call. Cleared when the
    marking member goes stale/leaves."""

    __tablename__ = "call_child_presence"
    __table_args__ = (UniqueConstraint("call_id", "child_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("family_calls.id"), index=True)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id"), index=True)
    marked_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlannedCall(Base):
    """The single next scheduled family call. One row per family (upsert)."""

    __tablename__ = "planned_calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("families.id"), unique=True, index=True
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    set_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# --- FutureRoots Premium (family-level membership) ---
# Premium state is ALWAYS derived at read time from family_subscriptions +
# premium_grants (services/entitlements.py). There is no is_premium column
# anywhere, by design.


class FamilySubscription(Base):
    """Mirror of the family's recurring Stripe subscription. Written ONLY by
    verified webhook handlers, the parent-initiated /sync reconcile (which
    reads live Stripe state), and the local backend's simulated settle —
    never from client say-so."""

    __tablename__ = "family_subscriptions"
    __table_args__ = (
        # At most one non-canceled subscription per family (double-subscribe
        # backstop). Partial on both Postgres (prod) and SQLite (tests).
        Index(
            "uq_family_subscriptions_live",
            "family_id",
            unique=True,
            postgresql_where=text("status != 'canceled'"),
            sqlite_where=text("status != 'canceled'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    stripe_customer_id: Mapped[str] = mapped_column(String(64))
    stripe_subscription_id: Mapped[str] = mapped_column(String(64), unique=True)
    plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(SubscriptionPlan, native_enum=False, length=20)
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, native_enum=False, length=20)
    )
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PremiumGrant(Base):
    """A prepaid Premium period (gift). Append-only: written ONLY when a
    verified webhook (or the live-Stripe /sync path) confirms payment.
    The single permitted mutation is the admin-only void (support refunds) —
    same deliberate exception as contributions.refunded_cents."""

    __tablename__ = "premium_grants"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_premium_grants_period"),
        CheckConstraint("amount_cents > 0", name="ck_premium_grants_amount"),
        Index("ix_premium_grants_family_ends", "family_id", "ends_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    source: Mapped[str] = mapped_column(String(20), default="gift")  # future: "promo", "support"
    granted_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    stripe_checkout_session_id: Mapped[str] = mapped_column(String(255), unique=True)  # idempotency key
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_cents: Mapped[int] = mapped_column()          # integer cents, always
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Admin-only void (manual refund/chargeback support path); voided grants
    # are ignored by the entitlement derivation but never deleted.
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PremiumGiftIntent(Base):
    """Created when a gifter starts checkout; holds the gift message locally so
    free text (which may name a child) is NEVER sent to Stripe. Not a money
    row — abandoned checkouts leave a harmless orphan here (no grant, no feed
    event, no email). Pruned after 30 days by the daily maintenance command
    (services/maintenance.py; the admin endpoint stays as a manual trigger)."""

    __tablename__ = "premium_gift_intents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    gifter_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    stripe_checkout_session_id: Mapped[str] = mapped_column(String(255), unique=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PremiumEmailLog(Base):
    """One row per (kind, dedupe_key) ever sent. INSERT with the unique
    constraint is the race-safe guard: insert first, send only on success."""

    __tablename__ = "premium_email_log"
    __table_args__ = (UniqueConstraint("kind", "dedupe_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))   # payment_failed | renewal_upcoming | premium_ended | gift_ending_soon | duplicate_subscription
    dedupe_key: Mapped[str] = mapped_column(String(255))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --- Testnet harness (settings.testnet_mode deployments only) ---
# These tables exist for the gamified testing program on
# testnet.futureroots.app. The family product never reads or writes them;
# with testnet_mode off, no code path touches them.


class Tester(Base):
    """A wallet-identified tester, linked 1:1 to a platform user so the whole
    product API works for them unchanged. Wallet addresses are stored
    lowercase; one tester per wallet."""

    __tablename__ = "testers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    wallet_address: Mapped[str] = mapped_column(String(42), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    # Optional X (Twitter) connection. When linked, the tester's X profile
    # picture and @handle replace the deterministic wallet identicon. One X
    # account per tester (x_user_id is unique).
    x_user_id: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    x_username: Mapped[str | None] = mapped_column(String(50), nullable=True)
    x_avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()


class XAuthState(Base):
    """Single-use, short-lived PKCE handshake state for the X OAuth 2.0
    connect flow. A row is created when a tester starts the connect flow and
    consumed (deleted) on callback; expires after 10 minutes."""

    __tablename__ = "x_auth_states"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tester_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("testers.id"), index=True)
    state: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_verifier: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WalletNonce(Base):
    """Single-use, short-lived sign-in nonces for testnet wallet login."""

    __tablename__ = "wallet_nonces"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    wallet_address: Mapped[str] = mapped_column(String(42), unique=True, index=True)
    nonce: Mapped[str] = mapped_column(String(64))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PointEvent(Base):
    """Append-only testnet points, mirroring the fund-ledger discipline:
    never UPDATE or DELETE; totals are always derived via SUM. Written only
    by app.testnet.service.award (server-verified actions)."""

    __tablename__ = "point_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tester_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("testers.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    points: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class BugReport(Base):
    """A tester-submitted bug. Append-only-friendly: submission never scores.
    The bug_verified points are awarded only when a human reviewer verifies the
    report (the admin verify endpoint), and points_awarded guards against ever
    awarding twice for the same report."""

    __tablename__ = "bug_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # a report comes from exactly one of: a testnet tester, or a main-site user
    tester_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("testers.id"), nullable=True, index=True
    )
    reporter_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|verified|rejected
    points_awarded: Mapped[bool] = mapped_column(default=False)
    media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_objects.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id"), index=True)
    granted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    consent_type: Mapped[ConsentType] = mapped_column(
        Enum(ConsentType, native_enum=False, length=30)
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
