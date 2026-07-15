"""fund nudges

Revision ID: b7d3e91c4f20
Revises: a05c08f146b0
Create Date: 2026-07-14 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7d3e91c4f20'
down_revision: Union[str, None] = 'a05c08f146b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'fund_nudges',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('child_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['child_id'], ['children.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_fund_nudges_child_id'), 'fund_nudges', ['child_id'], unique=False)
    op.create_index(op.f('ix_fund_nudges_user_id'), 'fund_nudges', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_fund_nudges_user_id'), table_name='fund_nudges')
    op.drop_index(op.f('ix_fund_nudges_child_id'), table_name='fund_nudges')
    op.drop_table('fund_nudges')
