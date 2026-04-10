"""add_judge_evaluations

Revision ID: g6h7i8j9k0l1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-08 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'g6h7i8j9k0l1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'judge_evaluations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('client_id', sa.String(), nullable=True),
        sa.Column('lead_id', sa.String(), nullable=True),
        sa.Column('job_id', sa.String(), nullable=True),
        sa.Column('channel', sa.String(), nullable=True),
        sa.Column('personalization_score', sa.Float(), nullable=True),
        sa.Column('cultural_fit_score', sa.Float(), nullable=True),
        sa.Column('cta_strength_score', sa.Float(), nullable=True),
        sa.Column('tone_match_score', sa.Float(), nullable=True),
        sa.Column('clarity_score', sa.Float(), nullable=True),
        sa.Column('weighted_score', sa.Float(), nullable=True),
        sa.Column('verdict', sa.String(), nullable=True),
        sa.Column('primary_weakness', sa.String(), nullable=True),
        sa.Column('was_rewritten', sa.Boolean(), nullable=True),
        sa.Column('final_passed', sa.Boolean(), nullable=True),
        sa.Column('red_flags_json', sa.Text(), nullable=True),
        sa.Column('improvement_suggestion', sa.Text(), nullable=True),
        sa.Column('judge_model', sa.String(), nullable=True),
        sa.Column('evaluation_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('judge_evaluations')
