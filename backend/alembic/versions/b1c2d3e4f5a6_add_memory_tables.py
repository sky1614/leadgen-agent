"""add_memory_tables

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-04-06 00:02:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'episodic_memory',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('client_id', sa.String(), sa.ForeignKey('clients.id'), nullable=True),
        sa.Column('lead_id', sa.String(), nullable=True),
        sa.Column('outcome', sa.String(), nullable=True),
        sa.Column('channel', sa.String(), nullable=True),
        sa.Column('message_length', sa.Integer(), nullable=True),
        sa.Column('had_name', sa.Boolean(), nullable=True),
        sa.Column('had_company', sa.Boolean(), nullable=True),
        sa.Column('had_pain_point', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'semantic_memory',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('client_id', sa.String(), nullable=True),
        sa.Column('industry', sa.String(), nullable=True),
        sa.Column('pattern_type', sa.String(), nullable=True),
        sa.Column('pattern_value', sa.String(), nullable=True),
        sa.Column('success_rate', sa.Float(), nullable=True),
        sa.Column('sample_count', sa.Integer(), nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('semantic_memory')
    op.drop_table('episodic_memory')
