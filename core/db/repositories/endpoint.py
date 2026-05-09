from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_

from core.db.base import utcnow
from core.db.models.endpoint import (
    ActorDeliveryPreference,
    DeliveryAttempt,
    Endpoint,
    EndpointAddress,
    EndpointAddressWorkspaceMembership,
    EndpointCapability,
    EndpointConnection,
    EndpointOutbox,
    EndpointThreadBinding,
    EndpointWorkspaceMembership,
)
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
            if metadata is not None:
                merged = dict(row.meta or {})
                merged.update(dict(metadata or {}))
                row.meta = merged
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

    def update_heartbeat(self, *, endpoint_id: str, status: str = "ready", metrics: dict | None = None, payload: dict | None = None) -> Endpoint | None:
        row = self.get_by_endpoint_id(endpoint_id)
        if row is None:
            return None
        normalized_status = str(status or "").strip()
        if normalized_status:
            row.status = normalized_status
        merged = dict(row.meta or {})
        heartbeat = {
            "status": row.status,
            "metrics": dict(metrics or {}),
            "payload": dict(payload or {}),
            "last_seen_at": utcnow().isoformat(),
        }
        merged["heartbeat"] = heartbeat
        merged["heartbeat_metrics"] = dict(metrics or {})
        row.meta = merged
        self.session.flush()
        return row

    def record_routing_result(self, *, endpoint_row_id, success: bool, latency_ms: float | None = None) -> Endpoint | None:
        row = self.get_by_id(endpoint_row_id)
        if row is None:
            return None
        merged = dict(row.meta or {})
        stats = dict(merged.get("routing_stats") or {})
        success_count = int(stats.get("success_count") or 0)
        failure_count = int(stats.get("failure_count") or 0)
        if success:
            success_count += 1
            stats["last_success_at"] = utcnow().isoformat()
        else:
            failure_count += 1
            stats["last_failure_at"] = utcnow().isoformat()
        stats["success_count"] = success_count
        stats["failure_count"] = failure_count
        if latency_ms is not None:
            try:
                observed = max(0.0, float(latency_ms))
                previous = float(stats.get("average_latency_ms") or observed)
                stats["average_latency_ms"] = round((previous * 0.8) + (observed * 0.2), 3)
                stats["last_latency_ms"] = round(observed, 3)
            except (TypeError, ValueError):
                pass
        merged["routing_stats"] = stats
        row.meta = merged
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

    def disable_missing_for_endpoint(self, *, endpoint_id, active_tool_keys: set[str]) -> int:
        rows = self.list_for_endpoint(endpoint_id=endpoint_id)
        disabled = 0
        for row in rows:
            tool_key = str(getattr(row, "tool_key", "") or "").strip()
            if tool_key in active_tool_keys or not bool(getattr(row, "enabled", True)):
                continue
            row.enabled = False
            disabled += 1
        if disabled:
            self.session.flush()
        return disabled


