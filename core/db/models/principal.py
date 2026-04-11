from __future__ import annotations

import uuid

from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class Principal(TimestampMixin, Base):
    __tablename__ = "principals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    principal_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
