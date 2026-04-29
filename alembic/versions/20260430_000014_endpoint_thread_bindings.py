"""endpoint thread bindings

Revision ID: 20260430_000014
Revises: 20260429_000013
Create Date: 2026-04-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260430_000014"
down_revision = "20260429_000013"
branch_labels = None
depends_on = None


UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "endpoint_thread_bindings",
        sa.Column("id", UUID, nullable=False),
        sa.Column("binding_id", sa.String(length=255), nullable=False),
        sa.Column("endpoint_id", UUID, nullable=False),
        sa.Column("thread_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("address_id", UUID, nullable=True),
        sa.Column("thread_strategy", sa.String(length=64), nullable=False),
        sa.Column("conversation_key", sa.String(length=512), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["address_id"], ["endpoint_addresses.id"], name="fk_endpoint_thread_bindings_address_id_endpoint_addresses"),
        sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.id"], name="fk_endpoint_thread_bindings_endpoint_id_endpoints"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_endpoint_thread_bindings_thread_id_threads"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_endpoint_thread_bindings_workspace_id_workspaces"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("binding_id", name="uq_endpoint_thread_bindings_binding_id"),
        sa.UniqueConstraint("endpoint_id", "thread_strategy", "conversation_key", name="uq_endpoint_thread_bindings_endpoint_strategy_key"),
    )


def downgrade() -> None:
    op.drop_table("endpoint_thread_bindings")
