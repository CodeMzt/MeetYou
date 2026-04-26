from __future__ import annotations

import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class Client(TimestampMixin, Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("principals.id"), nullable=False)
    client_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    capabilities: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    available_tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    executable_tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    transport_profile: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    host_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    host_os: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    host_arch: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    last_seen_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class ClientWorkspaceMembership(TimestampMixin, Base):
    __tablename__ = "client_workspace_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "client_id", name="uq_client_workspace_memberships_workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    membership_role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
