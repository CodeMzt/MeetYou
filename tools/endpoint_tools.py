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

    def _endpoint_payload(self, endpoint, *, connected: bool = False, snapshots: list[dict[str, Any]] | None = None, include_capabilities: bool = True) -> dict[str, Any]:
        rows = list(snapshots or [])
        first = rows[0] if rows else {}
        provider = first.get("provider") if isinstance(first.get("provider"), dict) else {}
        endpoint_id = str(getattr(endpoint, "endpoint_id", "") or first.get("endpoint_id") or "")
        capabilities: list[dict[str, Any]] = []
        if include_capabilities:
            for capability in self._domain().services.endpoint_capability.list_for_endpoint(endpoint_row_id=getattr(endpoint, "id", None)):
                capabilities.append(
                    {
                        "capability_id": str(getattr(capability, "capability_id", "") or ""),
                        "tool_key": str(getattr(capability, "tool_key", "") or ""),
                        "risk_level": str(getattr(capability, "risk_level", "") or "read"),
                        "requires_confirmation": bool(getattr(capability, "requires_confirmation", False)),
                        "enabled": bool(getattr(capability, "enabled", True)),
                    }
                )
        payload = {
            "endpoint_id": endpoint_id,
            "display_name": str(provider.get("display_name") or getattr(endpoint, "meta", {}).get("display_name", "") or endpoint_id),
            "endpoint_type": str(getattr(endpoint, "endpoint_type", "") or ""),
            "provider_type": str(getattr(endpoint, "provider_type", "") or ""),
            "transport_type": str(getattr(endpoint, "transport_type", "") or ""),
            "status": str(getattr(endpoint, "status", "") or ("online" if connected else "")),
            "connected": bool(connected),
            "connection_count": len(rows),
            "workspace_ids": _string_list(getattr(endpoint, "workspace_scope", []) or []),
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
        session_id: str = "",
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        domain = self._domain()
        gateway = self._gateway()
        workspace = self._workspace_row(workspace_id, session_id=session_id)
        del thread_id
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
            workspace_scope = _string_list(getattr(endpoint, "workspace_scope", []) or [])
            if workspace_key and workspace_key not in workspace_scope and "*" not in workspace_scope:
                continue
            if not endpoint_id or endpoint_id not in snapshots_by_endpoint:
                continue
            if str(getattr(endpoint, "status", "") or "").strip().lower() not in _ONLINE_ENDPOINT_STATUSES:
                continue
            payload = self._endpoint_payload(
                endpoint,
                connected=True,
                snapshots=snapshots_by_endpoint.get(endpoint_id, []),
                include_capabilities=include_tools,
            )
            results.append(payload)
        results.sort(key=lambda item: (str(item.get("display_name") or "").lower(), str(item.get("endpoint_id") or "")))
        return {"ok": True, "count": len(results), "endpoints": results}

    async def list_endpoint_tool_targets(
        self,
        workspace_id: str = "",
        tool_key: str = "",
        include_tools: bool = True,
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
            workspace_scope = _string_list(getattr(endpoint, "workspace_scope", []) or [])
            if workspace_key and workspace_key not in workspace_scope and "*" not in workspace_scope:
                continue
            if not endpoint_id or endpoint_id not in connected_ids:
                continue
            if str(getattr(endpoint, "status", "") or "").strip().lower() not in _ONLINE_ENDPOINT_STATUSES:
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
                include_capabilities=include_tools,
            )
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
        return {
            "ok": True,
            "count": len(targets),
            "workspace_id": str(getattr(workspace, "workspace_id", "") or workspace_id or ""),
            "tool_key": normalized_tool_key,
            "endpoints": targets,
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
