"""add_prompt_versions

Revision ID: f3a1b2c4d5e6
Revises: ac3c68189cd5
Create Date: 2026-04-06 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f3a1b2c4d5e6'
down_revision: Union[str, None] = 'ac3c68189cd5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'prompt_versions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('client_id', sa.String(), sa.ForeignKey('clients.id'), nullable=True),
        sa.Column('template_name', sa.String(), nullable=False),
        sa.Column('prompt_text', sa.Text(), nullable=False),
        sa.Column('reply_rate_at_creation', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('prompt_versions')
