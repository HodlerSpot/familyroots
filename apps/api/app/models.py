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
    member_joined = "member_joined"


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
    # Media is always scoped to a child so access control follows the Family Graph
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(BigInteger, default=0)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[MediaStatus] = mapped_column(
        Enum(MediaStatus, native_enum=False, length=20), default=MediaStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    child: Mapped[Child] = relationship()


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
