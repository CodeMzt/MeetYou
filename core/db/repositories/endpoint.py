from __future__ import annotations

from core.db.base import utcnow
from core.db.models.endpoint import DeliveryAttempt, Endpoint, EndpointCapability, EndpointConnection, EndpointOutbox
from core.db.repositories.base import RepositoryBase


class EndpointRepository(RepositoryBase):
    def upsert(
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
    ) -> Endpoint:
        row = self.get_by_endpoint_id(endpoint_id)
        if row is None:
            row = Endpoint(
                endpoint_id=endpoint_id,
                endpoint_type=endpoint_type,
                provider_type=provider_type,
                transport_type=transport_type,
                owner_actor_id=owner_actor_id,
                workspace_scope=list(workspace_scope or []),
                status=status,
                labels=list(labels or []),
                priority=int(priority or 100),
                meta=dict(metadata or {}),
            )
            self.session.add(row)
        else:
            row.endpoint_type = endpoint_type
            row.provider_type = provider_type
            row.transport_type = transport_type
            row.owner_actor_id = owner_actor_id
            row.workspace_scope = list(workspace_scope or [])
            row.status = status
            row.labels = list(labels or [])
            row.priority = int(priority or 100)
            row.meta = dict(metadata or row.meta or {})
        self.session.flush()
        return row

    def get_by_endpoint_id(self, endpoint_id: str) -> Endpoint | None:
        return self.session.query(Endpoint).filter_by(endpoint_id=endpoint_id).one_or_none()

    def get_by_id(self, row_id) -> Endpoint | None:
        return self.session.query(Endpoint).filter_by(id=row_id).one_or_none()

    def list_all(self) -> list[Endpoint]:
        return list(self.session.query(Endpoint).order_by(Endpoint.endpoint_id.asc()).all())

    def set_status(self, *, endpoint_id: str, status: str) -> Endpoint | None:
        row = self.get_by_endpoint_id(endpoint_id)
        if row is None:
            return None
        row.status = status
        self.session.flush()
        return row


class EndpointConnectionRepository(RepositoryBase):
    def upsert(
        self,
        *,
        connection_id: str,
        endpoint_id,
        transport: str = "websocket",
        protocol_version: str = "meetyou.endpoint.ws.v4",
        status: str = "connected",
        remote_addr: str = "",
        subscriptions: list | None = None,
        capability_snapshot: dict | None = None,
        metadata: dict | None = None,
    ) -> EndpointConnection:
        row = self.get_by_connection_id(connection_id)
        if row is None:
            row = EndpointConnection(
                connection_id=connection_id,
                endpoint_id=endpoint_id,
                transport=transport,
                protocol_version=protocol_version,
                status=status,
                last_seen_at=utcnow(),
                remote_addr=remote_addr,
                subscriptions=list(subscriptions or []),
                capability_snapshot=dict(capability_snapshot or {}),
                meta=dict(metadata or {}),
            )
            self.session.add(row)
        else:
            row.endpoint_id = endpoint_id
            row.transport = transport
            row.protocol_version = protocol_version
            row.status = status
            row.last_seen_at = utcnow()
            row.remote_addr = remote_addr
            row.subscriptions = list(subscriptions or row.subscriptions or [])
            row.capability_snapshot = dict(capability_snapshot or row.capability_snapshot or {})
            row.meta = dict(metadata or row.meta or {})
        self.session.flush()
        return row

    def get_by_connection_id(self, connection_id: str) -> EndpointConnection | None:
        return self.session.query(EndpointConnection).filter_by(connection_id=connection_id).one_or_none()

    def update_heartbeat(self, *, connection_id: str, status: str = "connected", metadata: dict | None = None) -> EndpointConnection | None:
        row = self.get_by_connection_id(connection_id)
        if row is None:
            return None
        row.status = status
        row.last_seen_at = utcnow()
        if metadata is not None:
            merged = dict(row.meta or {})
            merged.update(dict(metadata or {}))
            row.meta = merged
        self.session.flush()
        return row

    def mark_disconnected(self, *, connection_id: str) -> EndpointConnection | None:
        row = self.get_by_connection_id(connection_id)
        if row is None:
            return None
        row.status = "disconnected"
        row.last_seen_at = utcnow()
        self.session.flush()
        return row


class EndpointCapabilityRepository(RepositoryBase):
    def upsert(
        self,
        *,
        endpoint_id,
        tool_key: str,
        capability_id: str,
        schema: dict | None = None,
        risk_level: str = "read",
        requires_confirmation: bool = False,
        enabled: bool = True,
        constraints: dict | None = None,
        metadata: dict | None = None,
    ) -> EndpointCapability:
        row = self.session.query(EndpointCapability).filter_by(endpoint_id=endpoint_id, tool_key=tool_key).one_or_none()
        if row is None:
            row = EndpointCapability(
                endpoint_id=endpoint_id,
                tool_key=tool_key,
                capability_id=capability_id,
                schema=dict(schema or {}),
                risk_level=risk_level,
                requires_confirmation=bool(requires_confirmation),
                enabled=bool(enabled),
                constraints=dict(constraints or {}),
                meta=dict(metadata or {}),
            )
            self.session.add(row)
        else:
            row.capability_id = capability_id
            row.schema = dict(schema or {})
            row.risk_level = risk_level
            row.requires_confirmation = bool(requires_confirmation)
            row.enabled = bool(enabled)
            row.constraints = dict(constraints or {})
            row.meta = dict(metadata or row.meta or {})
        self.session.flush()
        return row

    def get_by_capability_id(self, capability_id: str) -> EndpointCapability | None:
        return self.session.query(EndpointCapability).filter_by(capability_id=capability_id).one_or_none()

    def list_for_endpoint(self, *, endpoint_id) -> list[EndpointCapability]:
        return list(
            self.session.query(EndpointCapability)
            .filter_by(endpoint_id=endpoint_id)
            .order_by(EndpointCapability.tool_key.asc())
            .all()
        )

    def list_enabled_for_tool(self, *, tool_key: str) -> list[EndpointCapability]:
        return list(
            self.session.query(EndpointCapability)
            .filter_by(tool_key=tool_key, enabled=True)
            .order_by(EndpointCapability.tool_key.asc())
            .all()
        )


class EndpointOutboxRepository(RepositoryBase):
    def create(
        self,
        *,
        outbox_id: str,
        target_endpoint_id,
        message_type: str,
        payload: dict,
        status: str = "pending",
        available_at=None,
        metadata: dict | None = None,
    ) -> EndpointOutbox:
        row = EndpointOutbox(
            outbox_id=outbox_id,
            target_endpoint_id=target_endpoint_id,
            message_type=message_type,
            payload=dict(payload or {}),
            status=status,
            available_at=available_at,
            meta=dict(metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row


class DeliveryAttemptRepository(RepositoryBase):
    def create(
        self,
        *,
        delivery_id: str,
        target_endpoint_id,
        message_type: str,
        payload: dict,
        outbox_id=None,
        status: str = "pending",
        error: dict | None = None,
        metadata: dict | None = None,
    ) -> DeliveryAttempt:
        row = DeliveryAttempt(
            delivery_id=delivery_id,
            outbox_id=outbox_id,
            target_endpoint_id=target_endpoint_id,
            message_type=message_type,
            status=status,
            payload=dict(payload or {}),
            error=dict(error or {}),
            meta=dict(metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row
