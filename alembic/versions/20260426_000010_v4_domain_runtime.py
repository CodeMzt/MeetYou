"""v4 domain runtime

Revision ID: 20260426_000010
Revises: 20260425_000009
Create Date: 2026-04-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260426_000010"
down_revision = "20260425_000009"
branch_labels = None
depends_on = None


UUID = postgresql.UUID(as_uuid=True)


def _drop_constraint_if_exists(table: str, constraint: str) -> None:
    op.execute(sa.text(f'ALTER TABLE IF EXISTS "{table}" DROP CONSTRAINT IF EXISTS "{constraint}"'))


def upgrade() -> None:
    op.create_table(
        "actors",
        sa.Column("id", UUID, nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("actor_type", sa.String(length=64), nullable=False),
        sa.Column("owner_user_id", sa.String(length=128), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("permission_profile_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_id", name="uq_actors_actor_id"),
    )
    op.create_table(
        "endpoints",
        sa.Column("id", UUID, nullable=False),
        sa.Column("endpoint_id", sa.String(length=255), nullable=False),
        sa.Column("endpoint_type", sa.String(length=64), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("transport_type", sa.String(length=64), nullable=False),
        sa.Column("owner_actor_id", UUID, nullable=True),
        sa.Column("workspace_scope", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("labels", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_actor_id"], ["actors.id"], name="fk_endpoints_owner_actor_id_actors"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint_id", name="uq_endpoints_endpoint_id"),
    )
    op.create_table(
        "endpoint_connections",
        sa.Column("id", UUID, nullable=False),
        sa.Column("connection_id", sa.String(length=128), nullable=False),
        sa.Column("endpoint_id", UUID, nullable=False),
        sa.Column("transport", sa.String(length=64), nullable=False, server_default="websocket"),
        sa.Column("protocol_version", sa.String(length=64), nullable=False, server_default="meetyou.endpoint.ws.v4"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="connected"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remote_addr", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("subscriptions", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("capability_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.id"], name="fk_endpoint_connections_endpoint_id_endpoints"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", name="uq_endpoint_connections_connection_id"),
    )
    op.create_table(
        "endpoint_capabilities",
        sa.Column("id", UUID, nullable=False),
        sa.Column("capability_id", sa.String(length=255), nullable=False),
        sa.Column("endpoint_id", UUID, nullable=False),
        sa.Column("tool_key", sa.String(length=255), nullable=False),
        sa.Column("schema", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("risk_level", sa.String(length=32), nullable=False, server_default="read"),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("constraints", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.id"], name="fk_endpoint_capabilities_endpoint_id_endpoints"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capability_id", name="uq_endpoint_capabilities_capability_id"),
        sa.UniqueConstraint("endpoint_id", "tool_key", name="uq_endpoint_capabilities_endpoint_tool"),
    )
    op.create_table(
        "runs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("thread_id", UUID, nullable=True),
        sa.Column("trigger_type", sa.String(length=64), nullable=False),
        sa.Column("origin_actor_id", UUID, nullable=False),
        sa.Column("origin_endpoint_id", UUID, nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("input", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("output", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("execution_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("delivery_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_runs_workspace_id_workspaces"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_runs_thread_id_threads"),
        sa.ForeignKeyConstraint(["origin_actor_id"], ["actors.id"], name="fk_runs_origin_actor_id_actors"),
        sa.ForeignKeyConstraint(["origin_endpoint_id"], ["endpoints.id"], name="fk_runs_origin_endpoint_id_endpoints"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_runs_run_id"),
    )
    op.create_table(
        "run_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("thread_id", UUID, nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("durable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name="fk_run_events_run_id_runs"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_run_events_thread_id_threads"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_run_events_event_id"),
        sa.UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),
    )
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", UUID, nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("singleton_key", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("deletable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("editable_fields", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("trigger_type", sa.String(length=64), nullable=False, server_default="interval"),
        sa.Column("trigger_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("action_ref", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("run_template", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("execution_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("delivery_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("concurrency_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("misfire_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_scheduled_jobs_workspace_id_workspaces"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_scheduled_jobs_job_id"),
        sa.UniqueConstraint("singleton_key", name="uq_scheduled_jobs_singleton_key"),
    )
    op.create_table(
        "scheduled_job_runs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("job_run_id", sa.String(length=128), nullable=False),
        sa.Column("job_id", UUID, nullable=False),
        sa.Column("run_id", UUID, nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("error", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["scheduled_jobs.id"], name="fk_scheduled_job_runs_job_id_scheduled_jobs"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name="fk_scheduled_job_runs_run_id_runs"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_run_id", name="uq_scheduled_job_runs_job_run_id"),
    )
    op.create_table(
        "endpoint_outbox",
        sa.Column("id", UUID, nullable=False),
        sa.Column("outbox_id", sa.String(length=128), nullable=False),
        sa.Column("target_endpoint_id", UUID, nullable=False),
        sa.Column("message_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["target_endpoint_id"], ["endpoints.id"], name="fk_endpoint_outbox_target_endpoint_id_endpoints"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outbox_id", name="uq_endpoint_outbox_outbox_id"),
    )
    op.create_table(
        "delivery_attempts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("delivery_id", sa.String(length=128), nullable=False),
        sa.Column("outbox_id", UUID, nullable=True),
        sa.Column("target_endpoint_id", UUID, nullable=False),
        sa.Column("message_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("error", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["outbox_id"], ["endpoint_outbox.id"], name="fk_delivery_attempts_outbox_id_endpoint_outbox"),
        sa.ForeignKeyConstraint(["target_endpoint_id"], ["endpoints.id"], name="fk_delivery_attempts_target_endpoint_id_endpoints"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id", name="uq_delivery_attempts_delivery_id"),
    )

    op.add_column("messages", sa.Column("run_id", UUID, nullable=True))
    op.add_column("messages", sa.Column("content_type", sa.String(length=64), nullable=False, server_default="text"))
    op.add_column("messages", sa.Column("created_by_actor_id", UUID, nullable=True))
    op.add_column("messages", sa.Column("origin_endpoint_id", UUID, nullable=True))
    op.create_foreign_key("fk_messages_run_id_runs", "messages", "runs", ["run_id"], ["id"])
    op.create_foreign_key("fk_messages_created_by_actor_id_actors", "messages", "actors", ["created_by_actor_id"], ["id"])
    op.create_foreign_key("fk_messages_origin_endpoint_id_endpoints", "messages", "endpoints", ["origin_endpoint_id"], ["id"])
    _drop_constraint_if_exists("messages", "fk_messages_source_client_id_clients")
    op.drop_column("messages", "source_client_id")

    op.add_column("context_pool_items", sa.Column("origin_endpoint_id", UUID, nullable=True))
    op.create_foreign_key("fk_context_pool_items_origin_endpoint_id_endpoints", "context_pool_items", "endpoints", ["origin_endpoint_id"], ["id"])
    _drop_constraint_if_exists("context_pool_items", "fk_context_pool_items_source_client_id_clients")
    op.drop_column("context_pool_items", "source_client_id")

    op.add_column("sessions", sa.Column("origin_endpoint_id", UUID, nullable=True))
    op.alter_column("sessions", "client_id", existing_type=UUID, nullable=True)
    op.create_foreign_key("fk_sessions_origin_endpoint_id_endpoints", "sessions", "endpoints", ["origin_endpoint_id"], ["id"])

    op.add_column("operations", sa.Column("requested_by_actor_id", UUID, nullable=True))
    op.add_column("operations", sa.Column("requested_by_run_id", UUID, nullable=True))
    op.add_column("operations", sa.Column("execution_target_type", sa.String(length=64), nullable=False, server_default="endpoint"))
    op.add_column("operations", sa.Column("execution_target_id", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("operations", sa.Column("target_endpoint_id", UUID, nullable=True))
    op.alter_column("operations", "thread_id", existing_type=UUID, nullable=True)
    op.create_foreign_key("fk_operations_requested_by_actor_id_actors", "operations", "actors", ["requested_by_actor_id"], ["id"])
    op.create_foreign_key("fk_operations_requested_by_run_id_runs", "operations", "runs", ["requested_by_run_id"], ["id"])
    op.create_foreign_key("fk_operations_target_endpoint_id_endpoints", "operations", "endpoints", ["target_endpoint_id"], ["id"])
    _drop_constraint_if_exists("operations", "fk_operations_target_client_id_clients")
    op.drop_column("operations", "target_client_id")

    op.add_column("operation_calls", sa.Column("endpoint_capability_id", UUID, nullable=True))
    op.add_column("operation_calls", sa.Column("target_endpoint_id", UUID, nullable=True))
    op.add_column("operation_calls", sa.Column("execution_target_id", sa.String(length=255), nullable=False, server_default=""))
    op.alter_column("operation_calls", "capability_id", existing_type=UUID, nullable=True)
    op.create_foreign_key("fk_operation_calls_endpoint_capability_id_endpoint_capabilities", "operation_calls", "endpoint_capabilities", ["endpoint_capability_id"], ["id"])
    op.create_foreign_key("fk_operation_calls_target_endpoint_id_endpoints", "operation_calls", "endpoints", ["target_endpoint_id"], ["id"])
    _drop_constraint_if_exists("operation_calls", "fk_operation_calls_target_client_id_clients")
    op.drop_column("operation_calls", "target_client_id")


def downgrade() -> None:
    _drop_constraint_if_exists("sessions", "fk_sessions_origin_endpoint_id_endpoints")
    op.alter_column("sessions", "client_id", existing_type=UUID, nullable=False)
    op.drop_column("sessions", "origin_endpoint_id")

    op.add_column("operation_calls", sa.Column("target_client_id", UUID, nullable=True))
    op.create_foreign_key("fk_operation_calls_target_client_id_clients", "operation_calls", "clients", ["target_client_id"], ["id"])
    _drop_constraint_if_exists("operation_calls", "fk_operation_calls_target_endpoint_id_endpoints")
    _drop_constraint_if_exists("operation_calls", "fk_operation_calls_endpoint_capability_id_endpoint_capabilities")
    op.alter_column("operation_calls", "capability_id", existing_type=UUID, nullable=False)
    op.drop_column("operation_calls", "execution_target_id")
    op.drop_column("operation_calls", "target_endpoint_id")
    op.drop_column("operation_calls", "endpoint_capability_id")

    op.add_column("operations", sa.Column("target_client_id", UUID, nullable=True))
    op.create_foreign_key("fk_operations_target_client_id_clients", "operations", "clients", ["target_client_id"], ["id"])
    _drop_constraint_if_exists("operations", "fk_operations_target_endpoint_id_endpoints")
    _drop_constraint_if_exists("operations", "fk_operations_requested_by_run_id_runs")
    _drop_constraint_if_exists("operations", "fk_operations_requested_by_actor_id_actors")
    op.alter_column("operations", "thread_id", existing_type=UUID, nullable=False)
    op.drop_column("operations", "target_endpoint_id")
    op.drop_column("operations", "execution_target_id")
    op.drop_column("operations", "execution_target_type")
    op.drop_column("operations", "requested_by_run_id")
    op.drop_column("operations", "requested_by_actor_id")

    op.add_column("context_pool_items", sa.Column("source_client_id", UUID, nullable=True))
    op.create_foreign_key("fk_context_pool_items_source_client_id_clients", "context_pool_items", "clients", ["source_client_id"], ["id"])
    _drop_constraint_if_exists("context_pool_items", "fk_context_pool_items_origin_endpoint_id_endpoints")
    op.drop_column("context_pool_items", "origin_endpoint_id")

    op.add_column("messages", sa.Column("source_client_id", UUID, nullable=True))
    op.create_foreign_key("fk_messages_source_client_id_clients", "messages", "clients", ["source_client_id"], ["id"])
    _drop_constraint_if_exists("messages", "fk_messages_origin_endpoint_id_endpoints")
    _drop_constraint_if_exists("messages", "fk_messages_created_by_actor_id_actors")
    _drop_constraint_if_exists("messages", "fk_messages_run_id_runs")
    op.drop_column("messages", "origin_endpoint_id")
    op.drop_column("messages", "created_by_actor_id")
    op.drop_column("messages", "content_type")
    op.drop_column("messages", "run_id")

    op.drop_table("delivery_attempts")
    op.drop_table("endpoint_outbox")
    op.drop_table("scheduled_job_runs")
    op.drop_table("scheduled_jobs")
    op.drop_table("run_events")
    op.drop_table("runs")
    op.drop_table("endpoint_capabilities")
    op.drop_table("endpoint_connections")
    op.drop_table("endpoints")
    op.drop_table("actors")
