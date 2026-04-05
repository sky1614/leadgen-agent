"""add email tracking fields

Revision ID: 292d03497158
Revises: a95566cba2be
Create Date: 2026-03-28 14:14:10.198776

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '292d03497158'
down_revision: Union[str, Sequence[str], None] = 'a95566cba2be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('leads', sa.Column('email_verified', sa.Boolean(), nullable=True))
    op.add_column('leads', sa.Column('do_not_contact', sa.Boolean(), nullable=True))
    op.add_column('message_log', sa.Column('sendgrid_message_id', sa.String(), nullable=True))
    op.add_column('message_log', sa.Column('delivered_at', sa.DateTime(), nullable=True))
    op.add_column('message_log', sa.Column('opened_at', sa.DateTime(), nullable=True))
    op.add_column('message_log', sa.Column('clicked_at', sa.DateTime(), nullable=True))
    op.add_column('message_log', sa.Column('bounced', sa.Boolean(), nullable=True))
    op.add_column('message_log', sa.Column('bounce_type', sa.String(), nullable=True))
    op.add_column('message_log', sa.Column('spam_reported', sa.Boolean(), nullable=True))
    op.add_column('message_log', sa.Column('unsubscribed', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('message_log', 'unsubscribed')
    op.drop_column('message_log', 'spam_reported')
    op.drop_column('message_log', 'bounce_type')
    op.drop_column('message_log', 'bounced')
    op.drop_column('message_log', 'clicked_at')
    op.drop_column('message_log', 'opened_at')
    op.drop_column('message_log', 'delivered_at')
    op.drop_column('message_log', 'sendgrid_message_id')
    op.drop_column('leads', 'do_not_contact')
    op.drop_column('leads', 'email_verified')
