"""remove legacy client domain ownership

Revision ID: 20260429_000012
Revises: 20260428_000011
Create Date: 2026-04-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260429_000012"
down_revision = "20260428_000011"
branch_labels = None
depends_on = None


def _constraint_exists_sql(name: str) -> str:
    return f"SELECT 1 FROM pg_constraint WHERE conname = '{name}'"


def _add_fk_if_missing(table: str, constraint: str, column: str, target_table: str, target_column: str = "id") -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS ({_constraint_exists_sql(constraint)}) THEN
                    ALTER TABLE "{table}"
                    ADD CONSTRAINT "{constraint}"
                    FOREIGN KEY ("{column}") REFERENCES "{target_table}" ("{target_column}");
                END IF;
            END $$;
            """
        )
    )


def _drop_constraint(table: str, constraint: str) -> None:
    op.execute(sa.text(f'ALTER TABLE IF EXISTS "{table}" DROP CONSTRAINT IF EXISTS "{constraint}"'))


def upgrade() -> None:
    op.execute(sa.text("UPDATE workspaces SET default_execution_target = 'core.local' WHERE default_execution_target = 'core_only'"))
    op.execute(sa.text("UPDATE workspaces SET default_execution_target = 'endpoint' WHERE default_execution_target = 'specific_endpoint'"))
    op.execute(sa.text("UPDATE tasks SET execution_target = 'core.local' WHERE execution_target = 'core_only'"))
    op.execute(sa.text("UPDATE tasks SET execution_target = 'endpoint' WHERE execution_target = 'specific_endpoint'"))
    op.execute(sa.text("UPDATE operations SET execution_target = 'core.local' WHERE execution_target = 'core_only'"))
    op.execute(sa.text("UPDATE operations SET execution_target = 'endpoint' WHERE execution_target = 'specific_endpoint'"))

    op.add_column(
        "approvals",
        sa.Column("decided_by_actor_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _add_fk_if_missing("approvals", "fk_approvals_decided_by_actor_id_actors", "decided_by_actor_id", "actors")

    op.add_column(
        "attachments",
        sa.Column("origin_endpoint_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    _add_fk_if_missing("attachments", "fk_attachments_origin_endpoint_id_endpoints", "origin_endpoint_id", "endpoints")

    _drop_constraint("sessions", "fk_sessions_client_id_clients")
    op.execute(sa.text('ALTER TABLE IF EXISTS "sessions" DROP COLUMN IF EXISTS "client_id"'))

    _drop_constraint("operations", "fk_operations_requested_by_client_id_clients")
    op.execute(sa.text('ALTER TABLE IF EXISTS "operations" DROP COLUMN IF EXISTS "requested_by_client_id"'))

    _drop_constraint("approvals", "fk_approvals_decided_by_client_id_clients")
    op.execute(sa.text('ALTER TABLE IF EXISTS "approvals" DROP COLUMN IF EXISTS "decided_by_client_id"'))

    _drop_constraint("attachments", "fk_attachments_origin_client_id_clients")
    op.execute(sa.text('ALTER TABLE IF EXISTS "attachments" DROP COLUMN IF EXISTS "origin_client_id"'))

    op.execute(sa.text('DROP TABLE IF EXISTS "client_workspace_memberships"'))
    op.execute(sa.text('DROP TABLE IF EXISTS "clients"'))


def downgrade() -> None:
    op.execute(sa.text("UPDATE workspaces SET default_execution_target = 'core_only' WHERE default_execution_target = 'core.local'"))
    op.execute(sa.text("UPDATE workspaces SET default_execution_target = 'specific_endpoint' WHERE default_execution_target = 'endpoint'"))
    op.execute(sa.text("UPDATE tasks SET execution_target = 'core_only' WHERE execution_target = 'core.local'"))
    op.execute(sa.text("UPDATE tasks SET execution_target = 'specific_endpoint' WHERE execution_target = 'endpoint'"))
    op.execute(sa.text("UPDATE operations SET execution_target = 'core_only' WHERE execution_target = 'core.local'"))
    op.execute(sa.text("UPDATE operations SET execution_target = 'specific_endpoint' WHERE execution_target = 'endpoint'"))

    op.create_table(
        "clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_type", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="online"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_clients_principal_id_principals"),
        sa.UniqueConstraint("client_id", name="uq_clients_client_id"),
    )
    op.create_table(
        "client_workspace_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_role", sa.String(length=64), nullable=False, server_default="member"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_client_workspace_memberships_workspace_id_workspaces"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name="fk_client_workspace_memberships_client_id_clients"),
        sa.UniqueConstraint("workspace_id", "client_id", name="uq_client_workspace_memberships_workspace_id"),
    )
    op.add_column("sessions", sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True))
    _add_fk_if_missing("sessions", "fk_sessions_client_id_clients", "client_id", "clients")
    op.add_column("operations", sa.Column("requested_by_client_id", postgresql.UUID(as_uuid=True), nullable=True))
    _add_fk_if_missing("operations", "fk_operations_requested_by_client_id_clients", "requested_by_client_id", "clients")
    op.add_column("approvals", sa.Column("decided_by_client_id", postgresql.UUID(as_uuid=True), nullable=True))
    _add_fk_if_missing("approvals", "fk_approvals_decided_by_client_id_clients", "decided_by_client_id", "clients")
    op.add_column("attachments", sa.Column("origin_client_id", postgresql.UUID(as_uuid=True), nullable=True))
    _add_fk_if_missing("attachments", "fk_attachments_origin_client_id_clients", "origin_client_id", "clients")
    _drop_constraint("approvals", "fk_approvals_decided_by_actor_id_actors")
    op.execute(sa.text('ALTER TABLE IF EXISTS "approvals" DROP COLUMN IF EXISTS "decided_by_actor_id"'))
    _drop_constraint("attachments", "fk_attachments_origin_endpoint_id_endpoints")
    op.execute(sa.text('ALTER TABLE IF EXISTS "attachments" DROP COLUMN IF EXISTS "origin_endpoint_id"'))
