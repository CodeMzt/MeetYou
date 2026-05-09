"""v5 projects research artifacts and conversation versioning

Revision ID: 20260506_000016
Revises: 20260505_000015
Create Date: 2026-05-06
"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260506_000016"
down_revision = "20260505_000015"
branch_labels = None
depends_on = None


UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", UUID, nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("memory_scope", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_projects_principal"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_projects_workspace"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_projects_project_id"),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("artifact_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", UUID, nullable=False),
        sa.Column("project_id", UUID, nullable=True),
        sa.Column("thread_id", UUID, nullable=True),
        sa.Column("created_by_run_id", UUID, nullable=True),
        sa.Column("artifact_type", sa.String(length=64), nullable=False, server_default="document"),
        sa.Column("storage_backend", sa.String(length=64), nullable=False, server_default="local"),
        sa.Column("storage_key", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("filename", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("content_type", sa.String(length=128), nullable=False, server_default="application/octet-stream"),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_artifacts_principal"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_artifacts_project"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_artifacts_thread"),
        sa.ForeignKeyConstraint(["created_by_run_id"], ["runs.id"], name="fk_artifacts_run"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", name="uq_artifacts_artifact_id"),
    )
    op.create_table(
        "thread_branches",
        sa.Column("id", UUID, nullable=False),
        sa.Column("branch_id", sa.String(length=128), nullable=False),
        sa.Column("thread_id", UUID, nullable=False),
        sa.Column("parent_branch_id", UUID, nullable=True),
        sa.Column("root_message_id", UUID, nullable=True),
        sa.Column("current_leaf_message_id", UUID, nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_thread_branches_thread"),
        sa.ForeignKeyConstraint(["parent_branch_id"], ["thread_branches.id"], name="fk_thread_branches_parent"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", name="uq_thread_branches_branch_id"),
    )
    op.create_table(
        "project_sources",
        sa.Column("id", UUID, nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("principal_id", UUID, nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False, server_default="note"),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_type", sa.String(length=64), nullable=False, server_default="text"),
        sa.Column("source_thread_id", UUID, nullable=True),
        sa.Column("source_message_id", UUID, nullable=True),
        sa.Column("artifact_id", UUID, nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_project_sources_project"),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_project_sources_principal"),
        sa.ForeignKeyConstraint(["source_thread_id"], ["threads.id"], name="fk_project_sources_thread"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], name="fk_project_sources_message"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], name="fk_project_sources_artifact"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", name="uq_project_sources_source_id"),
    )
    op.create_table(
        "conversation_checkpoints",
        sa.Column("id", UUID, nullable=False),
        sa.Column("checkpoint_id", sa.String(length=128), nullable=False),
        sa.Column("thread_id", UUID, nullable=False),
        sa.Column("branch_id", UUID, nullable=True),
        sa.Column("message_id", UUID, nullable=True),
        sa.Column("run_id", UUID, nullable=True),
        sa.Column("checkpoint_type", sa.String(length=64), nullable=False, server_default="manual"),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("state", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_conversation_checkpoints_thread"),
        sa.ForeignKeyConstraint(["branch_id"], ["thread_branches.id"], name="fk_conversation_checkpoints_branch"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], name="fk_conversation_checkpoints_message"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name="fk_conversation_checkpoints_run"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checkpoint_id", name="uq_conversation_checkpoints_checkpoint_id"),
    )
    op.create_table(
        "research_tasks",
        sa.Column("id", UUID, nullable=False),
        sa.Column("research_task_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", UUID, nullable=False),
        sa.Column("project_id", UUID, nullable=True),
        sa.Column("thread_id", UUID, nullable=True),
        sa.Column("run_id", UUID, nullable=True),
        sa.Column("artifact_id", UUID, nullable=True),
        sa.Column("topic", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
        sa.Column("plan", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("source_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("evidence_ledger", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("output_format", sa.String(length=32), nullable=False, server_default="markdown"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], name="fk_research_tasks_principal"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_research_tasks_project"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_research_tasks_thread"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name="fk_research_tasks_run"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], name="fk_research_tasks_artifact"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("research_task_id", name="uq_research_tasks_research_task_id"),
    )

    op.add_column("threads", sa.Column("project_id", UUID, nullable=True))
    op.add_column("threads", sa.Column("active_branch_id", UUID, nullable=True))
    op.add_column("threads", sa.Column("current_leaf_message_id", UUID, nullable=True))
    op.create_foreign_key("fk_threads_project", "threads", "projects", ["project_id"], ["id"])

    op.add_column("messages", sa.Column("parent_message_id", UUID, nullable=True))
    op.add_column("messages", sa.Column("branch_id", UUID, nullable=True))
    op.add_column("messages", sa.Column("revision_of_message_id", UUID, nullable=True))
    op.add_column("messages", sa.Column("variant_index", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("messages", sa.Column("visibility", sa.String(length=32), nullable=False, server_default="active"))
    op.create_foreign_key("fk_messages_parent_message", "messages", "messages", ["parent_message_id"], ["id"])
    op.create_foreign_key("fk_messages_branch", "messages", "thread_branches", ["branch_id"], ["id"])
    op.create_foreign_key("fk_messages_revision_of", "messages", "messages", ["revision_of_message_id"], ["id"])

    _backfill_default_thread_branches()


def _backfill_default_thread_branches() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    thread_rows = conn.execute(sa.text("SELECT id, thread_id FROM threads ORDER BY created_at ASC, id ASC")).mappings().all()
    branch_insert = sa.text(
        """
        INSERT INTO thread_branches (
            id, branch_id, thread_id, parent_branch_id, root_message_id, current_leaf_message_id,
            title, status, metadata, created_at, updated_at
        )
        VALUES (
            :id, :branch_id, :thread_id, NULL, NULL, :current_leaf_message_id,
            'Default', 'active', :metadata, :created_at, :updated_at
        )
        """
    ).bindparams(sa.bindparam("metadata", type_=sa.JSON()))
    for thread in thread_rows:
        branch_id = uuid.uuid4()
        message_rows = conn.execute(
            sa.text("SELECT id, message_id FROM messages WHERE thread_id = :thread_id ORDER BY created_at ASC, id ASC"),
            {"thread_id": thread["id"]},
        ).mappings().all()
        leaf_message_id = message_rows[-1]["id"] if message_rows else None
        conn.execute(
            branch_insert,
            {
                "id": branch_id,
                "branch_id": f"br_{uuid.uuid4().hex}",
                "thread_id": thread["id"],
                "current_leaf_message_id": leaf_message_id,
                "metadata": {"default_branch": True, "created_by": "v5_migration"},
                "created_at": now,
                "updated_at": now,
            },
        )
        previous_message_id = None
        for message in message_rows:
            conn.execute(
                sa.text(
                    """
                    UPDATE messages
                    SET branch_id = :branch_id, parent_message_id = :parent_message_id
                    WHERE id = :message_id
                    """
                ),
                {
                    "branch_id": branch_id,
                    "parent_message_id": previous_message_id,
                    "message_id": message["id"],
                },
            )
            previous_message_id = message["id"]
        conn.execute(
            sa.text(
                """
                UPDATE threads
                SET active_branch_id = :branch_id, current_leaf_message_id = :leaf_message_id
                WHERE id = :thread_id
                """
            ),
            {
                "branch_id": branch_id,
                "leaf_message_id": leaf_message_id,
                "thread_id": thread["id"],
            },
        )


def downgrade() -> None:
    op.drop_constraint("fk_messages_revision_of", "messages", type_="foreignkey")
    op.drop_constraint("fk_messages_branch", "messages", type_="foreignkey")
    op.drop_constraint("fk_messages_parent_message", "messages", type_="foreignkey")
    op.drop_column("messages", "visibility")
    op.drop_column("messages", "variant_index")
    op.drop_column("messages", "revision_of_message_id")
    op.drop_column("messages", "branch_id")
    op.drop_column("messages", "parent_message_id")

    op.drop_constraint("fk_threads_project", "threads", type_="foreignkey")
    op.drop_column("threads", "current_leaf_message_id")
    op.drop_column("threads", "active_branch_id")
    op.drop_column("threads", "project_id")

    op.drop_table("research_tasks")
    op.drop_table("conversation_checkpoints")
    op.drop_table("project_sources")
    op.drop_table("thread_branches")
    op.drop_table("artifacts")
    op.drop_table("projects")
