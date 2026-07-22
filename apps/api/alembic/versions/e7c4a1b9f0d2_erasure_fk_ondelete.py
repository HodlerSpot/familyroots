"""erasure FK ondelete + nullable severance (compliance WS1)

Closes the FK gaps the manual erasure runbook (docs/erasure-runbook.md §3, §7)
called out: every relationship was a bare ForeignKey with NO ACTION, so a
self-serve erasure walk could not hard-delete a users/children/families row
without a violation. This migration makes the walk a clean transaction:

- ON DELETE CASCADE where a hard-delete is ALWAYS correct (the dependent row
  has no life of its own): child_relationships, capsule_release_votes,
  fund_nudges, the four video-call tables, predictions -> prediction_rounds,
  prediction_rounds -> children, memory_prompts, and comments -> feed_events.
- nullable + ON DELETE SET NULL where the row must SURVIVE with a severed
  reference: family-history authorship (*.created_by, feed_events.actor_user_id,
  goal_completions.verified_by, families.created_by, media_objects.uploaded_by,
  admin_audit_log.admin_user_id) and the retained FINANCIAL records
  (contributions, family_subscriptions, premium_grants, premium_gift_intents),
  whose money fields are never touched — only the person/child/family link is
  severed (§3.D). contributions.child_id and fund_accounts.child_id are also
  SET NULL so a child can be erased while the ledger + contribution records are
  retained; *_subscription/grant.family_id likewise for whole-family erasure.

Alembic autogenerate does NOT detect ondelete changes, so this is hand-written
(drop + recreate each FK under its default <table>_<column>_fkey name).

Revision ID: e7c4a1b9f0d2
Revises: 449af98a1296
Create Date: 2026-07-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7c4a1b9f0d2"
down_revision: Union[str, None] = "449af98a1296"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, referred_table) — recreated with ON DELETE SET NULL.
SET_NULL: list[tuple[str, str, str]] = [
    ("admin_audit_log", "admin_user_id", "users"),
    ("families", "created_by", "users"),
    ("media_objects", "uploaded_by", "users"),
    ("vault_items", "created_by", "users"),
    ("feed_events", "actor_user_id", "users"),
    ("goals", "created_by", "users"),
    ("goal_completions", "verified_by", "users"),
    ("time_capsules", "created_by", "users"),
    ("legacy_items", "created_by", "users"),
    ("contributions", "contributor_user_id", "users"),
    ("contributions", "child_id", "children"),
    ("contributions", "trigger_feed_event_id", "feed_events"),
    ("fund_accounts", "child_id", "children"),
    ("fund_accounts", "setup_by", "users"),
    ("family_members", "invited_by", "users"),
    ("family_subscriptions", "family_id", "families"),
    ("family_subscriptions", "owner_user_id", "users"),
    ("premium_grants", "family_id", "families"),
    ("premium_grants", "granted_by_user_id", "users"),
    ("premium_grants", "voided_by_user_id", "users"),
    ("premium_gift_intents", "gifter_user_id", "users"),
]

# (table, column, referred_table) — recreated with ON DELETE CASCADE.
CASCADE: list[tuple[str, str, str]] = [
    ("child_relationships", "child_id", "children"),
    ("child_relationships", "user_id", "users"),
    ("capsule_release_votes", "capsule_id", "time_capsules"),
    ("capsule_release_votes", "user_id", "users"),
    ("comments", "feed_event_id", "feed_events"),
    ("fund_nudges", "child_id", "children"),
    ("fund_nudges", "user_id", "users"),
    ("memory_prompts", "user_id", "users"),
    ("memory_prompts", "family_id", "families"),
    ("memory_prompts", "child_id", "children"),
    ("prediction_rounds", "child_id", "children"),
    ("predictions", "round_id", "prediction_rounds"),
    ("family_calls", "family_id", "families"),
    ("family_calls", "started_by", "users"),
    ("call_participants", "call_id", "family_calls"),
    ("call_participants", "user_id", "users"),
    ("call_child_presence", "call_id", "family_calls"),
    ("call_child_presence", "child_id", "children"),
    ("call_child_presence", "marked_by", "users"),
    ("planned_calls", "family_id", "families"),
    ("planned_calls", "set_by", "users"),
]

# Columns that were NOT NULL and are widened to nullable (subset of SET_NULL).
# Must match the model exactly so `alembic check` stays clean.
NEWLY_NULLABLE: list[tuple[str, str]] = [
    ("admin_audit_log", "admin_user_id"),
    ("families", "created_by"),
    ("media_objects", "uploaded_by"),
    ("vault_items", "created_by"),
    ("feed_events", "actor_user_id"),
    ("goals", "created_by"),
    ("goal_completions", "verified_by"),
    ("time_capsules", "created_by"),
    ("legacy_items", "created_by"),
    ("contributions", "contributor_user_id"),
    ("contributions", "child_id"),
    ("fund_accounts", "child_id"),
    ("family_subscriptions", "family_id"),
    ("family_subscriptions", "owner_user_id"),
    ("premium_grants", "family_id"),
    ("premium_grants", "granted_by_user_id"),
    ("premium_gift_intents", "gifter_user_id"),
]


def _fk(table: str, column: str) -> str:
    # Postgres default single-column FK constraint name.
    return f"{table}_{column}_fkey"


def upgrade() -> None:
    for table, column in NEWLY_NULLABLE:
        op.alter_column(table, column, existing_type=sa.Uuid(), nullable=True)
    for table, column, referred in SET_NULL:
        op.drop_constraint(_fk(table, column), table, type_="foreignkey")
        op.create_foreign_key(
            _fk(table, column), table, referred, [column], ["id"], ondelete="SET NULL"
        )
    for table, column, referred in CASCADE:
        op.drop_constraint(_fk(table, column), table, type_="foreignkey")
        op.create_foreign_key(
            _fk(table, column), table, referred, [column], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    # Recreate the bare (NO ACTION) constraints and restore NOT NULL. Note: if
    # any row was severed (a NULL written by an erasure) the NOT NULL restore
    # will fail — deliberately, since those identities cannot be reconstituted.
    for table, column, referred in CASCADE + SET_NULL:
        op.drop_constraint(_fk(table, column), table, type_="foreignkey")
        op.create_foreign_key(_fk(table, column), table, referred, [column], ["id"])
    for table, column in NEWLY_NULLABLE:
        op.alter_column(table, column, existing_type=sa.Uuid(), nullable=False)
