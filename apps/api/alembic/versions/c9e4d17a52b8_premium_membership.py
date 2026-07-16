"""FutureRoots Premium: family subscriptions, gift grants, email log

Revision ID: c9e4d17a52b8
Revises: b7d3e91c4f20
Create Date: 2026-07-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9e4d17a52b8'
down_revision: Union[str, None] = 'b7d3e91c4f20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # One Stripe Customer per adult user, created lazily on first checkout.
    op.add_column('users', sa.Column('stripe_customer_id', sa.String(length=64), nullable=True))
    op.create_unique_constraint('uq_users_stripe_customer_id', 'users', ['stripe_customer_id'])

    op.create_table(
        'family_subscriptions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=False),
        sa.Column('owner_user_id', sa.Uuid(), nullable=False),
        sa.Column('stripe_customer_id', sa.String(length=64), nullable=False),
        sa.Column('stripe_subscription_id', sa.String(length=64), nullable=False),
        sa.Column('plan', sa.Enum('monthly', 'annual', name='subscriptionplan', native_enum=False, length=20), nullable=False),
        sa.Column('status', sa.Enum('active', 'past_due', 'canceled', name='subscriptionstatus', native_enum=False, length=20), nullable=False),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stripe_subscription_id'),
    )
    op.create_index(op.f('ix_family_subscriptions_family_id'), 'family_subscriptions', ['family_id'], unique=False)
    # At most one non-canceled subscription per family (double-subscribe backstop).
    op.create_index(
        'uq_family_subscriptions_live',
        'family_subscriptions',
        ['family_id'],
        unique=True,
        postgresql_where=sa.text("status != 'canceled'"),
    )

    op.create_table(
        'premium_grants',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('granted_by_user_id', sa.Uuid(), nullable=False),
        sa.Column('stripe_checkout_session_id', sa.String(length=255), nullable=False),
        sa.Column('stripe_payment_intent_id', sa.String(length=64), nullable=True),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=True),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('voided_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('ends_at > starts_at', name='ck_premium_grants_period'),
        sa.CheckConstraint('amount_cents > 0', name='ck_premium_grants_amount'),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['granted_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['voided_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stripe_checkout_session_id'),
    )
    op.create_index(op.f('ix_premium_grants_family_id'), 'premium_grants', ['family_id'], unique=False)
    op.create_index('ix_premium_grants_family_ends', 'premium_grants', ['family_id', 'ends_at'], unique=False)

    op.create_table(
        'premium_gift_intents',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=False),
        sa.Column('gifter_user_id', sa.Uuid(), nullable=False),
        sa.Column('stripe_checkout_session_id', sa.String(length=255), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['gifter_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stripe_checkout_session_id'),
    )
    op.create_index(op.f('ix_premium_gift_intents_family_id'), 'premium_gift_intents', ['family_id'], unique=False)

    op.create_table(
        'premium_email_log',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('dedupe_key', sa.String(length=255), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kind', 'dedupe_key'),
    )
    op.create_index(op.f('ix_premium_email_log_family_id'), 'premium_email_log', ['family_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_premium_email_log_family_id'), table_name='premium_email_log')
    op.drop_table('premium_email_log')
    op.drop_index(op.f('ix_premium_gift_intents_family_id'), table_name='premium_gift_intents')
    op.drop_table('premium_gift_intents')
    op.drop_index('ix_premium_grants_family_ends', table_name='premium_grants')
    op.drop_index(op.f('ix_premium_grants_family_id'), table_name='premium_grants')
    op.drop_table('premium_grants')
    op.drop_index('uq_family_subscriptions_live', table_name='family_subscriptions')
    op.drop_index(op.f('ix_family_subscriptions_family_id'), table_name='family_subscriptions')
    op.drop_table('family_subscriptions')
    op.drop_constraint('uq_users_stripe_customer_id', 'users', type_='unique')
    op.drop_column('users', 'stripe_customer_id')
