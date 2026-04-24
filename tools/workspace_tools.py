from __future__ import annotations

from typing import Any

from core.runtime_context import get_event_context


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
