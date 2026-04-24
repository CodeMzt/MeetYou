"""workspace memberships and context pool

Revision ID: 20260424_000008
Revises: 20260409_000007
Create Date: 2026-04-24 12:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260424_000008"
down_revision = "20260409_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("active_workspace_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_messages_active_workspace_id_workspaces",
        "messages",
        "workspaces",
        ["active_workspace_id"],
        ["id"],
    )

    op.create_table(
        "client_workspace_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_role", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_client_workspace_memberships_workspace_id_workspaces"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name="fk_client_workspace_memberships_client_id_clients"),
        sa.UniqueConstraint("workspace_id", "client_id", name="uq_client_workspace_memberships_workspace_id"),
    )
    op.create_table(
        "context_pool_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("context_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("home_workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active_workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("canonical_text", sa.Text(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("workspace_tags", sa.JSON(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_context_pool_items_principal_id_principals"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_context_pool_items_thread_id_threads"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], name="fk_context_pool_items_session_id_sessions"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], name="fk_context_pool_items_message_id_messages"),
        sa.ForeignKeyConstraint(["source_client_id"], ["clients.id"], name="fk_context_pool_items_source_client_id_clients"),
        sa.ForeignKeyConstraint(["source_agent_id"], ["agents.id"], name="fk_context_pool_items_source_agent_id_agents"),
        sa.ForeignKeyConstraint(["home_workspace_id"], ["workspaces.id"], name="fk_context_pool_items_home_workspace_id_workspaces"),
        sa.ForeignKeyConstraint(["active_workspace_id"], ["workspaces.id"], name="fk_context_pool_items_active_workspace_id_workspaces"),
        sa.UniqueConstraint("context_id", name="uq_context_pool_items_context_id"),
    )


def downgrade() -> None:
    op.drop_table("context_pool_items")
    op.drop_table("client_workspace_memberships")
    op.drop_constraint("fk_messages_active_workspace_id_workspaces", "messages", type_="foreignkey")
    op.drop_column("messages", "active_workspace_id")
