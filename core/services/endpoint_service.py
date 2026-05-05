from __future__ import annotations

import hashlib
from uuid import uuid4

from core.db.base import utcnow
from core.db.repositories import (
    ActorDeliveryPreferenceRepository,
    DeliveryAttemptRepository,
    EndpointAddressRepository,
    EndpointAddressWorkspaceMembershipRepository,
    EndpointCapabilityRepository,
    EndpointConnectionRepository,
    EndpointOutboxRepository,
    EndpointRepository,
    EndpointThreadBindingRepository,
    EndpointWorkspaceMembershipRepository,
    WorkspaceRepository,
    ThreadRepository,
)
from core.services.base import ServiceBase


HIDDEN_ENDPOINT_STATUSES = {"archived", "retired"}
CORE_INTERNAL_ENDPOINT_IDS = {"core.local", "core.scheduler", "core.inbox", "core.notification"}
PRESENTATION_ENDPOINT_TYPES = {"desktop_ui", "edge_ui"}


class EndpointThreadBindingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _string_list(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def is_acceptance_probe_endpoint(endpoint) -> bool:
    endpoint_id = str(getattr(endpoint, "endpoint_id", "") or "").strip().lower()
    endpoint_type = str(getattr(endpoint, "endpoint_type", "") or "").strip().lower()
    meta = dict(getattr(endpoint, "meta", {}) or {})
    provider = meta.get("provider") if isinstance(meta.get("provider"), dict) else {}
    provider_id = str(provider.get("provider_id") or "").strip().lower()
    transport_profile = str(provider.get("transport_profile") or "").strip().lower()
    display_name = str(provider.get("display_name") or meta.get("display_name") or "").strip().lower()
    endpoint_id_matches = endpoint_id.startswith(("desktop.v4check-", "edge.v4check-")) and endpoint_id.endswith(
        (".ui", ".executor")
    )
    provider_matches = provider_id.startswith("v4check-") and transport_profile == "acceptance_ws"
    name_matches = display_name == "v4 acceptance endpoint" and endpoint_type in {"desktop_ui", "desktop_executor", "edge_executor"}
    return endpoint_id_matches or provider_matches or name_matches


def endpoint_hidden_from_operator(endpoint) -> bool:
    status = str(getattr(endpoint, "status", "") or "").strip().lower()
    meta = dict(getattr(endpoint, "meta", {}) or {})
    return status in HIDDEN_ENDPOINT_STATUSES or bool(meta.get("operator_hidden")) or is_acceptance_probe_endpoint(endpoint)


def endpoint_is_core_internal(endpoint) -> bool:
    endpoint_id = str(getattr(endpoint, "endpoint_id", "") or "").strip().lower()
    endpoint_type = str(getattr(endpoint, "endpoint_type", "") or "").strip().lower()
    provider_type = str(getattr(endpoint, "provider_type", "") or "").strip().lower()
    return provider_type == "core" or endpoint_id in CORE_INTERNAL_ENDPOINT_IDS or endpoint_type.startswith("core_")


def endpoint_is_presentation_role(endpoint) -> bool:
    endpoint_id = str(getattr(endpoint, "endpoint_id", "") or "").strip().lower()
    endpoint_type = str(getattr(endpoint, "endpoint_type", "") or "").strip().lower()
    provider_type = str(getattr(endpoint, "provider_type", "") or "").strip().lower()
    return provider_type in {"desktop", "edge"} and (endpoint_id.endswith(".ui") or endpoint_type in PRESENTATION_ENDPOINT_TYPES)


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

    def retire_acceptance_probe_endpoints(self) -> int:
        retired = 0
        retired_at = utcnow().isoformat()
        with self.session_scope() as session:
            endpoint_repo = EndpointRepository(session)
            capability_repo = EndpointCapabilityRepository(session)
            for endpoint in endpoint_repo.list_all():
                if not is_acceptance_probe_endpoint(endpoint):
                    continue
                meta = dict(getattr(endpoint, "meta", {}) or {})
                already_retired = bool(meta.get("operator_hidden")) and str(getattr(endpoint, "status", "") or "") == "archived"
                endpoint.status = "archived"
                meta["operator_hidden"] = True
                meta["operator_hidden_reason"] = "v4_acceptance_probe"
                meta.setdefault("retired_at", retired_at)
                endpoint.meta = meta
                for capability in capability_repo.list_for_endpoint(endpoint_id=endpoint.id):
                    capability.enabled = False
                if not already_retired:
                    retired += 1
            if retired:
                session.flush()
        return retired

    def set_status(self, *, endpoint_id: str, status: str):
        with self.session_scope() as session:
            return EndpointRepository(session).set_status(endpoint_id=endpoint_id, status=status)

    def update_heartbeat(self, *, endpoint_id: str, status: str = "ready", metrics: dict | None = None, payload: dict | None = None):
        with self.session_scope() as session:
            return EndpointRepository(session).update_heartbeat(
                endpoint_id=endpoint_id,
                status=status,
                metrics=metrics,
                payload=payload,
            )

    def record_routing_result(self, *, endpoint_row_id, success: bool, latency_ms: float | None = None):
        with self.session_scope() as session:
            return EndpointRepository(session).record_routing_result(
                endpoint_row_id=endpoint_row_id,
                success=success,
                latency_ms=latency_ms,
            )


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
        active_tool_keys: set[str] = set()
        with self.session_scope() as session:
            repo = EndpointCapabilityRepository(session)
            for item in capabilities or []:
                tool_key = str(item.get("tool_key") or item.get("name") or "").strip()
                if not tool_key:
                    continue
                active_tool_keys.add(tool_key)
                raw_capability_id = str(item.get("capability_id") or item.get("tool_id") or "").strip()
                if raw_capability_id and not raw_capability_id.startswith("endpoint."):
                    raw_capability_id = ""
                input_schema = (
                    item.get("input_schema")
                    if isinstance(item.get("input_schema"), dict)
                    else item.get("schema")
                    if isinstance(item.get("schema"), dict)
                    else {}
                )
                output_schema = item.get("output_schema") if isinstance(item.get("output_schema"), dict) else {}
                metadata = {
                    k: v
                    for k, v in dict(item).items()
                    if k not in {"schema", "input_schema", "output_schema", "constraints"}
                }
                metadata["input_schema"] = dict(input_schema or {})
                metadata["output_schema"] = dict(output_schema or {})
                repo.upsert(
                    endpoint_id=endpoint_row_id,
                    tool_key=tool_key,
                    capability_id=raw_capability_id or f"endpoint.{endpoint_public_id}.{tool_key}",
                    schema=input_schema,
                    risk_level=str(item.get("risk_level") or "read"),
                    requires_confirmation=bool(item.get("requires_confirmation", False)),
                    enabled=bool(item.get("enabled", True)),
                    constraints=item.get("constraints") if isinstance(item.get("constraints"), dict) else {},
                    metadata=metadata,
                )
                count += 1
            repo.disable_missing_for_endpoint(endpoint_id=endpoint_row_id, active_tool_keys=active_tool_keys)
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


class EndpointWorkspaceMembershipService(ServiceBase):
    @staticmethod
    def _public_workspace_ids(session, rows) -> list[str]:
        workspace_repo = WorkspaceRepository(session)
        result: list[str] = []
        for row in rows:
            workspace = workspace_repo.get_by_id(getattr(row, "workspace_id", None))
            workspace_id = str(getattr(workspace, "workspace_id", "") or "").strip()
            if workspace_id and workspace_id not in result:
                result.append(workspace_id)
        return result

    @staticmethod
    def _primary_workspace_id(session, rows) -> str:
        workspace_repo = WorkspaceRepository(session)
        primary = next((row for row in rows if bool(getattr(row, "is_primary", False))), rows[0] if rows else None)
        workspace = workspace_repo.get_by_id(getattr(primary, "workspace_id", None)) if primary is not None else None
        return str(getattr(workspace, "workspace_id", "") or "").strip()

    @staticmethod
    def _endpoint_is_core(endpoint) -> bool:
        return str(getattr(endpoint, "provider_type", "") or "").strip().lower() == "core"

    def _sync_endpoint_scope(self, session, *, endpoint) -> list[str]:
        repo = EndpointWorkspaceMembershipRepository(session)
        rows = repo.list_for_endpoint(endpoint_id=getattr(endpoint, "id", None))
        workspace_ids = self._public_workspace_ids(session, rows)
        endpoint.workspace_scope = list(workspace_ids)
        meta = dict(getattr(endpoint, "meta", {}) or {})
        meta["managed_workspace_ids"] = list(workspace_ids)
        meta["primary_workspace_id"] = self._primary_workspace_id(session, rows)
        endpoint.meta = meta
        session.flush()
        return workspace_ids

    def seed_endpoint_memberships(
        self,
        *,
        endpoint_row_id,
        workspace_ids: list[str] | tuple[str, ...] | None,
        source: str = "provider_declared",
        fallback_workspace_id: str = "personal",
    ) -> list[str]:
        requested = _string_list(workspace_ids)
        with self.session_scope() as session:
            endpoint = EndpointRepository(session).get_by_id(endpoint_row_id)
            if endpoint is None:
                return []
            repo = EndpointWorkspaceMembershipRepository(session)
            active_rows = repo.list_for_endpoint(endpoint_id=endpoint.id)
            if active_rows:
                return self._sync_endpoint_scope(session, endpoint=endpoint)

            workspace_repo = WorkspaceRepository(session)
            workspaces = []
            for workspace_id in requested:
                workspace = workspace_repo.get_by_workspace_id(workspace_id)
                if workspace is not None and str(getattr(workspace, "status", "") or "active") != "archived":
                    workspaces.append(workspace)
            if not workspaces and not self._endpoint_is_core(endpoint):
                fallback = workspace_repo.get_by_workspace_id(fallback_workspace_id)
                if fallback is not None and str(getattr(fallback, "status", "") or "active") != "archived":
                    workspaces.append(fallback)

            for index, workspace in enumerate(workspaces):
                repo.upsert(
                    endpoint_id=endpoint.id,
                    workspace_id=workspace.id,
                    is_primary=index == 0,
                    source=source,
                    metadata={"seeded_from_workspace_ids": requested},
                )
            return self._sync_endpoint_scope(session, endpoint=endpoint)

    def list_for_endpoint(self, *, endpoint_row_id, include_disabled: bool = False):
        with self.session_scope() as session:
            return EndpointWorkspaceMembershipRepository(session).list_for_endpoint(
                endpoint_id=endpoint_row_id,
                include_disabled=include_disabled,
            )

    def add_workspace(
        self,
        *,
        endpoint_id: str,
        workspace_id: str,
        make_primary: bool = False,
        source: str = "core",
    ) -> dict:
        with self.session_scope() as session:
            endpoint = EndpointRepository(session).get_by_endpoint_id(str(endpoint_id or "").strip())
            if endpoint is None:
                raise KeyError("endpoint_not_found")
            if self._endpoint_is_core(endpoint):
                raise ValueError("core_endpoint_membership_readonly")
            workspace = WorkspaceRepository(session).get_by_workspace_id(str(workspace_id or "").strip())
            if workspace is None or str(getattr(workspace, "status", "") or "active") == "archived":
                raise KeyError("workspace_not_found")
            repo = EndpointWorkspaceMembershipRepository(session)
            rows = repo.list_for_endpoint(endpoint_id=endpoint.id)
            repo.upsert(
                endpoint_id=endpoint.id,
                workspace_id=workspace.id,
                is_primary=bool(make_primary or not rows),
                source=source,
            )
            workspace_ids = self._sync_endpoint_scope(session, endpoint=endpoint)
            return {
                "endpoint_id": endpoint.endpoint_id,
                "workspace_ids": workspace_ids,
                "primary_workspace_id": self._primary_workspace_id(session, repo.list_for_endpoint(endpoint_id=endpoint.id)),
            }

    def remove_workspace(self, *, endpoint_id: str, workspace_id: str) -> dict:
        with self.session_scope() as session:
            endpoint = EndpointRepository(session).get_by_endpoint_id(str(endpoint_id or "").strip())
            if endpoint is None:
                raise KeyError("endpoint_not_found")
            if self._endpoint_is_core(endpoint):
                raise ValueError("core_endpoint_membership_readonly")
            workspace = WorkspaceRepository(session).get_by_workspace_id(str(workspace_id or "").strip())
            if workspace is None:
                raise KeyError("workspace_not_found")
            repo = EndpointWorkspaceMembershipRepository(session)
            rows = repo.list_for_endpoint(endpoint_id=endpoint.id)
            active_workspace_ids = {str(getattr(row, "workspace_id", "") or "") for row in rows}
            if str(workspace.id) not in active_workspace_ids:
                return {
                    "endpoint_id": endpoint.endpoint_id,
                    "workspace_ids": self._sync_endpoint_scope(session, endpoint=endpoint),
                    "primary_workspace_id": self._primary_workspace_id(session, rows),
                }
            if len(rows) <= 1:
                raise ValueError("endpoint_last_workspace_membership")
            repo.disable(endpoint_id=endpoint.id, workspace_id=workspace.id)
            next_rows = repo.list_for_endpoint(endpoint_id=endpoint.id)
            workspace_ids = self._sync_endpoint_scope(session, endpoint=endpoint)
            return {
                "endpoint_id": endpoint.endpoint_id,
                "workspace_ids": workspace_ids,
                "primary_workspace_id": self._primary_workspace_id(session, next_rows),
            }

    def set_primary_workspace(self, *, endpoint_id: str, workspace_id: str) -> dict:
        with self.session_scope() as session:
            endpoint = EndpointRepository(session).get_by_endpoint_id(str(endpoint_id or "").strip())
            if endpoint is None:
                raise KeyError("endpoint_not_found")
            if self._endpoint_is_core(endpoint):
                raise ValueError("core_endpoint_membership_readonly")
            workspace = WorkspaceRepository(session).get_by_workspace_id(str(workspace_id or "").strip())
            if workspace is None or str(getattr(workspace, "status", "") or "active") == "archived":
                raise KeyError("workspace_not_found")
            repo = EndpointWorkspaceMembershipRepository(session)
            repo.upsert(endpoint_id=endpoint.id, workspace_id=workspace.id, is_primary=True, source="core")
            rows = repo.list_for_endpoint(endpoint_id=endpoint.id)
            workspace_ids = self._sync_endpoint_scope(session, endpoint=endpoint)
            return {
                "endpoint_id": endpoint.endpoint_id,
                "workspace_ids": workspace_ids,
                "primary_workspace_id": self._primary_workspace_id(session, rows),
            }


class EndpointAddressService(ServiceBase):
    def upsert_address(
        self,
        *,
        endpoint_row_id,
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
    ):
        with self.session_scope() as session:
            return EndpointAddressRepository(session).upsert(
                endpoint_id=endpoint_row_id,
                provider_type=provider_type,
                address_type=address_type,
                external_ref=external_ref,
                address_id=address_id,
                display_name=display_name,
                workspace_scope=workspace_scope,
                status=status,
                capabilities=capabilities,
                last_seen_at=last_seen_at,
                last_verified_at=last_verified_at,
                metadata=metadata,
            )

    def get_by_address_id(self, address_id: str):
        with self.session_scope() as session:
            return EndpointAddressRepository(session).get_by_address_id(address_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return EndpointAddressRepository(session).get_by_id(row_id)

    def list_addresses(
        self,
        *,
        provider_type: str = "",
        address_type: str = "",
        workspace_id: str = "",
        status: str = "",
    ):
        with self.session_scope() as session:
            return EndpointAddressRepository(session).list_all(
                provider_type=str(provider_type or "").strip(),
                address_type=str(address_type or "").strip(),
                workspace_id=str(workspace_id or "").strip(),
                status=str(status or "").strip(),
            )

    def delete_address(self, *, address_id: str) -> bool:
        with self.session_scope() as session:
            return EndpointAddressRepository(session).delete(address_id=address_id)


class EndpointAddressWorkspaceMembershipService(ServiceBase):
    @staticmethod
    def _public_workspace_ids(session, rows) -> list[str]:
        workspace_repo = WorkspaceRepository(session)
        result: list[str] = []
        for row in rows:
            workspace = workspace_repo.get_by_id(getattr(row, "workspace_id", None))
            workspace_id = str(getattr(workspace, "workspace_id", "") or "").strip()
            if workspace_id and workspace_id not in result:
                result.append(workspace_id)
        return result

    @staticmethod
    def _primary_workspace_id(session, rows) -> str:
        workspace_repo = WorkspaceRepository(session)
        primary = next((row for row in rows if bool(getattr(row, "is_primary", False))), rows[0] if rows else None)
        workspace = workspace_repo.get_by_id(getattr(primary, "workspace_id", None)) if primary is not None else None
        return str(getattr(workspace, "workspace_id", "") or "").strip()

    def _sync_address_scope(self, session, *, address) -> list[str]:
        repo = EndpointAddressWorkspaceMembershipRepository(session)
        rows = repo.list_for_address(address_id=getattr(address, "id", None))
        workspace_ids = self._public_workspace_ids(session, rows)
        address.workspace_scope = list(workspace_ids)
        meta = dict(getattr(address, "meta", {}) or {})
        meta["managed_workspace_ids"] = list(workspace_ids)
        meta["primary_workspace_id"] = self._primary_workspace_id(session, rows)
        address.meta = meta
        session.flush()
        return workspace_ids

    def seed_address_memberships(
        self,
        *,
        address_row_id,
        workspace_ids: list[str] | tuple[str, ...] | None,
        source: str = "provider_declared",
    ) -> list[str]:
        requested = _string_list(workspace_ids)
        with self.session_scope() as session:
            address = EndpointAddressRepository(session).get_by_id(address_row_id)
            if address is None:
                return []
            repo = EndpointAddressWorkspaceMembershipRepository(session)
            active_rows = repo.list_for_address(address_id=address.id)
            if active_rows:
                return self._sync_address_scope(session, address=address)
            workspace_repo = WorkspaceRepository(session)
            workspaces = []
            for workspace_id in requested:
                workspace = workspace_repo.get_by_workspace_id(workspace_id)
                if workspace is not None and str(getattr(workspace, "status", "") or "active") != "archived":
                    workspaces.append(workspace)
            if not workspaces:
                endpoint = EndpointRepository(session).get_by_id(getattr(address, "endpoint_id", None))
                endpoint_scope = _string_list(getattr(endpoint, "workspace_scope", []) or [])
                for workspace_id in endpoint_scope:
                    workspace = workspace_repo.get_by_workspace_id(workspace_id)
                    if workspace is not None and str(getattr(workspace, "status", "") or "active") != "archived":
                        workspaces.append(workspace)
            for index, workspace in enumerate(workspaces):
                repo.upsert(
                    address_id=address.id,
                    workspace_id=workspace.id,
                    is_primary=index == 0,
                    source=source,
                    metadata={"seeded_from_workspace_ids": requested},
                )
            return self._sync_address_scope(session, address=address)

    def list_for_address(self, *, address_row_id, include_disabled: bool = False):
        with self.session_scope() as session:
            return EndpointAddressWorkspaceMembershipRepository(session).list_for_address(
                address_id=address_row_id,
                include_disabled=include_disabled,
            )

    def add_workspace(
        self,
        *,
        address_id: str,
        workspace_id: str,
        make_primary: bool = False,
        source: str = "core",
    ) -> dict:
        with self.session_scope() as session:
            address = EndpointAddressRepository(session).get_by_address_id(str(address_id or "").strip())
            if address is None:
                raise KeyError("address_not_found")
            workspace = WorkspaceRepository(session).get_by_workspace_id(str(workspace_id or "").strip())
            if workspace is None or str(getattr(workspace, "status", "") or "active") == "archived":
                raise KeyError("workspace_not_found")
            repo = EndpointAddressWorkspaceMembershipRepository(session)
            rows = repo.list_for_address(address_id=address.id)
            repo.upsert(
                address_id=address.id,
                workspace_id=workspace.id,
                is_primary=bool(make_primary or not rows),
                source=source,
            )
            workspace_ids = self._sync_address_scope(session, address=address)
            return {
                "address_id": address.address_id,
                "workspace_ids": workspace_ids,
                "primary_workspace_id": self._primary_workspace_id(session, repo.list_for_address(address_id=address.id)),
            }

    def remove_workspace(self, *, address_id: str, workspace_id: str) -> dict:
        with self.session_scope() as session:
            address = EndpointAddressRepository(session).get_by_address_id(str(address_id or "").strip())
            if address is None:
                raise KeyError("address_not_found")
            workspace = WorkspaceRepository(session).get_by_workspace_id(str(workspace_id or "").strip())
            if workspace is None:
                raise KeyError("workspace_not_found")
            repo = EndpointAddressWorkspaceMembershipRepository(session)
            rows = repo.list_for_address(address_id=address.id)
            active_workspace_ids = {str(getattr(row, "workspace_id", "") or "") for row in rows}
            if str(workspace.id) not in active_workspace_ids:
                return {
                    "address_id": address.address_id,
                    "workspace_ids": self._sync_address_scope(session, address=address),
                    "primary_workspace_id": self._primary_workspace_id(session, rows),
                }
            if len(rows) <= 1:
                raise ValueError("address_last_workspace_membership")
            repo.disable(address_id=address.id, workspace_id=workspace.id)
            rows = repo.list_for_address(address_id=address.id)
            workspace_ids = self._sync_address_scope(session, address=address)
            return {
                "address_id": address.address_id,
                "workspace_ids": workspace_ids,
                "primary_workspace_id": self._primary_workspace_id(session, rows),
            }

    def set_primary_workspace(self, *, address_id: str, workspace_id: str) -> dict:
        with self.session_scope() as session:
            address = EndpointAddressRepository(session).get_by_address_id(str(address_id or "").strip())
            if address is None:
                raise KeyError("address_not_found")
            workspace = WorkspaceRepository(session).get_by_workspace_id(str(workspace_id or "").strip())
            if workspace is None or str(getattr(workspace, "status", "") or "active") == "archived":
                raise KeyError("workspace_not_found")
            repo = EndpointAddressWorkspaceMembershipRepository(session)
            repo.upsert(address_id=address.id, workspace_id=workspace.id, is_primary=True, source="core")
            rows = repo.list_for_address(address_id=address.id)
            workspace_ids = self._sync_address_scope(session, address=address)
            return {
                "address_id": address.address_id,
                "workspace_ids": workspace_ids,
                "primary_workspace_id": self._primary_workspace_id(session, rows),
            }


class EndpointThreadBindingService(ServiceBase):
    _VALID_STRATEGIES = {"per_conversation", "per_address", "shared_endpoint", "explicit_thread"}

    @staticmethod
    def _binding_id(*parts: str) -> str:
        digest = hashlib.sha256("\n".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:32]
        return f"etb.{digest}"

    @staticmethod
    def _clean_key(value: str) -> str:
        return str(value or "").strip()

    def _canonical_key(
        self,
        *,
        thread_strategy: str,
        endpoint_public_id: str,
        conversation_key: str = "",
        address=None,
        explicit_thread_id: str = "",
    ) -> str:
        if thread_strategy == "shared_endpoint":
            return f"endpoint:{endpoint_public_id}"
        if thread_strategy == "per_address":
            address_id = str(getattr(address, "address_id", "") or "").strip()
            external_ref = str(getattr(address, "external_ref", "") or "").strip()
            key = address_id or self._clean_key(conversation_key) or external_ref
            if not key:
                raise EndpointThreadBindingError("conversation_key_required", "per_address requires address_id or conversation_key.")
            return f"address:{key}"
        if thread_strategy == "explicit_thread":
            key = self._clean_key(explicit_thread_id)
            if not key:
                raise EndpointThreadBindingError("explicit_thread_id_required", "explicit_thread requires explicit_thread_id.")
            return f"thread:{key}"
        key = self._clean_key(conversation_key)
        if not key:
            raise EndpointThreadBindingError("conversation_key_required", "per_conversation requires conversation_key.")
        return f"conversation:{key}"

    def resolve_thread(
        self,
        *,
        principal_id,
        endpoint_row_id,
        endpoint_public_id: str,
        workspace_row_id,
        workspace_public_id: str = "",
        thread_strategy: str = "per_conversation",
        conversation_key: str = "",
        address_row_id=None,
        title: str = "",
        display_name: str = "",
        explicit_thread_id: str = "",
        metadata: dict | None = None,
    ):
        strategy = str(thread_strategy or "per_conversation").strip() or "per_conversation"
        if strategy not in self._VALID_STRATEGIES:
            raise EndpointThreadBindingError("unsupported_thread_strategy", f"Unsupported endpoint thread strategy: {strategy}")

        with self.session_scope() as session:
            binding_repo = EndpointThreadBindingRepository(session)
            thread_repo = ThreadRepository(session)
            address = EndpointAddressRepository(session).get_by_id(address_row_id) if address_row_id is not None else None
            canonical_key = self._canonical_key(
                thread_strategy=strategy,
                endpoint_public_id=endpoint_public_id,
                conversation_key=conversation_key,
                address=address,
                explicit_thread_id=explicit_thread_id,
            )
            binding = binding_repo.get_by_endpoint_strategy_key(
                endpoint_id=endpoint_row_id,
                thread_strategy=strategy,
                conversation_key=canonical_key,
            )
            explicit_thread = thread_repo.get_by_thread_id(explicit_thread_id) if explicit_thread_id else None
            explicit_thread_error: EndpointThreadBindingError | None = None
            if explicit_thread_id and explicit_thread is None:
                explicit_thread_error = EndpointThreadBindingError("explicit_thread_not_found", f"Unknown explicit thread: {explicit_thread_id}")
            if explicit_thread is not None:
                if str(getattr(explicit_thread, "status", "") or "") == "deleted":
                    explicit_thread_error = EndpointThreadBindingError("explicit_thread_deleted", f"Explicit thread is deleted: {explicit_thread_id}")
                elif str(getattr(explicit_thread, "principal_id", "") or "") != str(principal_id or ""):
                    explicit_thread_error = EndpointThreadBindingError("explicit_thread_forbidden", "Explicit thread does not belong to the current principal.")
                elif workspace_row_id is not None and getattr(explicit_thread, "home_workspace_id", None) != workspace_row_id:
                    explicit_thread_error = EndpointThreadBindingError("explicit_thread_workspace_mismatch", "Explicit thread does not belong to the requested workspace.")
            if strategy == "explicit_thread" and explicit_thread_error is not None:
                raise explicit_thread_error
            if strategy != "explicit_thread" and explicit_thread_error is not None:
                explicit_thread = None

            thread = None
            if binding is not None:
                thread = thread_repo.get_by_id(getattr(binding, "thread_id", None))
                if thread is not None and str(getattr(thread, "status", "") or "") == "deleted":
                    thread = None
            if thread is None:
                thread = explicit_thread
            if thread is None:
                thread = thread_repo.create(
                    thread_id=f"thr_{uuid4().hex}",
                    principal_id=principal_id,
                    home_workspace_id=workspace_row_id,
                    title=str(title or display_name or canonical_key).strip()[:255],
                    metadata={
                        **dict(metadata or {}),
                        "endpoint_thread_binding": True,
                        "endpoint_id": endpoint_public_id,
                        "workspace_id": workspace_public_id,
                        "thread_strategy": strategy,
                        "conversation_key": canonical_key,
                    },
                )

            binding_metadata = {
                **dict(metadata or {}),
                "endpoint_id": endpoint_public_id,
                "workspace_id": workspace_public_id,
                "thread_id": getattr(thread, "thread_id", ""),
                "raw_conversation_key": self._clean_key(conversation_key),
                "explicit_thread_id": self._clean_key(explicit_thread_id),
            }
            binding = binding_repo.upsert(
                endpoint_id=endpoint_row_id,
                thread_id=getattr(thread, "id", None),
                workspace_id=workspace_row_id,
                address_id=address_row_id,
                thread_strategy=strategy,
                conversation_key=canonical_key,
                binding_id=self._binding_id(str(endpoint_public_id), strategy, canonical_key),
                display_name=display_name or title,
                status="active",
                metadata=binding_metadata,
            )
            return binding, thread


class ActorDeliveryPreferenceService(ServiceBase):
    def upsert_preference(
        self,
        *,
        actor_row_id,
        provider_type: str,
        address_row_id,
        alias: str = "me",
        preference_id: str = "",
        is_default: bool = True,
        verified: bool = False,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return ActorDeliveryPreferenceRepository(session).upsert(
                actor_id=actor_row_id,
                provider_type=provider_type,
                address_id=address_row_id,
                alias=alias,
                preference_id=preference_id,
                is_default=is_default,
                verified=verified,
                metadata=metadata,
            )

    def list_for_actor(self, *, actor_row_id, provider_type: str = "", alias: str = ""):
        with self.session_scope() as session:
            return ActorDeliveryPreferenceRepository(session).list_for_actor(
                actor_id=actor_row_id,
                provider_type=str(provider_type or "").strip(),
                alias=str(alias or "").strip(),
            )

    def get_default(self, *, actor_row_id, provider_type: str, alias: str = "me"):
        with self.session_scope() as session:
            return ActorDeliveryPreferenceRepository(session).get_default(
                actor_id=actor_row_id,
                provider_type=str(provider_type or "").strip(),
                alias=str(alias or "me").strip() or "me",
            )


class EndpointOutboxService(ServiceBase):
    def enqueue(
        self,
        *,
        target_endpoint_id,
        target_address_id=None,
        message_type: str,
        payload: dict,
        available_at=None,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return EndpointOutboxRepository(session).create(
                outbox_id=f"outbox_{uuid4().hex}",
                target_endpoint_id=target_endpoint_id,
                target_address_id=target_address_id,
                message_type=message_type,
                payload=payload,
                available_at=available_at,
                metadata=metadata,
            )

    def list_due(self, *, target_endpoint_id=None, limit: int = 50):
        with self.session_scope() as session:
            return EndpointOutboxRepository(session).list_due(
                target_endpoint_id=target_endpoint_id,
                limit=limit,
            )

    def mark_inflight(self, *, outbox_id):
        with self.session_scope() as session:
            return EndpointOutboxRepository(session).mark_inflight(outbox_id=outbox_id)

    def mark_sent(self, *, outbox_id):
        with self.session_scope() as session:
            return EndpointOutboxRepository(session).mark_sent(outbox_id=outbox_id)

    def reschedule_failure(
        self,
        *,
        outbox_id,
        error: str,
        max_attempts: int = 5,
        base_delay_seconds: int = 2,
        max_delay_seconds: int = 300,
    ):
        with self.session_scope() as session:
            return EndpointOutboxRepository(session).reschedule_failure(
                outbox_id=outbox_id,
                error=error,
                max_attempts=max_attempts,
                base_delay_seconds=base_delay_seconds,
                max_delay_seconds=max_delay_seconds,
            )


class DeliveryAttemptService(ServiceBase):
    def record(
        self,
        *,
        target_endpoint_id,
        target_address_id=None,
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
                target_address_id=target_address_id,
                message_type=message_type,
                payload=payload,
                status=status,
                error=error,
                metadata=metadata,
            )