class EndpointWorkspaceMembershipRepository(RepositoryBase):
    def upsert(
        self,
        *,
        endpoint_id,
        workspace_id,
        membership_id: str = "",
        membership_role: str = "member",
        is_primary: bool = False,
        enabled: bool = True,
        source: str = "core",
        metadata: dict | None = None,
    ) -> EndpointWorkspaceMembership:
        row = self.get(endpoint_id=endpoint_id, workspace_id=workspace_id)
        if row is None:
            row = EndpointWorkspaceMembership(
                membership_id=str(membership_id or f"ewm.{endpoint_id}.{workspace_id}").strip(),
                endpoint_id=endpoint_id,
                workspace_id=workspace_id,
                membership_role=str(membership_role or "member").strip() or "member",
                is_primary=bool(is_primary),
                enabled=bool(enabled),
                source=str(source or "core").strip() or "core",
                meta=dict(metadata or {}),
            )
            self.session.add(row)
        else:
            row.membership_role = str(membership_role or row.membership_role or "member").strip() or "member"
            row.enabled = bool(enabled)
            row.source = str(source or row.source or "core").strip() or "core"
            if metadata is not None:
                merged = dict(row.meta or {})
                merged.update(dict(metadata or {}))
                row.meta = merged
            if is_primary:
                row.is_primary = True
        if is_primary:
            self._clear_other_primary(endpoint_id=endpoint_id, keep_workspace_id=workspace_id)
        self.session.flush()
        return row

    def get(self, *, endpoint_id, workspace_id) -> EndpointWorkspaceMembership | None:
        return (
            self.session.query(EndpointWorkspaceMembership)
            .filter_by(endpoint_id=endpoint_id, workspace_id=workspace_id)
            .one_or_none()
        )

    def list_for_endpoint(self, *, endpoint_id, include_disabled: bool = False) -> list[EndpointWorkspaceMembership]:
        query = self.session.query(EndpointWorkspaceMembership).filter_by(endpoint_id=endpoint_id)
        if not include_disabled:
            query = query.filter_by(enabled=True)
        return list(query.order_by(EndpointWorkspaceMembership.is_primary.desc(), EndpointWorkspaceMembership.created_at.asc()).all())

    def list_for_workspace(self, *, workspace_id, include_disabled: bool = False) -> list[EndpointWorkspaceMembership]:
        query = self.session.query(EndpointWorkspaceMembership).filter_by(workspace_id=workspace_id)
        if not include_disabled:
            query = query.filter_by(enabled=True)
        return list(query.order_by(EndpointWorkspaceMembership.created_at.asc()).all())

    def set_primary(self, *, endpoint_id, workspace_id) -> EndpointWorkspaceMembership | None:
        row = self.get(endpoint_id=endpoint_id, workspace_id=workspace_id)
        if row is None:
            return None
        row.enabled = True
        row.is_primary = True
        self._clear_other_primary(endpoint_id=endpoint_id, keep_workspace_id=workspace_id)
        self.session.flush()
        return row

    def disable(self, *, endpoint_id, workspace_id) -> bool:
        row = self.get(endpoint_id=endpoint_id, workspace_id=workspace_id)
        if row is None or not bool(row.enabled):
            return False
        was_primary = bool(row.is_primary)
        row.enabled = False
        row.is_primary = False
        if was_primary:
            self._promote_first_enabled(endpoint_id=endpoint_id)
        self.session.flush()
        return True

    def _clear_other_primary(self, *, endpoint_id, keep_workspace_id) -> None:
        for row in self.session.query(EndpointWorkspaceMembership).filter_by(endpoint_id=endpoint_id).all():
            if row.workspace_id != keep_workspace_id:
                row.is_primary = False

    def _promote_first_enabled(self, *, endpoint_id) -> None:
        rows = self.list_for_endpoint(endpoint_id=endpoint_id)
        if rows and not any(bool(row.is_primary) for row in rows):
            rows[0].is_primary = True


