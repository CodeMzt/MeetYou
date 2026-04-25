from __future__ import annotations

from typing import Any

from core.runtime_context import bind_event_context, get_event_context


class WorkspaceTools:
    def __init__(self) -> None:
        self._core_domain = None
        self._session_manager = None
        self._gateway_getter = None

    def set_core_domain(self, core_domain) -> None:
        self._core_domain = core_domain

    def set_runtime(self, *, session_manager=None, gateway_getter=None) -> None:
        self._session_manager = session_manager
        self._gateway_getter = gateway_getter

    async def list_workspaces(
        self,
        include_agents: bool = False,
        include_clients: bool = False,
        session_id: str = "",
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        domain = self._core_domain
        if domain is None:
            return {"ok": False, "code": "core_domain_unavailable", "message": "Core domain is not available."}

        event_context = get_event_context()
        resolved_session_id = str(session_id or event_context.get("session_id") or "").strip()
        active_workspace_id = str(event_context.get("active_workspace_id") or event_context.get("workspace_id") or "").strip()
        if resolved_session_id:
            session_row = domain.services.session.get_by_session_id(resolved_session_id)
            if session_row is not None and not active_workspace_id:
                workspace_row = domain.services.workspace.get_by_id(getattr(session_row, "active_workspace_id", None))
                active_workspace_id = str(getattr(workspace_row, "workspace_id", "") or "")

        workspace_service = domain.services.workspace
        governance_getter = getattr(workspace_service, "get_governance_view", None)
        workspace_rows = workspace_service.list_workspaces()
        items: list[dict[str, Any]] = []
        for workspace in workspace_rows:
            governance = governance_getter(workspace) if callable(governance_getter) else {}
            workspace_id = str(getattr(workspace, "workspace_id", "") or "")
            item = {
                "workspace_id": workspace_id,
                "title": str(getattr(workspace, "title", "") or ""),
                "status": str(getattr(workspace, "status", "") or "active"),
                "base_mode": str(getattr(workspace, "base_mode", "") or "general"),
                "description": str(governance.get("description") or getattr(workspace, "description", "") or ""),
                "default_execution_target": str(governance.get("default_execution_target") or getattr(workspace, "default_execution_target", "") or ""),
                "memory_ranking_policy": str(governance.get("memory_ranking_policy") or "workspace_first"),
                "active": bool(active_workspace_id and workspace_id == active_workspace_id),
            }
            if include_agents:
                agents = []
                agent_service = getattr(domain.services, "agent", None)
                lister = getattr(agent_service, "list_agents_for_workspace", None)
                if callable(lister):
                    for agent in lister(getattr(workspace, "id", None)):
                        agents.append(
                            {
                                "agent_id": str(getattr(agent, "agent_id", "") or ""),
                                "agent_type": str(getattr(agent, "agent_type", "") or ""),
                                "display_name": str(getattr(agent, "display_name", "") or ""),
                                "status": str(getattr(agent, "status", "") or ""),
                            }
                        )
                item["agents"] = agents
            if include_clients:
                clients = []
                client_service = getattr(domain.services, "client", None)
                lister = getattr(client_service, "list_clients_for_workspace", None)
                if callable(lister):
                    for row in lister(getattr(workspace, "id", None)):
                        client = row[0] if isinstance(row, tuple) else row
                        clients.append(
                            {
                                "client_id": str(getattr(client, "client_id", "") or ""),
                                "client_type": str(getattr(client, "client_type", "") or ""),
                                "display_name": str(getattr(client, "display_name", "") or ""),
                            }
                        )
                item["clients"] = clients
            items.append(item)

        return {
            "ok": True,
            "active_workspace_id": active_workspace_id,
            "session_id": resolved_session_id,
            "workspaces": items,
        }

    async def switch_workspace(
        self,
        workspace_id: str,
        reason: str = "",
        session_id: str = "",
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        domain = self._core_domain
        if domain is None:
            return {"ok": False, "code": "core_domain_unavailable", "message": "Core domain is not available."}
        target_workspace_id = str(workspace_id or "").strip()
        if not target_workspace_id:
            return {"ok": False, "code": "workspace_id_required", "message": "workspace_id is required."}
        workspace = domain.services.workspace.get_by_workspace_id(target_workspace_id)
        if workspace is None:
            return {"ok": False, "code": "workspace_not_found", "message": f"Unknown workspace: {target_workspace_id}"}

        event_context = get_event_context()
        resolved_session_id = str(session_id or event_context.get("session_id") or "").strip()
        if not resolved_session_id:
            return {"ok": False, "code": "session_id_required", "message": "session_id is required."}
        session_row = domain.services.session.get_by_session_id(resolved_session_id)
        if session_row is None:
            return {"ok": False, "code": "session_not_found", "message": f"Unknown session: {resolved_session_id}"}
        thread_row = domain.services.thread.get_by_id(session_row.thread_id)
        client_row = domain.services.client.get_by_id(session_row.client_id)
        if client_row is not None:
            domain.services.client.bind_workspace(
                workspace_id=workspace.id,
                client_id=client_row.id,
                membership_role="active",
                enabled=True,
                metadata={"source": "switch_workspace_tool", "reason": str(reason or "").strip()},
            )
        updated = domain.services.session.set_active_workspace(
            session_id=resolved_session_id,
            active_workspace_id=workspace.id,
            metadata={"active_workspace_id": workspace.workspace_id, "switch_reason": str(reason or "").strip()},
        )
        bind_event_context(
            active_workspace_id=workspace.workspace_id,
            workspace_id=workspace.workspace_id,
            workspace_title=workspace.title,
            workspace_base_mode=workspace.base_mode,
        )

        source = event_context.get("source")
        if self._session_manager is not None and source is not None:
            self._session_manager.bind_runtime_session(
                source,
                session_id=resolved_session_id,
                metadata={
                    "thread_id": getattr(thread_row, "thread_id", ""),
                    "active_workspace_id": workspace.workspace_id,
                    "workspace_id": workspace.workspace_id,
                    "workspace_title": workspace.title,
                    "workspace_base_mode": workspace.base_mode,
                    "client_id": getattr(client_row, "client_id", ""),
                    "session_row_id": str(getattr(session_row, "id", "") or ""),
                },
            )

        gateway = self._gateway_getter() if callable(self._gateway_getter) else None
        if gateway is not None and thread_row is not None:
            await gateway.publish_client_thread_event(
                thread_row.thread_id,
                event_type="workspace.changed",
                payload={
                    "thread_id": thread_row.thread_id,
                    "session_id": resolved_session_id,
                    "active_workspace_id": workspace.workspace_id,
                    "workspace_id": workspace.workspace_id,
                    "client_id": getattr(client_row, "client_id", ""),
                    "reason": str(reason or "").strip(),
                    "source": "switch_workspace_tool",
                },
            )
        return {
            "ok": True,
            "session_id": getattr(updated, "session_id", resolved_session_id),
            "active_workspace_id": workspace.workspace_id,
            "workspace_title": workspace.title,
            "reason": str(reason or "").strip(),
        }
