from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class ContextPoolItem(TimestampMixin, Base):
    __tablename__ = "context_pool_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    context_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("principals.id"), nullable=False)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("threads.id"), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=True)
    source_client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True)
    home_workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    active_workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False, default="turn")
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    canonical_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    workspace_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    embedding: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