class EndpointAddressRepository(RepositoryBase):
    def upsert(
        self,
        *,
        endpoint_id,
        provider_type: str,
        address_type: str,
        external_ref: str,
        address_id: str = "",
        display_name: str = "",
        workspace_scope: list | None = None,
        status: str = "sendable",
        capabilities: list | None = None,
        last_seen_at=None,
        last_verified_at=None,
        metadata: dict | None = None,
    ) -> EndpointAddress:
        normalized_external_ref = str(external_ref or "").strip()
        normalized_address_type = str(address_type or "direct").strip() or "direct"
        row = None
        normalized_address_id = str(address_id or "").strip()
        if normalized_address_id:
            row = self.get_by_address_id(normalized_address_id)
        if row is None:
            row = (
                self.session.query(EndpointAddress)
                .filter_by(endpoint_id=endpoint_id, address_type=normalized_address_type, external_ref=normalized_external_ref)
                .one_or_none()
            )
        if row is None:
            row = EndpointAddress(
                address_id=normalized_address_id,
                endpoint_id=endpoint_id,
                provider_type=str(provider_type or "").strip(),
                address_type=normalized_address_type,
                external_ref=normalized_external_ref,
                display_name=str(display_name or "").strip(),
                workspace_scope=list(workspace_scope or []),
                status=str(status or "unknown").strip() or "unknown",
                capabilities=list(capabilities or []),
                last_seen_at=last_seen_at,
                last_verified_at=last_verified_at,
                meta=dict(metadata or {}),
            )
            if not row.address_id:
                row.address_id = f"addr.{row.provider_type}.{row.address_type}.{row.external_ref}"
            self.session.add(row)
        else:
            row.provider_type = str(provider_type or row.provider_type or "").strip()
            row.address_type = normalized_address_type
            row.external_ref = normalized_external_ref or row.external_ref
            if display_name is not None:
                row.display_name = str(display_name or row.display_name or "").strip()
            row.workspace_scope = list(workspace_scope or row.workspace_scope or [])
            row.status = str(status or row.status or "unknown").strip() or "unknown"
            row.capabilities = list(capabilities or row.capabilities or [])
            if last_seen_at is not None:
                row.last_seen_at = last_seen_at
            if last_verified_at is not None:
                row.last_verified_at = last_verified_at
            row.meta = dict(metadata or row.meta or {})
        self.session.flush()
        return row

    def get_by_address_id(self, address_id: str) -> EndpointAddress | None:
        return self.session.query(EndpointAddress).filter_by(address_id=str(address_id or "").strip()).one_or_none()

    def get_by_id(self, row_id) -> EndpointAddress | None:
        return self.session.query(EndpointAddress).filter_by(id=row_id).one_or_none()

    def get_by_endpoint_external_ref(self, *, endpoint_id, external_ref: str) -> EndpointAddress | None:
        return (
            self.session.query(EndpointAddress)
            .filter_by(endpoint_id=endpoint_id, external_ref=str(external_ref or "").strip())
            .one_or_none()
        )

    def list_all(
        self,
        *,
        provider_type: str = "",
        address_type: str = "",
        workspace_id: str = "",
        status: str = "",
    ) -> list[EndpointAddress]:
        query = self.session.query(EndpointAddress)
        if provider_type:
            query = query.filter_by(provider_type=provider_type)
        if address_type:
            query = query.filter_by(address_type=address_type)
        if status:
            query = query.filter_by(status=status)
        rows = list(query.order_by(EndpointAddress.provider_type.asc(), EndpointAddress.display_name.asc()).all())
        if workspace_id:
            rows = [
                row
                for row in rows
                if not list(row.workspace_scope or []) or workspace_id in list(row.workspace_scope or []) or "*" in list(row.workspace_scope or [])
            ]
        return rows

    def delete(self, *, address_id: str) -> bool:
        row = self.get_by_address_id(address_id)
        if row is None:
            return False
        row.status = "unavailable"
        row.capabilities = []
        self.session.flush()
        return True


