"""contributions.media_id ON DELETE SET NULL (erasure defense in depth)

Follow-up to e7c4a1b9f0d2. That migration made contribution.child_id /
contributor_user_id / trigger_feed_event_id SET NULL but left media_id a bare
NO-ACTION FK. On child/member erasure the attached personal video message is
deleted while the (retained) contribution row survives; the erasure walk nulls
media_id before deleting the media row, but a bare NO-ACTION FK would still 500
on any stray media delete that raced the null. Recreate the FK with
ON DELETE SET NULL so a deleted media_object can never orphan-fault a retained
contribution (runbook §4.5). The column is already nullable — no type change.

Split into its own revision (not an edit of the applied e7c4a1b9f0d2) to avoid
dev-DB drift.

Revision ID: f4a9c2e7b1d8
Revises: e7c4a1b9f0d2
Create Date: 2026-07-21 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "f4a9c2e7b1d8"
down_revision: Union[str, None] = "e7c4a1b9f0d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK = "contributions_media_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_FK, "contributions", type_="foreignkey")
    op.create_foreign_key(
        _FK, "contributions", "media_objects", ["media_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint(_FK, "contributions", type_="foreignkey")
    op.create_foreign_key(
        _FK, "contributions", "media_objects", ["media_id"], ["id"]
    )
