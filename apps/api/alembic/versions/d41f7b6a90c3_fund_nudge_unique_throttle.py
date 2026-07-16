"""Race-safe fund-nudge throttle: one row per (member, child)

The 7-day nudge throttle was check-then-insert (two concurrent taps could
both send). fund_nudges now keeps a single row per (child_id, user_id) —
the unique constraint arbitrates the race, and a re-nudge after the window
refreshes created_at in place instead of inserting a new row.

Revision ID: d41f7b6a90c3
Revises: c9e4d17a52b8
Create Date: 2026-07-16 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd41f7b6a90c3'
down_revision: Union[str, None] = 'c9e4d17a52b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Collapse historical duplicates to the newest row per (child_id, user_id)
    # so the unique constraint can apply. Postgres-only SQL is fine here:
    # migrations run only against Postgres (tests build schema from metadata).
    op.execute(
        """
        DELETE FROM fund_nudges a
        USING fund_nudges b
        WHERE a.child_id = b.child_id
          AND a.user_id = b.user_id
          AND (a.created_at < b.created_at
               OR (a.created_at = b.created_at AND a.id < b.id))
        """
    )
    op.create_unique_constraint(
        'uq_fund_nudges_member_child', 'fund_nudges', ['child_id', 'user_id']
    )


def downgrade() -> None:
    op.drop_constraint('uq_fund_nudges_member_child', 'fund_nudges', type_='unique')
