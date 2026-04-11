"""agent owner client

Revision ID: 20260409_000007
Revises: 20260409_000006
Create Date: 2026-04-09 19:20:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260409_000007"
down_revision = "20260409_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("owner_client_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_agents_owner_client_id_clients",
        "agents",
        "clients",
        ["owner_client_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_agents_owner_client_id_clients", "agents", type_="foreignkey")
    op.drop_column("agents", "owner_client_id")
