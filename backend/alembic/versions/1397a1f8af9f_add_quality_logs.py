"""add_quality_logs

Revision ID: 1397a1f8af9f
Revises: daa261a53ff1
Create Date: 2026-03-29 11:07:08.582963

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1397a1f8af9f'
down_revision: Union[str, Sequence[str], None] = 'daa261a53ff1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('quality_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('client_id', sa.String(), nullable=True),
        sa.Column('lead_id', sa.String(), nullable=True),
        sa.Column('job_id', sa.String(), nullable=True),
        sa.Column('channel', sa.String(), nullable=True),
        sa.Column('passed', sa.Boolean(), nullable=True),
        sa.Column('passed_after_regen', sa.Boolean(), nullable=True),
        sa.Column('failed_permanently', sa.Boolean(), nullable=True),
        sa.Column('quality_score', sa.Float(), nullable=True),
        sa.Column('issues_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade() -> None:
    op.drop_table('quality_logs')
