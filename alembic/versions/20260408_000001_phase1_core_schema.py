"""phase1 core schema

Revision ID: 20260408_000001
Revises:
Create Date: 2026-04-08 16:20:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260408_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "principals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("principal_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("principal_key", name="uq_principals_principal_key"),
    )
    op.create_table(
        "clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("client_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_type", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_clients_principal_id_principals"),
        sa.UniqueConstraint("client_id", name="uq_clients_client_id"),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("base_mode", sa.String(length=64), nullable=False),
        sa.Column("prompt_overlay", sa.Text(), nullable=False),
        sa.Column("default_execution_target", sa.String(length=64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_workspaces_principal_id_principals"),
        sa.UniqueConstraint("workspace_id", name="uq_workspaces_workspace_id"),
    )
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_type", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("transport_profile", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("host_name", sa.String(length=255), nullable=False),
        sa.Column("host_os", sa.String(length=64), nullable=False),
        sa.Column("host_arch", sa.String(length=64), nullable=False),
        sa.Column("supports_offline_cache", sa.Boolean(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_agents_principal_id_principals"),
        sa.UniqueConstraint("agent_id", name="uq_agents_agent_id"),
    )
    op.create_table(
        "agent_capability_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], name="fk_agent_capability_snapshots_agent_id_agents"),
    )
    op.create_table(
        "workspace_agent_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_role", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_workspace_agent_memberships_workspace_id_workspaces"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], name="fk_workspace_agent_memberships_agent_id_agents"),
        sa.UniqueConstraint("workspace_id", "agent_id", name="uq_workspace_agent_memberships_workspace_id"),
    )
    op.create_table(
        "capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("capability_id", sa.String(length=255), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("provider_ref", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False),
        sa.Column("availability", sa.String(length=32), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("capability_id", name="uq_capabilities_capability_id"),
    )
    op.create_table(
        "capability_workspace_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("capability_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["capability_id"], ["capabilities.id"], name="fk_capability_workspace_bindings_capability_id_capabilities"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_capability_workspace_bindings_workspace_id_workspaces"),
        sa.UniqueConstraint("capability_id", "workspace_id", name="uq_capability_workspace_bindings_capability_id"),
    )
    op.create_table(
        "threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_threads_principal_id_principals"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_threads_workspace_id_workspaces"),
        sa.UniqueConstraint("thread_id", name="uq_threads_thread_id"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_sessions_thread_id_threads"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name="fk_sessions_client_id_clients"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_sessions_workspace_id_workspaces"),
        sa.UniqueConstraint("session_id", name="uq_sessions_session_id"),
    )
    op.create_table(
        "operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("operation_id", sa.String(length=128), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_by_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operation_type", sa.String(length=64), nullable=False),
        sa.Column("execution_target", sa.String(length=64), nullable=False),
        sa.Column("target_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_operations_thread_id_threads"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_operations_workspace_id_workspaces"),
        sa.ForeignKeyConstraint(["requested_by_client_id"], ["clients.id"], name="fk_operations_requested_by_client_id_clients"),
        sa.ForeignKeyConstraint(["requested_by_session_id"], ["sessions.id"], name="fk_operations_requested_by_session_id_sessions"),
        sa.ForeignKeyConstraint(["target_agent_id"], ["agents.id"], name="fk_operations_target_agent_id_agents"),
        sa.UniqueConstraint("operation_id", name="uq_operations_operation_id"),
    )
    op.create_table(
        "operation_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("call_id", sa.String(length=128), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["operation_id"], ["operations.id"], name="fk_operation_calls_operation_id_operations"),
        sa.ForeignKeyConstraint(["capability_id"], ["capabilities.id"], name="fk_operation_calls_capability_id_capabilities"),
        sa.ForeignKeyConstraint(["target_agent_id"], ["agents.id"], name="fk_operation_calls_target_agent_id_agents"),
        sa.UniqueConstraint("call_id", name="uq_operation_calls_call_id"),
    )
    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("approval_id", sa.String(length=128), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_type", sa.String(length=64), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_by_client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["operation_id"], ["operations.id"], name="fk_approvals_operation_id_operations"),
        sa.ForeignKeyConstraint(["decided_by_client_id"], ["clients.id"], name="fk_approvals_decided_by_client_id_clients"),
        sa.UniqueConstraint("approval_id", name="uq_approvals_approval_id"),
    )
    op.create_table(
        "attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("attachment_id", sa.String(length=128), nullable=False),
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("origin_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("origin_client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("storage_class", sa.String(length=32), nullable=False),
        sa.Column("lifecycle_policy", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.String(length=64), nullable=True),
        sa.Column("sha256", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["origin_agent_id"], ["agents.id"], name="fk_attachments_origin_agent_id_agents"),
        sa.ForeignKeyConstraint(["origin_client_id"], ["clients.id"], name="fk_attachments_origin_client_id_clients"),
        sa.UniqueConstraint("attachment_id", name="uq_attachments_attachment_id"),
    )
    op.create_table(
        "attachment_upload_tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("ticket_id", sa.String(length=128), nullable=False),
        sa.Column("attachment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issuer_type", sa.String(length=32), nullable=False),
        sa.Column("issuer_ref", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.String(length=64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["attachments.id"], name="fk_attachment_upload_tickets_attachment_id_attachments"),
        sa.UniqueConstraint("ticket_id", name="uq_attachment_upload_tickets_ticket_id"),
    )


def downgrade() -> None:
    op.drop_table("attachment_upload_tickets")
    op.drop_table("attachments")
    op.drop_table("approvals")
    op.drop_table("operation_calls")
    op.drop_table("operations")
    op.drop_table("sessions")
    op.drop_table("threads")
    op.drop_table("capability_workspace_bindings")
    op.drop_table("capabilities")
    op.drop_table("workspace_agent_memberships")
    op.drop_table("agent_capability_snapshots")
    op.drop_table("agents")
    op.drop_table("workspaces")
    op.drop_table("clients")
    op.drop_table("principals")
