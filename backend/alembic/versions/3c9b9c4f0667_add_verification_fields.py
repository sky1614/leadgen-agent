"""add verification fields

Revision ID: 3c9b9c4f0667
Revises: 292d03497158
Create Date: 2026-03-28 14:36:34.934611

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c9b9c4f0667'
down_revision: Union[str, Sequence[str], None] = '292d03497158'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('leads', sa.Column('wa_verified', sa.Boolean(), nullable=True))
    op.add_column('leads', sa.Column('verification_date', sa.DateTime(), nullable=True))
    op.add_column('leads', sa.Column('contact_channels', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('leads', 'contact_channels')
    op.drop_column('leads', 'verification_date')
    op.drop_column('leads', 'wa_verified')
