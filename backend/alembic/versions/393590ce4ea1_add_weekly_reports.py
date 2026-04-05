"""add_weekly_reports

Revision ID: 393590ce4ea1
Revises: 80f52005677d
Create Date: 2026-03-29 14:18:38.293599

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '393590ce4ea1'
down_revision: Union[str, Sequence[str], None] = '80f52005677d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('weekly_reports',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('client_id', sa.String(), nullable=True),
        sa.Column('week_start', sa.DateTime(), nullable=True),
        sa.Column('week_end', sa.DateTime(), nullable=True),
        sa.Column('stats_json', sa.Text(), nullable=True),
        sa.Column('sent_to', sa.String(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade() -> None:
    op.drop_table('weekly_reports')
