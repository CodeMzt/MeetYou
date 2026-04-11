"""core state tables

Revision ID: 20260408_000002
Revises: 20260408_000001
Create Date: 2026-04-08 17:20:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260408_000002"
down_revision = "20260408_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "config_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("config_key", sa.String(length=128), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("is_secret", sa.Boolean(), nullable=False),
        sa.Column("has_value", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("env_key", sa.String(length=128), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("config_key", name="uq_config_entries_config_key"),
    )
    op.create_table(
        "memory_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("memory_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("origin_workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope_user_id", sa.String(length=128), nullable=False),
        sa.Column("scope_session_id", sa.String(length=128), nullable=False),
        sa.Column("record_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("canonical_text", sa.Text(), nullable=False),
        sa.Column("raw_record", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_memory_records_principal_id_principals"),
        sa.ForeignKeyConstraint(["origin_workspace_id"], ["workspaces.id"], name="fk_memory_records_origin_workspace_id_workspaces"),
        sa.UniqueConstraint("memory_id", name="uq_memory_records_memory_id"),
    )
    op.create_table(
        "memory_workspace_tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("memory_row_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["memory_row_id"], ["memory_records.id"], name="fk_memory_workspace_tags_memory_row_id_memory_records"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_memory_workspace_tags_workspace_id_workspaces"),
        sa.UniqueConstraint("memory_row_id", "workspace_id", name="uq_memory_workspace_tags_memory_row_id"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope_user_id", sa.String(length=128), nullable=False),
        sa.Column("scope_session_id", sa.String(length=128), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("execution_target", sa.String(length=64), nullable=False),
        sa.Column("due_at", sa.String(length=64), nullable=False),
        sa.Column("next_run_at", sa.String(length=64), nullable=False),
        sa.Column("raw_record", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_tasks_principal_id_principals"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_tasks_workspace_id_workspaces"),
        sa.UniqueConstraint("task_id", name="uq_tasks_task_id"),
    )


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("memory_workspace_tags")
    op.drop_table("memory_records")
    op.drop_table("config_entries")
