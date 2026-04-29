from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class Session(TimestampMixin, Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("threads.id"), nullable=False)
    origin_endpoint_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("endpoints.id"), nullable=True)
    active_workspace_id: Mapped[uuid.UUID] = mapped_column("workspace_id", UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)

    @property
    def workspace_id(self):
        return self.active_workspace_id

    @workspace_id.setter
    def workspace_id(self, value) -> None:
        self.active_workspace_id = value
