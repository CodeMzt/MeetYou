from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class TaskState(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("principals.id"), nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    scope_user_id: Mapped[str] = mapped_column(String(128), nullable=False, default="global")
    scope_session_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, default="task")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    execution_target: Mapped[str] = mapped_column(String(64), nullable=False, default="core.local")
    due_at: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    next_run_at: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    raw_record: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
