from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class Thread(TimestampMixin, Base):
    __tablename__ = "threads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("principals.id"), nullable=False)
    home_workspace_id: Mapped[uuid.UUID] = mapped_column("workspace_id", UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    pinned_procedure_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("procedures.procedure_id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)

    @property
    def workspace_id(self):
        return self.home_workspace_id

    @workspace_id.setter
    def workspace_id(self, value) -> None:
        self.home_workspace_id = value
