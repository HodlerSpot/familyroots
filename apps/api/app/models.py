import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
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


class MemberStatus(str, enum.Enum):
    invited = "invited"
    active = "active"
    removed = "removed"


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


class CapsuleType(str, enum.Enum):
    letter = "letter"
    audio = "audio"
    video = "video"


class ReleaseCondition(str, enum.Enum):
    age = "age"
    date = "date"
    milestone = "milestone"


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


def role_column() -> Enum:
    return Enum(FamilyRole, native_enum=False, length=20)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list["FamilyMember"]] = relationship(
        back_populates="user", foreign_keys="FamilyMember.user_id"
    )


class Family(Base):
    __tablename__ = "families"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
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
    # Media is scoped to exactly one of child (vault, capsules) or family
    # (legacy archive) so access control always follows the Family Graph
    child_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("children.id"), nullable=True, index=True
    )
    family_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("families.id"), nullable=True, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(BigInteger, default=0)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[MediaStatus] = mapped_column(
        Enum(MediaStatus, native_enum=False, length=20), default=MediaStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    child: Mapped[Child | None] = relationship()


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()


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
