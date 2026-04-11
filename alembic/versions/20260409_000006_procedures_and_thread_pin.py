"""procedures and thread pin

Revision ID: 20260409_000006
Revises: 20260408_000005
Create Date: 2026-04-09 10:20:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260409_000006"
down_revision = "20260408_000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "procedures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("procedure_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("prompt_overlay", sa.Text(), nullable=False),
        sa.Column("default_execution_target", sa.String(length=64), nullable=False),
        sa.Column("risk_profile", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("applicable_modes", sa.JSON(), nullable=False),
        sa.Column("recommended_capabilities", sa.JSON(), nullable=False),
        sa.Column("recommended_source_profiles", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_procedures_principal_id_principals"),
        sa.UniqueConstraint("procedure_id", name="uq_procedures_procedure_id"),
    )
    op.add_column("threads", sa.Column("pinned_procedure_id", sa.String(length=128), nullable=True))
    op.create_foreign_key(
        "fk_threads_pinned_procedure_id_procedures",
        "threads",
        "procedures",
        ["pinned_procedure_id"],
        ["procedure_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_threads_pinned_procedure_id_procedures", "threads", type_="foreignkey")
    op.drop_column("threads", "pinned_procedure_id")
    op.drop_table("procedures")