class EndpointAddressWorkspaceMembershipRepository(RepositoryBase):
    def upsert(
        self,
        *,
        address_id,
        workspace_id,
        membership_id: str = "",
        membership_role: str = "member",
        is_primary: bool = False,
        enabled: bool = True,
        source: str = "core",
        metadata: dict | None = None,
    ) -> EndpointAddressWorkspaceMembership:
        row = self.get(address_id=address_id, workspace_id=workspace_id)
        if row is None:
            row = EndpointAddressWorkspaceMembership(
                membership_id=str(membership_id or f"eawm.{address_id}.{workspace_id}").strip(),
                address_id=address_id,
                workspace_id=workspace_id,
                membership_role=str(membership_role or "member").strip() or "member",
                is_primary=bool(is_primary),
                enabled=bool(enabled),
                source=str(source or "core").strip() or "core",
                meta=dict(metadata or {}),
            )
            self.session.add(row)
        else:
            row.membership_role = str(membership_role or row.membership_role or "member").strip() or "member"
            row.enabled = bool(enabled)
            row.source = str(source or row.source or "core").strip() or "core"
            if metadata is not None:
                merged = dict(row.meta or {})
                merged.update(dict(metadata or {}))
                row.meta = merged
            if is_primary:
                row.is_primary = True
        if is_primary:
            self._clear_other_primary(address_id=address_id, keep_workspace_id=workspace_id)
        self.session.flush()
        return row

    def get(self, *, address_id, workspace_id) -> EndpointAddressWorkspaceMembership | None:
        return (
            self.session.query(EndpointAddressWorkspaceMembership)
            .filter_by(address_id=address_id, workspace_id=workspace_id)
            .one_or_none()
        )

    def list_for_address(self, *, address_id, include_disabled: bool = False) -> list[EndpointAddressWorkspaceMembership]:
        query = self.session.query(EndpointAddressWorkspaceMembership).filter_by(address_id=address_id)
        if not include_disabled:
            query = query.filter_by(enabled=True)
        return list(query.order_by(EndpointAddressWorkspaceMembership.is_primary.desc(), EndpointAddressWorkspaceMembership.created_at.asc()).all())

    def list_for_workspace(self, *, workspace_id, include_disabled: bool = False) -> list[EndpointAddressWorkspaceMembership]:
        query = self.session.query(EndpointAddressWorkspaceMembership).filter_by(workspace_id=workspace_id)
        if not include_disabled:
            query = query.filter_by(enabled=True)
        return list(query.order_by(EndpointAddressWorkspaceMembership.created_at.asc()).all())

    def set_primary(self, *, address_id, workspace_id) -> EndpointAddressWorkspaceMembership | None:
        row = self.get(address_id=address_id, workspace_id=workspace_id)
        if row is None:
            return None
        row.enabled = True
        row.is_primary = True
        self._clear_other_primary(address_id=address_id, keep_workspace_id=workspace_id)
        self.session.flush()
        return row

    def disable(self, *, address_id, workspace_id) -> bool:
        row = self.get(address_id=address_id, workspace_id=workspace_id)
        if row is None or not bool(row.enabled):
            return False
        was_primary = bool(row.is_primary)
        row.enabled = False
        row.is_primary = False
        if was_primary:
            self._promote_first_enabled(address_id=address_id)
        self.session.flush()
        return True

    def _clear_other_primary(self, *, address_id, keep_workspace_id) -> None:
        for row in self.session.query(EndpointAddressWorkspaceMembership).filter_by(address_id=address_id).all():
            if row.workspace_id != keep_workspace_id:
                row.is_primary = False

    def _promote_first_enabled(self, *, address_id) -> None:
        rows = self.list_for_address(address_id=address_id)
        if rows and not any(bool(row.is_primary) for row in rows):
            rows[0].is_primary = True


