from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from core.runtime_context import get_event_context
from core.services.tool_router_service import ToolRouterError


_ONLINE_ENDPOINT_STATUSES = {"online", "ready", "active"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tool_error(code: str, message: str, *, details: dict[str, Any] | None = None, retryable: bool = False) -> RuntimeError:
    error = RuntimeError(message)
    error.tool_error_code = code
    error.tool_error_message = message
    error.tool_error_details = dict(details or {})
    error.tool_error_retryable = retryable
    return error


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


def _workspace_ids_for_endpoint(domain, endpoint) -> list[str]:
    """Return the same workspace ids used by the operator topology UI."""
    endpoint_row_id = getattr(endpoint, "id", None)
    membership_service = getattr(getattr(domain, "services", None), "endpoint_workspace_membership", None)
    workspace_service = getattr(getattr(domain, "services", None), "workspace", None)
    workspace_ids: list[str] = []
    if membership_service is not None and workspace_service is not None and endpoint_row_id is not None:
        try:
            rows = membership_service.list_for_endpoint(endpoint_row_id=endpoint_row_id)
        except Exception:
            rows = []
        for row in rows or []:
            workspace = None
            try:
                workspace = workspace_service.get_by_id(getattr(row, "workspace_id", None))
            except Exception:
                workspace = None
            workspace_id = str(getattr(workspace, "workspace_id", "") or "").strip()
            if workspace_id and workspace_id not in workspace_ids:
                workspace_ids.append(workspace_id)
    fallback = _string_list(getattr(endpoint, "workspace_scope", []) or [])
    for workspace_id in fallback:
        if workspace_id and workspace_id not in workspace_ids:
            workspace_ids.append(workspace_id)
    return workspace_ids


def _workspace_matches(workspace_key: str, workspace_ids: list[str]) -> bool:
    normalized = str(workspace_key or "").strip()
    if not normalized:
        return True
    return normalized in workspace_ids or "*" in workspace_ids


def _compact_endpoint_payload(endpoint: dict[str, Any]) -> dict[str, Any]:
    return {
        "endpoint_id": str(endpoint.get("endpoint_id") or ""),
        "display_name": str(endpoint.get("display_name") or ""),
        "provider_type": str(endpoint.get("provider_type") or ""),
        "status": str(endpoint.get("status") or ""),
        "connected": bool(endpoint.get("connected")),
        "workspace_ids": _string_list(endpoint.get("workspace_ids") or []),
        "executable_tools": _string_list(endpoint.get("executable_tools") or endpoint.get("tool_keys") or []),
    }


def _metadata_summary(metadata: Any) -> dict[str, Any]:
    payload = dict(metadata or {}) if isinstance(metadata, dict) else {}
    rendered = ""
    if payload:
        try:
            import json

            rendered = json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            rendered = str(payload)
    return {
        "key_count": len(payload),
        "keys": sorted(str(key) for key in payload.keys()),
        "byte_size_estimate": len(rendered.encode("utf-8", errors="ignore")) if rendered else 0,
    }


def _endpoint_inventory_summary(compact: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        compact,
        key=lambda item: (
            0 if item.get("executable_tools") else 1,
            str(item.get("provider_type") or "").lower(),
            str(item.get("endpoint_id") or "").lower(),
        ),
    )
    lines: list[str] = []
    tools_by_endpoint: dict[str, list[str]] = {}
    for item in ordered:
        endpoint_id = str(item.get("endpoint_id") or "")
        if not endpoint_id:
            continue
        tools = _string_list(item.get("executable_tools") or [])
        tools_by_endpoint[endpoint_id] = tools
        tool_text = ", ".join(tools) if tools else "(none)"
        lines.append(
            f"{endpoint_id} | provider={item.get('provider_type') or ''} | status={item.get('status') or ''} | tools={tool_text}"
        )
    return {
        "tool_target_lines": lines,
        "executable_tools_by_endpoint": tools_by_endpoint,
        "endpoint_ids": [item["endpoint_id"] for item in ordered if item.get("endpoint_id")],
        "compact_endpoints": ordered,
    }


def _address_payload(address, *, endpoint=None, preference=None, include_metadata: bool = False) -> dict[str, Any]:
    endpoint_id = str(getattr(endpoint, "endpoint_id", "") or "")
    metadata = dict(getattr(address, "meta", {}) or {})
    payload = {
        "address_id": str(getattr(address, "address_id", "") or ""),
        "endpoint_id": endpoint_id,
        "provider_type": str(getattr(address, "provider_type", "") or ""),
        "address_type": str(getattr(address, "address_type", "") or ""),
        "external_ref": str(getattr(address, "external_ref", "") or ""),
        "display_name": str(getattr(address, "display_name", "") or getattr(address, "external_ref", "") or ""),
        "workspace_ids": _string_list(getattr(address, "workspace_scope", []) or []),
        "status": str(getattr(address, "status", "") or "unknown"),
        "capabilities": _string_list(getattr(address, "capabilities", []) or []),
        "bound": preference is not None,
        "alias": str(getattr(preference, "alias", "") or "") if preference is not None else "",
        "is_default": bool(getattr(preference, "is_default", False)) if preference is not None else False,
        "verified": bool(getattr(preference, "verified", False)) if preference is not None else False,
        "metadata_summary": _metadata_summary(metadata),
    }
    if include_metadata:
        payload["metadata"] = metadata
    return payload


def _compact_address_payload(address: dict[str, Any]) -> dict[str, Any]:
    return {
        "address_id": str(address.get("address_id") or ""),
        "endpoint_id": str(address.get("endpoint_id") or ""),
        "provider_type": str(address.get("provider_type") or ""),
        "address_type": str(address.get("address_type") or ""),
        "external_ref": str(address.get("external_ref") or ""),
        "display_name": str(address.get("display_name") or ""),
        "workspace_ids": _string_list(address.get("workspace_ids") or []),
        "status": str(address.get("status") or ""),
        "bound": bool(address.get("bound")),
        "alias": str(address.get("alias") or ""),
    }


def _delivery_target_summary(addresses: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        [_compact_address_payload(address) for address in addresses],
        key=lambda item: (
            str(item.get("provider_type") or "").lower(),
            str(item.get("address_type") or "").lower(),
            str(item.get("display_name") or "").lower(),
            str(item.get("address_id") or "").lower(),
        ),
    )
    lines: list[str] = []
    for item in ordered:
        address_id = str(item.get("address_id") or "")
        if not address_id:
            continue
        workspace_text = ",".join(_string_list(item.get("workspace_ids") or [])) or "(none)"
        display_name = str(item.get("display_name") or item.get("external_ref") or "")
        lines.append(
            f"{address_id} | provider={item.get('provider_type') or ''} | type={item.get('address_type') or ''} | "
            f"status={item.get('status') or ''} | workspace_ids={workspace_text} | name={display_name}"
        )
    return {
        "delivery_target_lines": lines,
        "address_ids": [item["address_id"] for item in ordered if item.get("address_id")],
        "compact_addresses": ordered,
    }


def _origin_endpoint_id_from_context() -> str:
    context = get_event_context()
    for key in ("origin_endpoint_id", "endpoint_id", "source_id"):
        value = str(context.get(key) or "").strip()
        if value:
            return value
    source = context.get("source")
    metadata = getattr(source, "metadata", {}) if source is not None else {}
    if isinstance(metadata, dict):
        for key in ("endpoint_id", "origin_endpoint_id"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
    return ""


class EndpointTools:
    def __init__(self):
        self._core_domain = None
        self._gateway_getter = None

    def set_core_domain(self, core_domain) -> None:
        self._core_domain = core_domain

    def set_runtime(self, *, gateway_getter=None) -> None:
        self._gateway_getter = gateway_getter

    def _domain(self):
        if self._core_domain is None:
            raise _tool_error("core_domain_unavailable", "Core domain is unavailable.")
        return self._core_domain

    def _gateway(self):
        gateway = self._gateway_getter() if callable(self._gateway_getter) else None
        if gateway is None:
            raise _tool_error("gateway_unavailable", "Gateway runtime is unavailable.", retryable=True)
        return gateway

    def _workspace_row(self, workspace_id: str = "", *, session_id: str = ""):
        domain = self._domain()
        normalized_workspace_id = str(workspace_id or "").strip()
        if normalized_workspace_id:
            workspace = domain.services.workspace.get_by_workspace_id(normalized_workspace_id)
            if workspace is None:
                raise _tool_error("workspace_not_found", f"Unknown workspace: {normalized_workspace_id}")
            return workspace
        normalized_session_id = str(session_id or "").strip()
        if normalized_session_id:
            session = domain.services.session.get_by_session_id(normalized_session_id)
            if session is not None:
                row_id = getattr(session, "active_workspace_id", None)
                if row_id is not None:
                    workspace = domain.services.workspace.get_by_id(row_id)
                    if workspace is not None:
                        return workspace
        return None

    def _current_actor(self):
        domain = self._domain()
        principal = getattr(domain, "principal", None)
        principal_key = str(getattr(principal, "principal_key", "") or "self").strip() or "self"
        actor = domain.services.actor.get_by_actor_id(f"user:{principal_key}")
        if actor is None:
            actor = domain.services.actor.ensure_actor(
                actor_id=f"user:{principal_key}",
                actor_type="user",
                owner_user_id=principal_key,
                display_name=str(getattr(principal, "display_name", "") or principal_key),
                permission_profile_id="profile.default_user",
                metadata={"principal_key": principal_key},
            )
        return actor

    def _endpoint_for_address(self, address):
        endpoint = self._domain().services.endpoint.get_by_id(getattr(address, "endpoint_id", None))
        if endpoint is None:
            raise _tool_error("endpoint_not_found", f"Endpoint for address is missing: {getattr(address, 'address_id', '')}")
        return endpoint

    def _resolve_address(
        self,
        *,
        address_id: str = "",
        actor_ref: str = "",
        provider_type: str = "",
        alias: str = "me",
    ):
        domain = self._domain()
        normalized_address_id = str(address_id or "").strip()
        if normalized_address_id:
            address = domain.services.endpoint_address.get_by_address_id(normalized_address_id)
            if address is None:
                raise _tool_error("address_not_found", f"Unknown delivery address: {normalized_address_id}")
            return address, None
        normalized_actor_ref = str(actor_ref or "").strip().lower()
        if normalized_actor_ref in {"me", "self", "我"}:
            actor = self._current_actor()
            normalized_provider = str(provider_type or "").strip().lower()
            if not normalized_provider:
                raise _tool_error("provider_type_required", "provider_type is required when resolving actor_ref=me.")
            preference = domain.services.actor_delivery_preference.get_default(
                actor_row_id=actor.id,
                provider_type=normalized_provider,
                alias=str(alias or "me").strip() or "me",
            )
            if preference is None:
                return None, {
                    "requires_binding": True,
                    "actor_ref": "me",
                    "provider_type": normalized_provider,
                    "alias": str(alias or "me").strip() or "me",
                    "message": "No verified delivery preference is bound for this actor/provider.",
                }
            address = domain.services.endpoint_address.get_by_id(getattr(preference, "address_id", None))
            if address is None:
                return None, {
                    "requires_binding": True,
                    "actor_ref": "me",
                    "provider_type": normalized_provider,
                    "alias": str(alias or "me").strip() or "me",
                    "message": "The bound delivery address no longer exists.",
                }
            return address, preference
        raise _tool_error("delivery_target_required", "Specify address_id or actor_ref=me with provider_type.")

    def _endpoint_payload(self, endpoint, *, connected: bool = False, snapshots: list[dict[str, Any]] | None = None, include_capabilities: bool = True) -> dict[str, Any]:
        rows = list(snapshots or [])
        first = rows[0] if rows else {}
        provider = first.get("provider") if isinstance(first.get("provider"), dict) else {}
        endpoint_id = str(getattr(endpoint, "endpoint_id", "") or first.get("endpoint_id") or "")
        capabilities: list[dict[str, Any]] = []
        tool_keys: list[str] = []
        if include_capabilities:
            for capability in self._domain().services.endpoint_capability.list_for_endpoint(endpoint_row_id=getattr(endpoint, "id", None)):
                if bool(getattr(capability, "enabled", True)):
                    tool_key = str(getattr(capability, "tool_key", "") or "").strip()
                    if tool_key and tool_key not in tool_keys:
                        tool_keys.append(tool_key)
                capabilities.append(
                    {
                        "capability_id": str(getattr(capability, "capability_id", "") or ""),
                        "tool_key": str(getattr(capability, "tool_key", "") or ""),
                        "risk_level": str(getattr(capability, "risk_level", "") or "read"),
                        "requires_confirmation": bool(getattr(capability, "requires_confirmation", False)),
                        "enabled": bool(getattr(capability, "enabled", True)),
                    }
                )
        else:
            tool_keys = _string_list(
                getattr(capability, "tool_key", "")
                for capability in self._domain().services.endpoint_capability.list_for_endpoint(endpoint_row_id=getattr(endpoint, "id", None))
                if getattr(capability, "enabled", True)
            )
        workspace_ids = _workspace_ids_for_endpoint(self._domain(), endpoint)
        raw_status = str(getattr(endpoint, "status", "") or "").strip()
        effective_status = "online" if connected and raw_status.lower() not in _ONLINE_ENDPOINT_STATUSES else raw_status
        payload = {
            "endpoint_id": endpoint_id,
            "display_name": str(provider.get("display_name") or getattr(endpoint, "meta", {}).get("display_name", "") or endpoint_id),
            "endpoint_type": str(getattr(endpoint, "endpoint_type", "") or ""),
            "provider_type": str(getattr(endpoint, "provider_type", "") or ""),
            "transport_type": str(getattr(endpoint, "transport_type", "") or ""),
            "status": effective_status or ("online" if connected else ""),
            "connected": bool(connected),
            "connection_count": len(rows),
            "workspace_ids": workspace_ids,
            "tool_keys": tool_keys,
            "executable_tools": tool_keys,
            "capability_count": len(tool_keys),
            "capability_details_included": bool(include_capabilities),
            "capabilities": capabilities,
            "last_seen_at": getattr(endpoint, "updated_at", "").isoformat()
            if getattr(endpoint, "updated_at", None) is not None
            else "",
            "connected_at": str(first.get("connected_at") or ""),
            "updated_at": str(first.get("updated_at") or ""),
            "provider": provider,
        }
        return payload

    async def list_active_endpoints(
        self,
        workspace_id: str = "",
        thread_id: str = "",
        include_tools: bool = True,
        include_capability_details: bool = False,
        session_id: str = "",
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        domain = self._domain()
        gateway = self._gateway()
        workspace = self._workspace_row(workspace_id, session_id=session_id)
        del thread_id
        connected_ids = await gateway.endpoint_ws_manager.connected_endpoint_ids()
        snapshot = await gateway.endpoint_ws_manager.snapshot()
        snapshots_by_endpoint: dict[str, list[dict[str, Any]]] = {}
        for item in snapshot:
            endpoint_id = str(item.get("endpoint_id") or "").strip()
            if endpoint_id:
                snapshots_by_endpoint.setdefault(endpoint_id, []).append(item)

        endpoints = list(domain.services.endpoint.list_all())
        workspace_key = str(getattr(workspace, "workspace_id", "") or "").strip()

        results: list[dict[str, Any]] = []
        for endpoint in endpoints:
            endpoint_id = str(getattr(endpoint, "endpoint_id", "") or "").strip()
            workspace_ids = _workspace_ids_for_endpoint(domain, endpoint)
            if not _workspace_matches(workspace_key, workspace_ids):
                continue
            if not endpoint_id or endpoint_id not in connected_ids:
                continue
            payload = self._endpoint_payload(
                endpoint,
                connected=True,
                snapshots=snapshots_by_endpoint.get(endpoint_id, []),
                include_capabilities=include_capability_details,
            )
            if not include_tools:
                payload["tool_keys"] = []
                payload["executable_tools"] = []
            results.append(payload)
        results.sort(
            key=lambda item: (
                0 if (item.get("executable_tools") or item.get("tool_keys")) else 1,
                str(item.get("display_name") or "").lower(),
                str(item.get("endpoint_id") or ""),
            )
        )
        compact = [_compact_endpoint_payload(item) for item in results]
        summary = _endpoint_inventory_summary(compact)
        return {
            "ok": True,
            "count": len(results),
            **summary,
            "endpoints": results,
        }

    async def list_endpoint_tool_targets(
        self,
        workspace_id: str = "",
        tool_key: str = "",
        include_tools: bool = True,
        include_capability_details: bool = False,
        session_id: str = "",
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        domain = self._domain()
        workspace = self._workspace_row(workspace_id, session_id=session_id)
        normalized_tool_key = str(tool_key or "").strip()
        connected_ids = await self._gateway().endpoint_ws_manager.connected_endpoint_ids()

        endpoint_rows = list(domain.services.endpoint.list_all())
        workspace_key = str(getattr(workspace, "workspace_id", "") or "").strip()

        targets: list[dict[str, Any]] = []
        for endpoint in endpoint_rows:
            endpoint_id = str(getattr(endpoint, "endpoint_id", "") or "").strip()
            workspace_ids = _workspace_ids_for_endpoint(domain, endpoint)
            if not _workspace_matches(workspace_key, workspace_ids):
                continue
            if not endpoint_id or endpoint_id not in connected_ids:
                continue
            capabilities = domain.services.endpoint_capability.list_for_endpoint(endpoint_row_id=endpoint.id)
            tool_keys = _string_list(getattr(capability, "tool_key", "") for capability in capabilities if getattr(capability, "enabled", True))
            if normalized_tool_key and normalized_tool_key not in tool_keys:
                continue
            snapshots = await self._gateway().endpoint_ws_manager.snapshot(endpoint_id=endpoint_id)
            payload = self._endpoint_payload(
                endpoint,
                connected=True,
                snapshots=snapshots,
                include_capabilities=include_capability_details,
            )
            if not include_tools:
                payload["tool_keys"] = []
                payload["executable_tools"] = []
            if normalized_tool_key:
                payload["matched_tool_key"] = normalized_tool_key
            targets.append(payload)
        targets.sort(
            key=lambda item: (
                0 if str(item.get("provider_type") or "").lower() == "desktop" else 1,
                str(item.get("display_name") or "").lower(),
                str(item.get("endpoint_id") or ""),
            )
        )
        compact = [_compact_endpoint_payload(item) for item in targets]
        summary = _endpoint_inventory_summary(compact)
        return {
            "ok": True,
            "count": len(targets),
            "workspace_id": str(getattr(workspace, "workspace_id", "") or workspace_id or ""),
            "tool_key": normalized_tool_key,
            **summary,
            "endpoints": targets,
        }

    async def list_delivery_targets(
        self,
        provider_type: str = "",
        actor_ref: str = "",
        address_type: str = "",
        workspace_id: str = "",
        include_unavailable: bool = False,
        include_metadata: bool = False,
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        domain = self._domain()
        normalized_provider = str(provider_type or "").strip().lower()
        normalized_actor_ref = str(actor_ref or "").strip().lower()
        normalized_workspace = str(workspace_id or get_event_context().get("workspace_id") or "").strip()
        addresses = list(
            domain.services.endpoint_address.list_addresses(
                provider_type=normalized_provider,
                address_type=str(address_type or "").strip().lower(),
                workspace_id=normalized_workspace,
            )
        )
        if not include_unavailable:
            addresses = [row for row in addresses if str(getattr(row, "status", "") or "").strip().lower() in {"sendable", "unknown"}]
        preference_by_address: dict[str, Any] = {}
        requires_binding = False
        if normalized_actor_ref in {"me", "self", "我"}:
            actor = self._current_actor()
            preferences = domain.services.actor_delivery_preference.list_for_actor(
                actor_row_id=actor.id,
                provider_type=normalized_provider,
                alias="me",
            )
            preference_by_address = {str(getattr(pref, "address_id", "") or ""): pref for pref in preferences}
            if normalized_provider and not preferences:
                requires_binding = True
        payloads: list[dict[str, Any]] = []
        for address in addresses:
            endpoint = domain.services.endpoint.get_by_id(getattr(address, "endpoint_id", None))
            preference = preference_by_address.get(str(getattr(address, "id", "") or ""))
            payloads.append(_address_payload(address, endpoint=endpoint, preference=preference, include_metadata=include_metadata))
        summary = _delivery_target_summary(payloads)
        return {
            "ok": True,
            "count": len(payloads),
            "requires_binding": requires_binding,
            "provider_type": normalized_provider,
            "actor_ref": normalized_actor_ref,
            **summary,
            "addresses": payloads,
        }

    async def set_delivery_preference(
        self,
        provider_type: str,
        address_id: str,
        actor_ref: str = "me",
        alias: str = "me",
        verified: bool = True,
        is_default: bool = True,
        metadata: dict[str, Any] | None = None,
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        normalized_actor_ref = str(actor_ref or "me").strip().lower()
        if normalized_actor_ref not in {"me", "self", "我"}:
            raise _tool_error("unsupported_actor_ref", "Only actor_ref=me is supported for delivery preferences.")
        domain = self._domain()
        actor = self._current_actor()
        address = domain.services.endpoint_address.get_by_address_id(str(address_id or "").strip())
        if address is None:
            raise _tool_error("address_not_found", f"Unknown delivery address: {address_id}")
        normalized_provider = str(provider_type or getattr(address, "provider_type", "") or "").strip().lower()
        if normalized_provider and normalized_provider != str(getattr(address, "provider_type", "") or "").strip().lower():
            raise _tool_error("provider_type_mismatch", "The selected address does not belong to the requested provider_type.")
        preference = domain.services.actor_delivery_preference.upsert_preference(
            actor_row_id=actor.id,
            provider_type=normalized_provider,
            address_row_id=address.id,
            alias=str(alias or "me").strip() or "me",
            is_default=bool(is_default),
            verified=bool(verified),
            metadata={
                **dict(metadata or {}),
                "bound_at": _utcnow_iso(),
                "actor_ref": "me",
            },
        )
        endpoint = domain.services.endpoint.get_by_id(getattr(address, "endpoint_id", None))
        return {
            "ok": True,
            "preference_id": str(getattr(preference, "preference_id", "") or ""),
            "target": _address_payload(address, endpoint=endpoint, preference=preference, include_metadata=True),
        }

    async def _send_notice(self, *, target_type: str, target_id: str, content: str, session_id: str = "", workspace_id: str = "") -> dict[str, Any]:
        gateway = self._gateway()
        target = str(target_type or "endpoint").strip().lower()
        normalized_target_id = str(target_id or "").strip()
        text = str(content or "").strip()
        if target != "endpoint":
            raise _tool_error("unsupported_target_type", f"Unsupported target_type: {target_type}")
        if not normalized_target_id:
            raise _tool_error("target_endpoint_id_required", "target_id is required for endpoint delivery.")
        if not text:
            raise _tool_error("content_required", "content is required for notice delivery.")
        origin_endpoint_id = _origin_endpoint_id_from_context()
        if origin_endpoint_id and normalized_target_id == origin_endpoint_id:
            raise _tool_error(
                "same_origin_endpoint_notice_forbidden",
                "Do not use send_endpoint_message to reply to the originating endpoint. "
                "Return the final assistant answer normally, or use emit_progress_notice for progress.",
                details={"target_endpoint_id": normalized_target_id},
            )
        endpoint = self._domain().services.endpoint.get_by_endpoint_id(normalized_target_id)
        if endpoint is None:
            raise _tool_error("endpoint_not_found", f"Unknown endpoint: {normalized_target_id}")

        message_id = f"notice_{uuid4().hex}"
        delivered_count = await gateway.endpoint_ws_manager.publish_notice(
            target_endpoint_id=normalized_target_id,
            payload={
                "notice_id": message_id,
                "target_endpoint_id": normalized_target_id,
                "session_id": str(session_id or ""),
                "workspace_id": str(workspace_id or ""),
                "content": text,
                "created_at": _utcnow_iso(),
                "metadata": {
                    "runtime_action": "delivery.notice",
                    "target_type": "endpoint",
                    "target_id": normalized_target_id,
                },
            },
        )
        if delivered_count <= 0:
            raise _tool_error("endpoint_delivery_failed", f"Endpoint delivery failed: {normalized_target_id}", retryable=True)
        return {
            "ok": True,
            "delivered": True,
            "target_type": "endpoint",
            "target_id": normalized_target_id,
            "connection_count": delivered_count,
            "notice_id": message_id,
        }

    async def _send_tool_call(
        self,
        *,
        target_type: str,
        target_id: str,
        tool_key: str,
        arguments: dict[str, Any] | None,
        workspace_id: str = "",
        session_id: str = "",
        timeout_seconds: int = 120,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        domain = self._domain()
        dispatcher = getattr(domain, "tool_router", None)
        if dispatcher is None:
            raise _tool_error("tool_router_unavailable", "ToolRouter is unavailable.", retryable=True)
        target = str(target_type or "endpoint").strip().lower()
        normalized_target_id = str(target_id or "").strip()
        normalized_tool_key = str(tool_key or "").strip()
        normalized_session_id = str(session_id or get_event_context().get("session_id") or "").strip()
        normalized_workspace_id = str(workspace_id or get_event_context().get("workspace_id") or "").strip()
        if target != "endpoint":
            raise _tool_error("unsupported_target_type", f"Unsupported target_type: {target_type}")
        if not normalized_target_id:
            raise _tool_error("target_endpoint_id_required", "target_id is required for endpoint tool calls.")
        if not normalized_tool_key:
            raise _tool_error("tool_key_required", "tool_key is required for tool_call delivery.")

        try:
            result = await dispatcher.dispatch_tool_call(
                tool_key=normalized_tool_key,
                arguments=dict(arguments or {}),
                target_endpoint_id=normalized_target_id,
                session_id=normalized_session_id,
                workspace_id=normalized_workspace_id,
                title=f"Endpoint tool call: {normalized_tool_key}",
                timeout_seconds=int(timeout_seconds or 120),
                confirmed=bool(confirmed),
            )
        except ToolRouterError:
            raise
        return {
            "ok": True,
            "target_type": "endpoint",
            "target_id": normalized_target_id,
            "target_endpoint_id": normalized_target_id,
            "tool_key": normalized_tool_key,
            "result": result,
        }

    async def send_endpoint_message(
        self,
        target_type: str,
        target_id: str,
        delivery_kind: str = "notice",
        content: str = "",
        tool_key: str = "",
        arguments: dict[str, Any] | None = None,
        workspace_id: str = "",
        session_id: str = "",
        timeout_seconds: int = 120,
        confirmed: bool = False,
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        kind = str(delivery_kind or "notice").strip().lower()
        if kind == "notice":
            return await self._send_notice(
                target_type=target_type,
                target_id=target_id,
                content=content,
                session_id=session_id,
                workspace_id=workspace_id,
            )
        if kind == "tool_call":
            return await self._send_tool_call(
                target_type=target_type,
                target_id=target_id,
                tool_key=tool_key,
                arguments=arguments,
                workspace_id=workspace_id,
                session_id=session_id,
                timeout_seconds=timeout_seconds,
                confirmed=confirmed,
            )
        raise _tool_error("unsupported_delivery_kind", f"Unsupported delivery_kind: {delivery_kind}")

    async def send_delivery_message(
        self,
        content: str,
        address_id: str = "",
        actor_ref: str = "",
        provider_type: str = "",
        alias: str = "me",
        message_type: str = "notice",
        offline_policy: str = "store_and_retry",
        workspace_id: str = "",
        session_id: str = "",
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        text = str(content or "").strip()
        if not text:
            raise _tool_error("content_required", "content is required.")
        address, preference = self._resolve_address(
            address_id=address_id,
            actor_ref=actor_ref,
            provider_type=provider_type,
            alias=alias,
        )
        if address is None:
            return {"ok": False, **dict(preference or {})}
        endpoint = self._endpoint_for_address(address)
        result = await self._domain().services.delivery.deliver_to_address(
            target_endpoint=endpoint,
            target_address=address,
            message_type=str(message_type or "notice").strip() or "notice",
            payload={
                "notice_id": f"notice_{uuid4().hex}",
                "content": text,
                "workspace_id": str(workspace_id or get_event_context().get("workspace_id") or ""),
                "session_id": str(session_id or get_event_context().get("session_id") or ""),
                "created_at": _utcnow_iso(),
                "metadata": {
                    "runtime_action": "delivery.address_message",
                    "actor_ref": str(actor_ref or ""),
                    "provider_type": str(provider_type or getattr(address, "provider_type", "") or ""),
                },
            },
            offline_policy=str(offline_policy or "store_and_retry"),
        )
        return {
            "ok": True,
            "delivered": bool(result.get("sent")),
            "status": str(result.get("status") or ""),
            "target": _address_payload(address, endpoint=endpoint, preference=preference),
        }
