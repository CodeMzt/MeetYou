from __future__ import annotations

from uuid import uuid4

from core.db.repositories import (
    DeliveryAttemptRepository,
    EndpointCapabilityRepository,
    EndpointConnectionRepository,
    EndpointOutboxRepository,
    EndpointRepository,
)
from core.services.base import ServiceBase


class EndpointRegistryService(ServiceBase):
    def ensure_endpoint(
        self,
        *,
        endpoint_id: str,
        endpoint_type: str,
        provider_type: str,
        transport_type: str,
        owner_actor_id=None,
        workspace_scope: list | None = None,
        status: str = "active",
        labels: list | None = None,
        priority: int = 100,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return EndpointRepository(session).upsert(
                endpoint_id=endpoint_id,
                endpoint_type=endpoint_type,
                provider_type=provider_type,
                transport_type=transport_type,
                owner_actor_id=owner_actor_id,
                workspace_scope=workspace_scope,
                status=status,
                labels=labels,
                priority=priority,
                metadata=metadata,
            )

    def get_by_endpoint_id(self, endpoint_id: str):
        with self.session_scope() as session:
            return EndpointRepository(session).get_by_endpoint_id(endpoint_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return EndpointRepository(session).get_by_id(row_id)

    def list_all(self):
        with self.session_scope() as session:
            return EndpointRepository(session).list_all()

    def set_status(self, *, endpoint_id: str, status: str):
        with self.session_scope() as session:
            return EndpointRepository(session).set_status(endpoint_id=endpoint_id, status=status)


class EndpointConnectionService(ServiceBase):
    def upsert_connection(
        self,
        *,
        endpoint_row_id,
        connection_id: str | None = None,
        transport: str = "websocket",
        protocol_version: str = "meetyou.endpoint.ws.v4",
        status: str = "connected",
        remote_addr: str = "",
        subscriptions: list | None = None,
        capability_snapshot: dict | None = None,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return EndpointConnectionRepository(session).upsert(
                connection_id=connection_id or f"conn_{uuid4().hex}",
                endpoint_id=endpoint_row_id,
                transport=transport,
                protocol_version=protocol_version,
                status=status,
                remote_addr=remote_addr,
                subscriptions=subscriptions,
                capability_snapshot=capability_snapshot,
                metadata=metadata,
            )

    def heartbeat(self, *, connection_id: str, metadata: dict | None = None):
        with self.session_scope() as session:
            return EndpointConnectionRepository(session).update_heartbeat(
                connection_id=connection_id,
                status="connected",
                metadata=metadata,
            )

    def mark_disconnected(self, *, connection_id: str):
        with self.session_scope() as session:
            return EndpointConnectionRepository(session).mark_disconnected(connection_id=connection_id)


class EndpointCapabilityService(ServiceBase):
    def upsert_capability(
        self,
        *,
        endpoint_row_id,
        tool_key: str,
        capability_id: str = "",
        schema: dict | None = None,
        risk_level: str = "read",
        requires_confirmation: bool = False,
        enabled: bool = True,
        constraints: dict | None = None,
        metadata: dict | None = None,
    ):
        normalized_tool_key = str(tool_key or "").strip()
        with self.session_scope() as session:
            return EndpointCapabilityRepository(session).upsert(
                endpoint_id=endpoint_row_id,
                tool_key=normalized_tool_key,
                capability_id=capability_id or f"endpoint.{endpoint_row_id}.{normalized_tool_key}",
                schema=schema,
                risk_level=risk_level,
                requires_confirmation=requires_confirmation,
                enabled=enabled,
                constraints=constraints,
                metadata=metadata,
            )

    def replace_snapshot(self, *, endpoint_row_id, endpoint_public_id: str, capabilities: list[dict]) -> int:
        count = 0
        with self.session_scope() as session:
            repo = EndpointCapabilityRepository(session)
            for item in capabilities or []:
                tool_key = str(item.get("tool_key") or item.get("name") or "").strip()
                if not tool_key:
                    continue
                repo.upsert(
                    endpoint_id=endpoint_row_id,
                    tool_key=tool_key,
                    capability_id=str(item.get("capability_id") or item.get("tool_id") or f"endpoint.{endpoint_public_id}.{tool_key}"),
                    schema=item.get("schema") if isinstance(item.get("schema"), dict) else item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {},
                    risk_level=str(item.get("risk_level") or "read"),
                    requires_confirmation=bool(item.get("requires_confirmation", False)),
                    enabled=bool(item.get("enabled", True)),
                    constraints=item.get("constraints") if isinstance(item.get("constraints"), dict) else {},
                    metadata={k: v for k, v in dict(item).items() if k not in {"schema", "input_schema"}},
                )
                count += 1
        return count

    def get_by_capability_id(self, capability_id: str):
        with self.session_scope() as session:
            return EndpointCapabilityRepository(session).get_by_capability_id(capability_id)

    def list_for_endpoint(self, *, endpoint_row_id):
        with self.session_scope() as session:
            return EndpointCapabilityRepository(session).list_for_endpoint(endpoint_id=endpoint_row_id)

    def list_enabled_for_tool(self, *, tool_key: str):
        with self.session_scope() as session:
            return EndpointCapabilityRepository(session).list_enabled_for_tool(tool_key=tool_key)


class EndpointOutboxService(ServiceBase):
    def enqueue(
        self,
        *,
        target_endpoint_id,
        message_type: str,
        payload: dict,
        available_at=None,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return EndpointOutboxRepository(session).create(
                outbox_id=f"outbox_{uuid4().hex}",
                target_endpoint_id=target_endpoint_id,
                message_type=message_type,
                payload=payload,
                available_at=available_at,
                metadata=metadata,
            )


class DeliveryAttemptService(ServiceBase):
    def record(
        self,
        *,
        target_endpoint_id,
        message_type: str,
        payload: dict,
        status: str = "pending",
        outbox_id=None,
        error: dict | None = None,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return DeliveryAttemptRepository(session).create(
                delivery_id=f"delivery_{uuid4().hex}",
                outbox_id=outbox_id,
                target_endpoint_id=target_endpoint_id,
                message_type=message_type,
                payload=payload,
                status=status,
                error=error,
                metadata=metadata,
            )
