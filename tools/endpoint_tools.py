from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from client_tool_protocol import build_client_message
from core.runtime_context import get_event_context
from core.services.client_tool_dispatch_service import ClientToolDispatchError


_ONLINE_CLIENT_STATUSES = {"online", "ready", "active"}


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

    @staticmethod
    def _client_payload(client, *, connected: bool = False, snapshots: list[dict[str, Any]] | None = None, workspace_ids: list[str] | None = None) -> dict[str, Any]:
        rows = list(snapshots or [])
        first = rows[0] if rows else {}
        return {
            "client_id": str(getattr(client, "client_id", "") or first.get("client_id") or ""),
            "display_name": str(first.get("display_name") or getattr(client, "display_name", "") or ""),
            "client_type": str(first.get("client_type") or getattr(client, "client_type", "") or ""),
            "status": str(getattr(client, "status", "") or ("online" if connected else "")),
            "connected": bool(connected),
            "connection_count": len(rows),
            "thread_ids": _string_list(item.get("thread_id") for item in rows),
            "session_ids": _string_list(item.get("session_id") for item in rows),
            "workspace_ids": _string_list(workspace_ids or [item.get("workspace_id") for item in rows]),
            "transport_profile": str(first.get("transport_profile") or getattr(client, "transport_profile", "") or ""),
            "available_tools": _string_list(first.get("available_tools") or getattr(client, "available_tools", []) or []),
            "executable_tools": _string_list(first.get("executable_tools") or getattr(client, "executable_tools", []) or []),
            "last_seen_at": getattr(client, "last_seen_at", "").isoformat()
            if getattr(client, "last_seen_at", None) is not None
            else "",
            "connected_at": str(first.get("connected_at") or ""),
            "updated_at": str(first.get("updated_at") or ""),
            "host": dict(first.get("host") or {
                "name": getattr(client, "host_name", ""),
                "os": getattr(client, "host_os", ""),
                "arch": getattr(client, "host_arch", ""),
            }),
        }

    def _workspace_ids_for_client(self, client_id: str) -> list[str]:
        domain = self._domain()
        rows = domain.services.client.list_workspace_bindings(client_id)
        return _string_list(getattr(workspace, "workspace_id", "") for workspace, _membership in rows)

    async def list_active_clients(
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
        snapshot = await gateway.client_ws_manager.snapshot(
            thread_id=thread_id,
            workspace_id=str(getattr(workspace, "workspace_id", "") or ""),
        )
        snapshots_by_client: dict[str, list[dict[str, Any]]] = {}
        for item in snapshot:
            client_id = str(item.get("client_id") or "").strip()
            if client_id:
                snapshots_by_client.setdefault(client_id, []).append(item)

        if workspace is not None:
            client_rows = [client for client, _membership in domain.services.client.list_clients_for_workspace(workspace.id)]
        else:
            client_rows = list(domain.services.client.list_clients())

        clients: list[dict[str, Any]] = []
        for client in client_rows:
            client_id = str(getattr(client, "client_id", "") or "").strip()
            if not client_id or client_id not in snapshots_by_client:
                continue
            if str(getattr(client, "status", "") or "").strip().lower() not in _ONLINE_CLIENT_STATUSES:
                continue
            payload = self._client_payload(
                client,
                connected=True,
                snapshots=snapshots_by_client.get(client_id, []),
                workspace_ids=self._workspace_ids_for_client(client_id),
            )
            if not include_tools:
                payload.pop("available_tools", None)
                payload.pop("executable_tools", None)
            clients.append(payload)
        clients.sort(key=lambda item: (str(item.get("display_name") or "").lower(), str(item.get("client_id") or "")))
        return {"ok": True, "count": len(clients), "clients": clients}

    async def list_client_tool_targets(
        self,
        workspace_id: str = "",
        tool_key: str = "",
        include_tools: bool = True,
        session_id: str = "",
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        domain = self._domain()
        gateway = self._gateway()
        workspace = self._workspace_row(workspace_id, session_id=session_id)
        normalized_tool_key = str(tool_key or "").strip()
        connected_ids = await gateway.client_ws_manager.connected_client_ids()

        if workspace is not None:
            rows = domain.services.client.list_tool_clients_for_workspace(
                workspace_id=workspace.id,
                tool_key=normalized_tool_key,
            )
            client_rows = [client for client, _membership in rows]
        else:
            client_rows = list(domain.services.client.list_clients())

        targets: list[dict[str, Any]] = []
        for client in client_rows:
            client_id = str(getattr(client, "client_id", "") or "").strip()
            if not client_id or client_id not in connected_ids:
                continue
            if str(getattr(client, "status", "") or "").strip().lower() not in _ONLINE_CLIENT_STATUSES:
                continue
            executable_tools = _string_list(getattr(client, "executable_tools", []) or [])
            if normalized_tool_key and normalized_tool_key not in executable_tools:
                continue
            snapshots = await gateway.client_ws_manager.snapshot(client_id=client_id)
            payload = self._client_payload(
                client,
                connected=True,
                snapshots=snapshots,
                workspace_ids=self._workspace_ids_for_client(client_id),
            )
            if normalized_tool_key:
                payload["matched_tool_key"] = normalized_tool_key
            if not include_tools:
                payload.pop("available_tools", None)
                payload.pop("executable_tools", None)
            targets.append(payload)
        targets.sort(
            key=lambda item: (
                0 if str(item.get("client_type") or "").lower() == "desktop" else 1,
                str(item.get("display_name") or "").lower(),
                str(item.get("client_id") or ""),
            )
        )
        return {
            "ok": True,
            "count": len(targets),
            "workspace_id": str(getattr(workspace, "workspace_id", "") or workspace_id or ""),
            "tool_key": normalized_tool_key,
            "clients": targets,
        }

    @staticmethod
    def _filter_client_notice_snapshot(snapshot: list[dict[str, Any]], *, session_id: str = "", workspace_id: str = "") -> list[dict[str, Any]]:
        filtered = list(snapshot or [])
        normalized_session_id = str(session_id or "").strip()
        normalized_workspace_id = str(workspace_id or "").strip()
        if normalized_session_id:
            filtered = [item for item in filtered if str(item.get("session_id") or "").strip() == normalized_session_id]
        if normalized_workspace_id:
            filtered = [item for item in filtered if str(item.get("workspace_id") or "").strip() == normalized_workspace_id]
        return filtered

    @staticmethod
    def _build_notice_message(
        *,
        client_id: str,
        thread_id: str,
        session_id: str,
        workspace_id: str,
        content: str,
        target_id: str,
    ) -> dict[str, Any]:
        return {
            "message_id": f"msg_notice_{uuid4().hex}",
            "thread_id": thread_id,
            "session_id": session_id,
            "active_workspace_id": workspace_id,
            "workspace_id": workspace_id,
            "client_id": client_id,
            "role": "assistant",
            "content": content,
            "status": "completed",
            "channel": "notice",
            "created_at": _utcnow_iso(),
            "metadata": {
                "source": "send_endpoint_message",
                "delivery_kind": "notice",
                "target_type": "client",
                "target_id": target_id,
            },
        }

    async def _deliver_notice_to_client_snapshots(
        self,
        gateway,
        *,
        client_id: str,
        snapshots: list[dict[str, Any]],
        content: str,
    ) -> dict[str, Any]:
        delivered_count = 0
        message_ids: list[str] = []
        seen_routes: set[tuple[str, str, str]] = set()
        for item in snapshots:
            thread_id = str(item.get("thread_id") or "").strip()
            payload_session_id = str(item.get("session_id") or "").strip()
            payload_workspace_id = str(item.get("workspace_id") or "").strip()
            route_key = (thread_id, payload_session_id, payload_workspace_id)
            if route_key in seen_routes:
                continue
            seen_routes.add(route_key)
            message = self._build_notice_message(
                client_id=client_id,
                thread_id=thread_id,
                session_id=payload_session_id,
                workspace_id=payload_workspace_id,
                content=content,
                target_id=client_id,
            )
            route_count = await gateway.client_ws_manager.publish_client_event(
                client_id,
                event_type="message.created",
                payload={
                    "thread_id": thread_id,
                    "session_id": payload_session_id,
                    "message": message,
                },
                thread_id=thread_id,
                session_id=payload_session_id,
                workspace_id=payload_workspace_id,
            )
            if route_count > 0:
                delivered_count += route_count
                message_ids.append(message["message_id"])
        return {"connection_count": delivered_count, "message_ids": message_ids}

    async def _send_notice(self, *, target_type: str, target_id: str, content: str, session_id: str = "", workspace_id: str = "") -> dict[str, Any]:
        gateway = self._gateway()
        target = str(target_type or "client").strip().lower()
        normalized_target_id = str(target_id or "").strip()
        text = str(content or "").strip()
        if target != "client":
            raise _tool_error("unsupported_target_type", f"Unsupported target_type: {target_type}")
        if not normalized_target_id:
            raise _tool_error("target_client_id_required", "target_id is required for client delivery.")
        if not text:
            raise _tool_error("content_required", "content is required for notice delivery.")

        snapshot = await gateway.client_ws_manager.snapshot(client_id=normalized_target_id)
        snapshot = self._filter_client_notice_snapshot(
            snapshot,
            session_id=session_id,
            workspace_id=workspace_id,
        )
        if not snapshot:
            raise _tool_error("client_offline", f"Client is offline: {normalized_target_id}", retryable=True)

        protocol_delivered = await gateway.client_ws_manager.send_to_client(
            normalized_target_id,
            build_client_message(
                client_id=normalized_target_id,
                session_id=session_id,
                content=text,
                role="assistant",
                event_type="notice",
                metadata={
                    "source": "send_endpoint_message",
                    "delivery_kind": "notice",
                    "target_type": "client",
                    "target_id": normalized_target_id,
                },
            ),
            session_id=session_id,
            workspace_id=workspace_id,
        )
        delivery = await self._deliver_notice_to_client_snapshots(
            gateway,
            client_id=normalized_target_id,
            snapshots=snapshot,
            content=text,
        )
        delivered_count = int(delivery["connection_count"]) + int(protocol_delivered)
        if delivered_count <= 0:
            raise _tool_error("client_delivery_failed", f"Client delivery failed: {normalized_target_id}", retryable=True)
        message_ids = list(delivery["message_ids"])
        return {
            "ok": True,
            "delivered": True,
            "target_type": "client",
            "target_id": normalized_target_id,
            "connection_count": delivered_count,
            "message_id": message_ids[0] if message_ids else "",
            "message_ids": message_ids,
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
        dispatcher = getattr(domain, "client_tool_dispatch", None)
        if dispatcher is None:
            raise _tool_error("client_tool_dispatch_unavailable", "Client tool dispatcher is unavailable.", retryable=True)
        target = str(target_type or "client").strip().lower()
        normalized_target_id = str(target_id or "").strip()
        normalized_tool_key = str(tool_key or "").strip()
        normalized_session_id = str(session_id or get_event_context().get("session_id") or "").strip()
        normalized_workspace_id = str(workspace_id or get_event_context().get("workspace_id") or "").strip()
        source_client_id = str(get_event_context().get("client_id") or "").strip()
        if target != "client":
            raise _tool_error("unsupported_target_type", f"Unsupported target_type: {target_type}")
        if not normalized_target_id:
            raise _tool_error("target_client_id_required", "target_id is required for client tool calls.")
        if not normalized_tool_key:
            raise _tool_error("tool_key_required", "tool_key is required for tool_call delivery.")

        try:
            result = await dispatcher.dispatch_directed_tool(
                tool_key=normalized_tool_key,
                arguments=dict(arguments or {}),
                source_client_id=source_client_id,
                target_client_id=normalized_target_id,
                session_id=normalized_session_id,
                workspace_id=normalized_workspace_id,
                title=f"Endpoint tool call: {normalized_tool_key}",
                operation_type="tool.send_endpoint_message",
                timeout_seconds=int(timeout_seconds or 120),
                confirmed=bool(confirmed),
            )
        except ClientToolDispatchError:
            raise
        return {
            "ok": True,
            "target_type": "client",
            "target_id": normalized_target_id,
            "target_client_id": normalized_target_id,
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
