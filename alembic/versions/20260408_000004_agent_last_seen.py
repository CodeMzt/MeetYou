"""agent last seen

Revision ID: 20260408_000004
Revises: 20260408_000003
Create Date: 2026-04-08 20:05:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260408_000004"
down_revision = "20260408_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "last_seen_at")
