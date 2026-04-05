"""add_approval_fields

Revision ID: 80f52005677d
Revises: 06f088b91424
Create Date: 2026-03-29 13:14:20.814427

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '80f52005677d'
down_revision: Union[str, Sequence[str], None] = '06f088b91424'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('message_log', sa.Column('approval_status', sa.String(), nullable=True))
    op.add_column('message_log', sa.Column('approved_by', sa.String(), nullable=True))
    op.add_column('message_log', sa.Column('approved_at', sa.DateTime(), nullable=True))
    op.add_column('message_log', sa.Column('rejection_reason', sa.String(), nullable=True))
    op.add_column('message_log', sa.Column('quality_gate_score', sa.Float(), nullable=True))
    op.add_column('message_log', sa.Column('quality_gate_issues', sa.JSON(), nullable=True))

def downgrade() -> None:
    op.drop_column('message_log', 'quality_gate_issues')
    op.drop_column('message_log', 'quality_gate_score')
    op.drop_column('message_log', 'rejection_reason')
    op.drop_column('message_log', 'approved_at')
    op.drop_column('message_log', 'approved_by')
    op.drop_column('message_log', 'approval_status')