class EndpointThreadBindingRepository(RepositoryBase):
    def upsert(
        self,
        *,
        endpoint_id,
        thread_id,
        workspace_id,
        thread_strategy: str,
        conversation_key: str,
        binding_id: str = "",
        address_id=None,
        display_name: str = "",
        status: str = "active",
        metadata: dict | None = None,
    ) -> EndpointThreadBinding:
        normalized_strategy = str(thread_strategy or "").strip()
        normalized_key = str(conversation_key or "").strip()
        row = self.get_by_endpoint_strategy_key(
            endpoint_id=endpoint_id,
            thread_strategy=normalized_strategy,
            conversation_key=normalized_key,
        )
        if row is None:
            row = EndpointThreadBinding(
                binding_id=str(binding_id or "").strip(),
                endpoint_id=endpoint_id,
                thread_id=thread_id,
                workspace_id=workspace_id,
                address_id=address_id,
                thread_strategy=normalized_strategy,
                conversation_key=normalized_key,
                display_name=str(display_name or "").strip(),
                status=str(status or "active").strip() or "active",
                meta=dict(metadata or {}),
            )
            if not row.binding_id:
                row.binding_id = f"etb.{endpoint_id}.{normalized_strategy}.{normalized_key}"
            self.session.add(row)
        else:
            row.thread_id = thread_id
            row.workspace_id = workspace_id
            row.address_id = address_id
            row.display_name = str(display_name or row.display_name or "").strip()
            row.status = str(status or row.status or "active").strip() or "active"
            row.meta = dict(metadata or row.meta or {})
        self.session.flush()
        return row

    def get_by_endpoint_strategy_key(
        self,
        *,
        endpoint_id,
        thread_strategy: str,
        conversation_key: str,
    ) -> EndpointThreadBinding | None:
        return (
            self.session.query(EndpointThreadBinding)
            .filter_by(
                endpoint_id=endpoint_id,
                thread_strategy=str(thread_strategy or "").strip(),
                conversation_key=str(conversation_key or "").strip(),
            )
            .one_or_none()
        )

    def get_by_binding_id(self, binding_id: str) -> EndpointThreadBinding | None:
        return self.session.query(EndpointThreadBinding).filter_by(binding_id=str(binding_id or "").strip()).one_or_none()


class ActorDeliveryPreferenceRepository(RepositoryBase):
    def upsert(
        self,
        *,
        actor_id,
        provider_type: str,
        address_id,
        alias: str = "me",
        preference_id: str = "",
        is_default: bool = True,
        verified: bool = False,
        metadata: dict | None = None,
    ) -> ActorDeliveryPreference:
        normalized_provider = str(provider_type or "").strip()
        normalized_alias = str(alias or "me").strip() or "me"
        row = (
            self.session.query(ActorDeliveryPreference)
            .filter_by(actor_id=actor_id, provider_type=normalized_provider, alias=normalized_alias)
            .one_or_none()
        )
        if row is None:
            row = ActorDeliveryPreference(
                preference_id=str(preference_id or "").strip() or f"pref.{actor_id}.{normalized_provider}.{normalized_alias}",
                actor_id=actor_id,
                provider_type=normalized_provider,
                address_id=address_id,
                alias=normalized_alias,
                is_default=bool(is_default),
                verified=bool(verified),
                meta=dict(metadata or {}),
            )
            self.session.add(row)
        else:
            row.address_id = address_id
            row.is_default = bool(is_default)
            row.verified = bool(verified)
            row.meta = dict(metadata or row.meta or {})
        self.session.flush()
        return row

    def list_for_actor(self, *, actor_id, provider_type: str = "", alias: str = "") -> list[ActorDeliveryPreference]:
        query = self.session.query(ActorDeliveryPreference).filter_by(actor_id=actor_id)
        if provider_type:
            query = query.filter_by(provider_type=str(provider_type or "").strip())
        if alias:
            query = query.filter_by(alias=str(alias or "").strip())
        return list(query.order_by(ActorDeliveryPreference.provider_type.asc(), ActorDeliveryPreference.alias.asc()).all())

    def get_default(self, *, actor_id, provider_type: str, alias: str = "me") -> ActorDeliveryPreference | None:
        rows = self.list_for_actor(actor_id=actor_id, provider_type=provider_type, alias=alias or "me")
        return next((row for row in rows if bool(row.is_default)), rows[0] if rows else None)


