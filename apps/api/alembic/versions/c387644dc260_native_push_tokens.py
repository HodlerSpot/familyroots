"""native_push_tokens (native iOS/Android Expo push enrollment)

Adds the native_push_tokens table: one row per enrolled iOS/Android device,
holding its opaque Expo push token (unique), platform, optional label, and
first-seen / last-seen timestamps. Separate from push_subscriptions (web VAPID)
because the transports are unrelated. platform is a non-native (VARCHAR) enum,
matching the rest of the codebase. Additive only — no existing table changes.

Revision ID: c387644dc260
Revises: f4a9c2e7b1d8
Create Date: 2026-07-22 12:46:04.599409

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c387644dc260"
down_revision: Union[str, None] = "f4a9c2e7b1d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "native_push_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("expo_push_token", sa.String(length=255), nullable=False),
        sa.Column(
            "platform",
            sa.Enum("ios", "android", name="nativepushplatform", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("device_label", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # expo_push_token is unique=True, index=True on the model -> one unique index.
    op.create_index(
        op.f("ix_native_push_tokens_expo_push_token"),
        "native_push_tokens",
        ["expo_push_token"],
        unique=True,
    )
    op.create_index(
        op.f("ix_native_push_tokens_user_id"),
        "native_push_tokens",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_native_push_tokens_user_id"), table_name="native_push_tokens")
    op.drop_index(
        op.f("ix_native_push_tokens_expo_push_token"), table_name="native_push_tokens"
    )
    op.drop_table("native_push_tokens")
