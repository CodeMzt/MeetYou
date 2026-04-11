from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class RuntimeStateBlob(TimestampMixin, Base):
    __tablename__ = "runtime_state_blobs"
    __table_args__ = (UniqueConstraint("principal_id", "state_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    principal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("principals.id"), nullable=False)
    state_key: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
