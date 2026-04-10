"""add_ab_testing

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-08 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ab_tests',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('client_id', sa.String(), sa.ForeignKey('clients.id'), nullable=True),
        sa.Column('campaign_id', sa.String(), nullable=True),
        sa.Column('template_name', sa.String(), nullable=True),
        sa.Column('control_prompt', sa.Text(), nullable=True),
        sa.Column('treatment_prompt', sa.Text(), nullable=True),
        sa.Column('control_messages_sent', sa.Integer(), default=0),
        sa.Column('control_replies', sa.Integer(), default=0),
        sa.Column('control_opens', sa.Integer(), default=0),
        sa.Column('control_bounces', sa.Integer(), default=0),
        sa.Column('treatment_messages_sent', sa.Integer(), default=0),
        sa.Column('treatment_replies', sa.Integer(), default=0),
        sa.Column('treatment_opens', sa.Integer(), default=0),
        sa.Column('treatment_bounces', sa.Integer(), default=0),
        sa.Column('status', sa.String(), default='running'),
        sa.Column('winner', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.add_column('message_log', sa.Column('ab_test_id', sa.String(), nullable=True))
    op.add_column('message_log', sa.Column('ab_test_variant', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('message_log', 'ab_test_variant')
    op.drop_column('message_log', 'ab_test_id')
    op.drop_table('ab_tests')
