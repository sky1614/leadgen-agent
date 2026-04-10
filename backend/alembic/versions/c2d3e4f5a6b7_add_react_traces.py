"""add_react_traces

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-04-07 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'react_traces',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('client_id', sa.String(), sa.ForeignKey('clients.id'), nullable=True),
        sa.Column('job_id', sa.String(), nullable=True),
        sa.Column('lead_id', sa.String(), nullable=True),
        sa.Column('trace_type', sa.String(), nullable=True),
        sa.Column('decision', sa.String(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('thought_trace_json', sa.Text(), nullable=True),
        sa.Column('recommended_action', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('react_traces')
