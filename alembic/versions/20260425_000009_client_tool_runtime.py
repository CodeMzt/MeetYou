"""client tool runtime

Revision ID: 20260425_000009
Revises: 20260424_000008
Create Date: 2026-04-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260425_000009"
down_revision = "20260424_000008"
branch_labels = None
depends_on = None


def _drop_constraint_if_exists(table: str, constraint: str) -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = :table_name AND constraint_name = :constraint_name
                ) THEN
                    EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', :table_name, :constraint_name);
                END IF;
            END $$;
            """
        ).bindparams(table_name=table, constraint_name=constraint)
    )


def _drop_column_if_exists(table: str, column: str) -> None:
    op.execute(sa.text(f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS "{column}"'))


def upgrade() -> None:
    op.add_column("clients", sa.Column("available_tools", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("clients", sa.Column("executable_tools", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("clients", sa.Column("transport_profile", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("clients", sa.Column("host_name", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("clients", sa.Column("host_os", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("clients", sa.Column("host_arch", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("clients", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='operations' AND column_name='target_agent_id')
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='operations' AND column_name='target_client_id') THEN
                    ALTER TABLE operations RENAME COLUMN target_agent_id TO target_client_id;
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='operation_calls' AND column_name='target_agent_id')
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='operation_calls' AND column_name='target_client_id') THEN
                    ALTER TABLE operation_calls RENAME COLUMN target_agent_id TO target_client_id;
                END IF;
            END $$;
            """
        )
    )
    _drop_constraint_if_exists("operations", "fk_operations_target_agent_id_agents")
    _drop_constraint_if_exists("operations", "fk_operations_target_client_id_agents")
    _drop_constraint_if_exists("operation_calls", "fk_operation_calls_target_agent_id_agents")
    _drop_constraint_if_exists("operation_calls", "fk_operation_calls_target_client_id_agents")
    op.execute(sa.text("UPDATE operations SET target_client_id = NULL WHERE target_client_id IS NOT NULL"))
    op.execute(sa.text("UPDATE operation_calls SET target_client_id = NULL WHERE target_client_id IS NOT NULL"))
    op.create_foreign_key("fk_operations_target_client_id_clients", "operations", "clients", ["target_client_id"], ["id"])
    op.create_foreign_key("fk_operation_calls_target_client_id_clients", "operation_calls", "clients", ["target_client_id"], ["id"])

    _drop_constraint_if_exists("attachments", "fk_attachments_origin_agent_id_agents")
    _drop_column_if_exists("attachments", "origin_agent_id")
    _drop_constraint_if_exists("context_pool_items", "fk_context_pool_items_source_agent_id_agents")
    _drop_column_if_exists("context_pool_items", "source_agent_id")

    op.drop_table("workspace_agent_memberships")
    op.drop_table("agent_capability_snapshots")
    op.drop_table("agents")


def downgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_type", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("transport_profile", sa.String(length=64), nullable=False),
        sa.Column("supports_offline_cache", sa.Boolean(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agents_agent_id"),
    )
    _drop_constraint_if_exists("operations", "fk_operations_target_client_id_clients")
    _drop_constraint_if_exists("operation_calls", "fk_operation_calls_target_client_id_clients")
    op.drop_column("clients", "last_seen_at")
    op.drop_column("clients", "host_arch")
    op.drop_column("clients", "host_os")
    op.drop_column("clients", "host_name")
    op.drop_column("clients", "transport_profile")
    op.drop_column("clients", "executable_tools")
    op.drop_column("clients", "available_tools")
