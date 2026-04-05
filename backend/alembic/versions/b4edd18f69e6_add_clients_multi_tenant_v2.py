"""add clients multi-tenant v2

Revision ID: b4edd18f69e6
Revises: 6eecf3438806
Create Date: 2026-03-28 11:17:37.831107

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4edd18f69e6'
down_revision: Union[str, Sequence[str], None] = '6eecf3438806'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agent_jobs', sa.Column('client_id', sa.String(), nullable=True))
    op.add_column('campaigns', sa.Column('client_id', sa.String(), nullable=True))
    op.add_column('conversations', sa.Column('client_id', sa.String(), nullable=True))
    op.add_column('leads', sa.Column('client_id', sa.String(), nullable=True))
    op.add_column('message_log', sa.Column('client_id', sa.String(), nullable=True))
    op.add_column('scraped_sources', sa.Column('client_id', sa.String(), nullable=True))
    op.add_column('users', sa.Column('client_id', sa.String(), nullable=True))
    op.add_column('users', sa.Column('role', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'role')
    op.drop_column('users', 'client_id')
    op.drop_column('scraped_sources', 'client_id')
    op.drop_column('message_log', 'client_id')
    op.drop_column('leads', 'client_id')
    op.drop_column('conversations', 'client_id')
    op.drop_column('campaigns', 'client_id')
    op.drop_column('agent_jobs', 'client_id')
