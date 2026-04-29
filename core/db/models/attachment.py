from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class Attachment(TimestampMixin, Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attachment_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    origin_endpoint_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("endpoints.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_class: Mapped[str] = mapped_column(String(32), nullable=False, default="standard")
    lifecycle_policy: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    expires_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sha256: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class AttachmentUploadTicket(TimestampMixin, Base):
    __tablename__ = "attachment_upload_tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    attachment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("attachments.id"), nullable=False)
    issuer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    issuer_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="issued")
    expires_at: Mapped[str] = mapped_column(String(64), nullable=False)
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
