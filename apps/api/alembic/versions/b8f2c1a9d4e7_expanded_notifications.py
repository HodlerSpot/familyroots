"""expanded notifications: pref matrix + push subscriptions + bell

Adds the 16 new NotificationPreference columns (push mirrors of the original
four kinds + both channels for six new kinds), the push_subscriptions table
(web push), and the notifications table (in-app bell). FeedEventType gains
'fund_activated' but that is a non-native (VARCHAR) enum, so it needs no DDL.

New boolean columns carry a server_default so existing preference rows get the
product defaults without a data migration; the original four email_* columns
are untouched.

Revision ID: b8f2c1a9d4e7
Revises: d41f7b6a90c3
Create Date: 2026-07-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8f2c1a9d4e7'
down_revision: Union[str, None] = 'd41f7b6a90c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (column name, server_default) — mirrors models.NotificationPreference defaults.
_NEW_PREF_COLUMNS = [
    ("push_new_member", "true"),
    ("push_milestone", "true"),
    ("push_memory", "false"),
    ("push_legacy", "false"),
    ("email_call_live", "false"),
    ("push_call_live", "true"),
    ("email_contribution", "true"),
    ("push_contribution", "true"),
    ("email_fund_activated", "true"),
    ("push_fund_activated", "true"),
    ("email_capsule_sealed", "false"),
    ("push_capsule_sealed", "true"),
    ("email_capsule_released", "true"),
    ("push_capsule_released", "true"),
    ("email_announcements", "true"),
    ("push_announcements", "true"),
]


def upgrade() -> None:
    for name, default in _NEW_PREF_COLUMNS:
        op.add_column(
            "notification_preferences",
            sa.Column(
                name, sa.Boolean(), nullable=False, server_default=sa.text(default)
            ),
        )

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.String(length=500), nullable=False),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        sa.Column("ua_label", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_push_subscriptions_user_id"), "push_subscriptions", ["user_id"], unique=False
    )
    # endpoint is unique=True, index=True on the model → one unique index.
    op.create_index(
        op.f("ix_push_subscriptions_endpoint"), "push_subscriptions", ["endpoint"], unique=True
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("family_id", sa.Uuid(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_notifications_created_at"), "notifications", ["created_at"], unique=False
    )
    op.create_index(
        "ix_notifications_user_created", "notifications", ["user_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")

    op.drop_index(op.f("ix_push_subscriptions_endpoint"), table_name="push_subscriptions")
    op.drop_index(op.f("ix_push_subscriptions_user_id"), table_name="push_subscriptions")
    op.drop_table("push_subscriptions")

    for name, _ in reversed(_NEW_PREF_COLUMNS):
        op.drop_column("notification_preferences", name)
