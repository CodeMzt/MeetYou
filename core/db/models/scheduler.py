from __future__ import annotations

import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class ScheduledJob(TimestampMixin, Base):
    __tablename__ = "scheduled_jobs"
    __table_args__ = (UniqueConstraint("singleton_key", name="uq_scheduled_jobs_singleton_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    singleton_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deletable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    editable_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    trigger_type: Mapped[str] = mapped_column(String(64), nullable=False, default="interval")
    trigger_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    action_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    run_template: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    delivery_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    concurrency_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    misfire_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    next_fire_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fire_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    lease_until_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class ScheduledJobRun(TimestampMixin, Base):
    __tablename__ = "scheduled_job_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_run_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scheduled_jobs.id"), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id"), nullable=True)
    scheduled_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    error: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
