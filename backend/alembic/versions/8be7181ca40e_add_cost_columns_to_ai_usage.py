"""add_cost_columns_to_ai_usage

Revision ID: 8be7181ca40e
Revises: 393590ce4ea1
Create Date: 2026-03-29 14:49:46.945223

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8be7181ca40e'
down_revision: Union[str, Sequence[str], None] = '393590ce4ea1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ai_usage', sa.Column('units_used', sa.Integer(), nullable=True))
    op.add_column('ai_usage', sa.Column('cost_inr', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('ai_usage', 'cost_inr')
    op.drop_column('ai_usage', 'units_used')