class EndpointOutboxRepository(RepositoryBase):
    def create(
        self,
        *,
        outbox_id: str,
        target_endpoint_id,
        target_address_id=None,
        message_type: str,
        payload: dict,
        status: str = "pending",
        available_at=None,
        metadata: dict | None = None,
    ) -> EndpointOutbox:
        row = EndpointOutbox(
            outbox_id=outbox_id,
            target_endpoint_id=target_endpoint_id,
            target_address_id=target_address_id,
            message_type=message_type,
            payload=dict(payload or {}),
            status=status,
            available_at=available_at,
            meta=dict(metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_id(self, row_id) -> EndpointOutbox | None:
        return self.session.query(EndpointOutbox).filter_by(id=row_id).one_or_none()

    def get_by_outbox_id(self, outbox_id: str) -> EndpointOutbox | None:
        return self.session.query(EndpointOutbox).filter_by(outbox_id=str(outbox_id or "").strip()).one_or_none()

    def list_due(self, *, target_endpoint_id=None, limit: int = 50, now=None) -> list[EndpointOutbox]:
        due_at = now or utcnow()
        query = self.session.query(EndpointOutbox).filter(EndpointOutbox.status.in_(["pending", "retry"]))
        if target_endpoint_id is not None:
            query = query.filter_by(target_endpoint_id=target_endpoint_id)
        query = query.filter(or_(EndpointOutbox.available_at.is_(None), EndpointOutbox.available_at <= due_at))
        limit = max(1, min(int(limit or 50), 500))
        return list(query.order_by(EndpointOutbox.available_at.asc(), EndpointOutbox.created_at.asc()).limit(limit).all())

    def mark_inflight(self, *, outbox_id) -> EndpointOutbox | None:
        row = self.get_by_id(outbox_id)
        if row is None:
            return None
        row.status = "sending"
        row.attempt_count = int(row.attempt_count or 0) + 1
        self.session.flush()
        return row

    def mark_sent(self, *, outbox_id) -> EndpointOutbox | None:
        row = self.get_by_id(outbox_id)
        if row is None:
            return None
        row.status = "sent"
        row.last_error = ""
        self.session.flush()
        return row

    def reschedule_failure(
        self,
        *,
        outbox_id,
        error: str,
        max_attempts: int = 5,
        base_delay_seconds: int = 2,
        max_delay_seconds: int = 300,
    ) -> EndpointOutbox | None:
        row = self.get_by_id(outbox_id)
        if row is None:
            return None
        attempts = int(row.attempt_count or 0)
        row.last_error = str(error or "")
        if attempts >= max(1, int(max_attempts or 1)):
            row.status = "dead_letter"
            row.available_at = None
        else:
            delay_seconds = min(
                max(1, int(max_delay_seconds or 300)),
                max(1, int(base_delay_seconds or 2)) * (2 ** max(0, attempts - 1)),
            )
            row.status = "retry"
            row.available_at = utcnow() + timedelta(seconds=delay_seconds)
        self.session.flush()
        return row


class DeliveryAttemptRepository(RepositoryBase):
    def create(
        self,
        *,
        delivery_id: str,
        target_endpoint_id,
        target_address_id=None,
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
            target_address_id=target_address_id,
            message_type=message_type,
            status=status,
            payload=dict(payload or {}),
            error=dict(error or {}),
            meta=dict(metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_delivery_id(self, delivery_id: str) -> DeliveryAttempt | None:
        return self.session.query(DeliveryAttempt).filter_by(delivery_id=str(delivery_id or "").strip()).one_or_none()

    def update_result(
        self,
        *,
        delivery_id: str,
        status: str,
        error: dict | None = None,
        metadata: dict | None = None,
        outbox_id=None,
    ) -> DeliveryAttempt | None:
        row = self.get_by_delivery_id(delivery_id)
        if row is None:
            return None
        row.status = str(status or row.status or "pending").strip() or "pending"
        if error is not None:
            row.error = dict(error or {})
        if metadata:
            merged = dict(row.meta or {})
            merged.update(dict(metadata or {}))
            row.meta = merged
        if outbox_id is not None:
            row.outbox_id = outbox_id
        self.session.flush()
        return row
