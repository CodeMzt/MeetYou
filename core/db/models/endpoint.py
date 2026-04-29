from __future__ import annotations

import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, TimestampMixin


class Endpoint(TimestampMixin, Base):
    __tablename__ = "endpoints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    endpoint_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    endpoint_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    transport_type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("actors.id"), nullable=True)
    workspace_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    labels: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class EndpointConnection(TimestampMixin, Base):
    __tablename__ = "endpoint_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("endpoints.id"), nullable=False)
    transport: Mapped[str] = mapped_column(String(64), nullable=False, default="websocket")
    protocol_version: Mapped[str] = mapped_column(String(64), nullable=False, default="meetyou.endpoint.ws.v4")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="connected")
    last_seen_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remote_addr: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    subscriptions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    capability_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class EndpointCapability(TimestampMixin, Base):
    __tablename__ = "endpoint_capabilities"
    __table_args__ = (UniqueConstraint("endpoint_id", "tool_key", name="uq_endpoint_capabilities_endpoint_tool"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("endpoints.id"), nullable=False)
    tool_key: Mapped[str] = mapped_column(String(255), nullable=False)
    schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="read")
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    constraints: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class EndpointAddress(TimestampMixin, Base):
    __tablename__ = "endpoint_addresses"
    __table_args__ = (
        UniqueConstraint("address_id", name="uq_endpoint_addresses_address_id"),
        UniqueConstraint("endpoint_id", "address_type", "external_ref", name="uq_endpoint_addresses_endpoint_type_external_ref"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    address_id: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("endpoints.id"), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    address_type: Mapped[str] = mapped_column(String(64), nullable=False, default="direct")
    external_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    workspace_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    capabilities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    last_seen_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class ActorDeliveryPreference(TimestampMixin, Base):
    __tablename__ = "actor_delivery_preferences"
    __table_args__ = (
        UniqueConstraint("preference_id", name="uq_actor_delivery_preferences_preference_id"),
        UniqueConstraint("actor_id", "provider_type", "alias", name="uq_actor_delivery_preferences_actor_provider_alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    preference_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("actors.id"), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    address_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("endpoint_addresses.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(128), nullable=False, default="me")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class EndpointOutbox(TimestampMixin, Base):
    __tablename__ = "endpoint_outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outbox_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    target_endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("endpoints.id"), nullable=False)
    target_address_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("endpoint_addresses.id"), nullable=True)
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    available_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class DeliveryAttempt(TimestampMixin, Base):
    __tablename__ = "delivery_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    outbox_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("endpoint_outbox.id"), nullable=True)
    target_endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("endpoints.id"), nullable=False)
    target_address_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("endpoint_addresses.id"), nullable=True)
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    meta: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
