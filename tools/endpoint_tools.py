from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_protocol import build_agent_message
from core.runtime_context import get_event_context
from core.services.agent_dispatch_service import AgentDispatchError


_ONLINE_AGENT_STATUSES = {"online", "ready"}
_CLIENT_WS_SCHEMA = "meetyou.client.ws.v1"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tool_error(code: str, message: str, *, details: dict[str, Any] | None = None, retryable: bool = False) -> RuntimeError:
    error = RuntimeError(message)
    error.tool_error_code = code
    error.tool_error_message = message
    error.tool_error_details = dict(details or {})
    error.tool_error_retryable = retryable
    return error


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
    def _agent_payload(agent, *, connected_at: str = "", workspace_ids: list[str] | None = None) -> dict[str, Any]:
        return {
            "agent_id": getattr(agent, "agent_id", ""),
            "display_name": getattr(agent, "display_name", ""),
            "agent_type": getattr(agent, "agent_type", ""),
            "transport_profile": getattr(agent, "transport_profile", ""),
            "status": getattr(agent, "status", ""),
            "connected": True,
            "connected_at": connected_at,
            "last_seen_at": getattr(agent, "last_seen_at", "").isoformat()
            if getattr(agent, "last_seen_at", None) is not None
            else "",
            "workspace_ids": list(workspace_ids or []),
            "owner_client_row_id": str(getattr(agent, "owner_client_id", "") or ""),
            "host": {
                "name": getattr(agent, "host_name", ""),
                "os": getattr(agent, "host_os", ""),
                "arch": getattr(agent, "host_arch", ""),
            },
        }

    async def list_active_agents(
        self,
        workspace_id: str = "",
        include_capabilities: bool = False,
        session_id: str = "",
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        domain = self._domain()
        gateway = self._gateway()
        workspace = self._workspace_row(workspace_id, session_id=session_id)
        connected_snapshot = {item["agent_id"]: item for item in await gateway.agent_ws_manager.snapshot()}
        agents: list[dict[str, Any]] = []
        for agent in domain.services.agent.list_agents():
            agent_id = str(getattr(agent, "agent_id", "") or "").strip()
            if not agent_id or agent_id not in connected_snapshot:
                continue
            if str(getattr(agent, "status", "") or "").strip().lower() not in _ONLINE_AGENT_STATUSES:
                continue
            workspaces = domain.services.agent.list_workspaces(agent_id)
            public_workspace_ids = [str(getattr(item, "workspace_id", "") or "") for item in workspaces]
            if workspace is not None and getattr(workspace, "workspace_id", "") not in public_workspace_ids:
                continue
            payload = self._agent_payload(
                agent,
                connected_at=str(connected_snapshot[agent_id].get("connected_at") or ""),
                workspace_ids=public_workspace_ids,
            )
            if include_capabilities:
                capability_rows = []
                for workspace_row in workspaces:
                    for capability in domain.services.capability.list_for_workspace(workspace_id=workspace_row.id):
                        if str(getattr(capability, "provider_ref", "") or "") != agent_id:
                            continue
                        capability_rows.append(
                            {
                                "capability_id": getattr(capability, "capability_id", ""),
                                "title": getattr(capability, "title", ""),
                                "kind": getattr(capability, "kind", ""),
                                "risk_level": getattr(capability, "risk_level", ""),
                                "requires_confirmation": bool(getattr(capability, "requires_confirmation", False)),
                                "workspace_id": getattr(workspace_row, "workspace_id", ""),
                            }
                        )
                seen: set[str] = set()
                payload["capabilities"] = [
                    item
                    for item in capability_rows
                    if not (item["capability_id"] in seen or seen.add(item["capability_id"]))
                ]
            agents.append(payload)
        return {"ok": True, "count": len(agents), "agents": agents}

    async def list_active_clients(
        self,
        workspace_id: str = "",
        thread_id: str = "",
        include_owned_agents: bool = False,
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
        connected_agent_ids = await gateway.agent_ws_manager.connected_agent_ids()
        clients: list[dict[str, Any]] = []
        for item in snapshot:
            client_id = str(item.get("client_id") or "").strip()
            client_row = domain.services.client.get_by_client_id(client_id) if client_id else None
            payload = {
                "client_id": client_id,
                "display_name": str(item.get("display_name") or getattr(client_row, "display_name", "") or ""),
                "client_type": str(item.get("client_type") or getattr(client_row, "client_type", "") or ""),
                "status": "online",
                "thread_id": str(item.get("thread_id") or ""),
                "session_id": str(item.get("session_id") or ""),
                "workspace_id": str(item.get("workspace_id") or ""),
                "connected_at": str(item.get("connected_at") or ""),
                "updated_at": str(item.get("updated_at") or ""),
            }
            if include_owned_agents and client_row is not None:
                owned_agents = []
                for agent in domain.services.agent.list_agents():
                    if getattr(agent, "owner_client_id", None) != getattr(client_row, "id", None):
                        continue
                    agent_id = str(getattr(agent, "agent_id", "") or "")
                    if agent_id not in connected_agent_ids:
                        continue
                    if str(getattr(agent, "status", "") or "").strip().lower() not in _ONLINE_AGENT_STATUSES:
                        continue
                    owned_agents.append(self._agent_payload(agent))
                payload["owned_agents"] = owned_agents
            clients.append(payload)
        return {"ok": True, "count": len(clients), "clients": clients}

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
        target_type: str,
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
                "target_type": target_type,
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
        target_type: str,
        target_id: str,
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
                target_type=target_type,
                target_id=target_id,
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
        target = str(target_type or "").strip().lower()
        normalized_target_id = str(target_id or "").strip()
        text = str(content or "").strip()
        if not text:
            raise _tool_error("content_required", "content is required for notice delivery.")
        if target == "agent":
            domain = self._domain()
            payload = build_agent_message(
                agent_id=normalized_target_id,
                session_id=session_id,
                content=text,
                role="assistant",
                event_type="notice",
                metadata={
                    "source": "send_endpoint_message",
                    "delivery_kind": "notice",
                    "target_type": "agent",
                    "target_id": normalized_target_id,
                },
            )
            delivered = await gateway.agent_ws_manager.send_to_agent(normalized_target_id, payload)
            if not delivered:
                raise _tool_error("agent_offline", f"Agent is offline: {normalized_target_id}", retryable=True)
            owner_client_id = ""
            owner_connection_count = 0
            owner_message_ids: list[str] = []
            agent_row = domain.services.agent.get_by_agent_id(normalized_target_id)
            owner_client_row_id = getattr(agent_row, "owner_client_id", None) if agent_row is not None else None
            if owner_client_row_id is not None:
                owner_client = domain.services.client.get_by_id(owner_client_row_id)
                owner_client_id = str(getattr(owner_client, "client_id", "") or "").strip()
                if owner_client_id:
                    owner_snapshot = await gateway.client_ws_manager.snapshot(client_id=owner_client_id)
                    owner_snapshot = self._filter_client_notice_snapshot(
                        owner_snapshot,
                        session_id=session_id,
                        workspace_id=workspace_id,
                    )
                    owner_delivery = await self._deliver_notice_to_client_snapshots(
                        gateway,
                        client_id=owner_client_id,
                        snapshots=owner_snapshot,
                        content=text,
                        target_type="agent",
                        target_id=normalized_target_id,
                    )
                    owner_connection_count = int(owner_delivery["connection_count"])
                    owner_message_ids = list(owner_delivery["message_ids"])
            return {
                "ok": True,
                "delivered": True,
                "target_type": "agent",
                "target_id": normalized_target_id,
                "agent_delivered": True,
                "owner_client_id": owner_client_id,
                "owner_client_connection_count": owner_connection_count,
                "owner_client_message_ids": owner_message_ids,
            }
        if target == "client":
            snapshot = await gateway.client_ws_manager.snapshot(client_id=normalized_target_id)
            snapshot = self._filter_client_notice_snapshot(
                snapshot,
                session_id=session_id,
                workspace_id=workspace_id,
            )
            if not snapshot:
                raise _tool_error("client_offline", f"Client is offline: {normalized_target_id}", retryable=True)
            delivery = await self._deliver_notice_to_client_snapshots(
                gateway,
                client_id=normalized_target_id,
                snapshots=snapshot,
                content=text,
                target_type="client",
                target_id=normalized_target_id,
            )
            delivered_count = int(delivery["connection_count"])
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
        raise _tool_error("unsupported_target_type", f"Unsupported target_type: {target_type}")

    async def _resolve_client_owned_agent(self, *, client_id: str, workspace_id: str = "", capability_ref: str = ""):
        domain = self._domain()
        gateway = self._gateway()
        client = domain.services.client.get_by_client_id(client_id)
        if client is None:
            raise _tool_error("client_not_found", f"Unknown client: {client_id}")
        connected_agent_ids = await gateway.agent_ws_manager.connected_agent_ids()
        for agent in domain.services.agent.list_agents():
            agent_id = str(getattr(agent, "agent_id", "") or "").strip()
            if getattr(agent, "owner_client_id", None) != getattr(client, "id", None):
                continue
            if agent_id not in connected_agent_ids:
                continue
            if str(getattr(agent, "status", "") or "").strip().lower() not in _ONLINE_AGENT_STATUSES:
                continue
            if workspace_id and not domain.services.agent.is_bound_to_workspace(agent_id=agent_id, workspace_id=workspace_id):
                continue
            if capability_ref:
                candidate = domain.agent_dispatch.resolve_specific_capability(
                    agent_id=agent_id,
                    capability_ref=capability_ref,
                    workspace_id=workspace_id,
                )
                if candidate is None:
                    continue
            return agent
        raise _tool_error(
            "client_agent_unavailable",
            f"No online owned agent can satisfy the request for client: {client_id}",
            retryable=True,
        )

    async def _send_capability_call(
        self,
        *,
        target_type: str,
        target_id: str,
        capability_ref: str,
        arguments: dict[str, Any] | None,
        workspace_id: str = "",
        session_id: str = "",
        timeout_seconds: int = 120,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        domain = self._domain()
        target = str(target_type or "").strip().lower()
        normalized_target_id = str(target_id or "").strip()
        normalized_workspace_id = str(workspace_id or "").strip()
        normalized_session_id = str(session_id or get_event_context().get("session_id") or "").strip()
        if not capability_ref:
            raise _tool_error("capability_ref_required", "capability_ref is required for capability_call delivery.")
        agent_id = normalized_target_id
        if target == "client":
            snapshot = await self._gateway().client_ws_manager.snapshot(client_id=normalized_target_id)
            if not normalized_session_id and snapshot:
                normalized_session_id = str(snapshot[0].get("session_id") or "")
            if not normalized_workspace_id and snapshot:
                normalized_workspace_id = str(snapshot[0].get("workspace_id") or "")
            agent = await self._resolve_client_owned_agent(
                client_id=normalized_target_id,
                workspace_id=normalized_workspace_id,
                capability_ref=capability_ref,
            )
            agent_id = str(getattr(agent, "agent_id", "") or "")
        elif target != "agent":
            raise _tool_error("unsupported_target_type", f"Unsupported target_type: {target_type}")

        try:
            result = await domain.agent_dispatch.dispatch_specific_agent_capability(
                agent_id=agent_id,
                capability_ref=capability_ref,
                arguments=dict(arguments or {}),
                session_id=normalized_session_id,
                workspace_id=normalized_workspace_id,
                title=f"Endpoint capability call: {capability_ref}",
                operation_type="tool.send_endpoint_message",
                timeout_seconds=int(timeout_seconds or 120),
                confirmed=bool(confirmed),
            )
        except AgentDispatchError:
            raise
        return {
            "ok": True,
            "target_type": target,
            "target_id": normalized_target_id,
            "agent_id": agent_id,
            "capability_ref": capability_ref,
            "result": result,
        }

    async def send_endpoint_message(
        self,
        target_type: str,
        target_id: str,
        delivery_kind: str = "notice",
        content: str = "",
        capability_ref: str = "",
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
        if kind == "capability_call":
            return await self._send_capability_call(
                target_type=target_type,
                target_id=target_id,
                capability_ref=capability_ref,
                arguments=arguments,
                workspace_id=workspace_id,
                session_id=session_id,
                timeout_seconds=timeout_seconds,
                confirmed=confirmed,
            )
        raise _tool_error("unsupported_delivery_kind", f"Unsupported delivery_kind: {delivery_kind}")
