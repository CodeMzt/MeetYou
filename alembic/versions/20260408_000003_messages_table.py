"""messages table

Revision ID: 20260408_000003
Revises: 20260408_000002
Create Date: 2026-04-08 18:20:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260408_000003"
down_revision = "20260408_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_messages_thread_id_threads"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], name="fk_messages_session_id_sessions"),
        sa.ForeignKeyConstraint(["source_client_id"], ["clients.id"], name="fk_messages_source_client_id_clients"),
        sa.UniqueConstraint("message_id", name="uq_messages_message_id"),
    )


def downgrade() -> None:
    op.drop_table("messages")
