"""add_autonomous_loop

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-04-07 00:01:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'autonomous_loop',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('client_id', sa.String(), sa.ForeignKey('clients.id'), nullable=True),
        sa.Column('campaign_id', sa.String(), nullable=True),
        sa.Column('replan_count', sa.Integer(), nullable=True),
        sa.Column('last_replan_at', sa.DateTime(), nullable=True),
        sa.Column('last_performance_json', sa.Text(), nullable=True),
        sa.Column('last_strategy_json', sa.Text(), nullable=True),
        sa.Column('total_improvements', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('autonomous_loop')
