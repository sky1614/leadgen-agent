"""add_multi_agent_columns

Revision ID: h7i8j9k0l1m2
Revises: g6h7i8j9k0l1
Create Date: 2026-04-08 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "h7i8j9k0l1m2"
down_revision: Union[str, None] = "g6h7i8j9k0l1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_jobs", sa.Column("prospector_status", sa.String(), nullable=True))
    op.add_column("agent_jobs", sa.Column("scorer_status", sa.String(), nullable=True))
    op.add_column("agent_jobs", sa.Column("writer_status", sa.String(), nullable=True))
    op.add_column("agent_jobs", sa.Column("delivery_status", sa.String(), nullable=True))
    op.add_column("agent_jobs", sa.Column("leads_found", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("agent_jobs", sa.Column("leads_scored", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("agent_jobs", sa.Column("leads_written", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("agent_jobs", sa.Column("auto_approved_count", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("agent_jobs", sa.Column("pending_approval_count", sa.Integer(), nullable=True, server_default="0"))


def downgrade() -> None:
    op.drop_column("agent_jobs", "pending_approval_count")
    op.drop_column("agent_jobs", "auto_approved_count")
    op.drop_column("agent_jobs", "leads_written")
    op.drop_column("agent_jobs", "leads_scored")
    op.drop_column("agent_jobs", "leads_found")
    op.drop_column("agent_jobs", "delivery_status")
    op.drop_column("agent_jobs", "writer_status")
    op.drop_column("agent_jobs", "scorer_status")
    op.drop_column("agent_jobs", "prospector_status")
