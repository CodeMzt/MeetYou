"""runtime state blobs

Revision ID: 20260408_000005
Revises: 20260408_000004
Create Date: 2026-04-08 23:58:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260408_000005"
down_revision = "20260408_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_state_blobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state_key", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_runtime_state_blobs_principal_id_principals"),
        sa.UniqueConstraint("principal_id", "state_key", name="uq_runtime_state_blobs_principal_id"),
    )


def downgrade() -> None:
    op.drop_table("runtime_state_blobs")
