from __future__ import annotations

from typing import Any

from core.runtime_context import get_event_context


class ThreadTools:
    def __init__(self) -> None:
        self._core_domain = None
        self._gateway_getter = None

    def set_core_domain(self, core_domain) -> None:
        self._core_domain = core_domain

    def set_runtime(self, *, session_manager=None, gateway_getter=None) -> None:
        del session_manager
        self._gateway_getter = gateway_getter

    def _workspace_by_public_id(self, workspace_id: str = ""):
        domain = self._core_domain
        if domain is None:
            return None
        normalized = str(workspace_id or "").strip()
        if normalized:
            return domain.services.workspace.get_by_workspace_id(normalized)
        rows = domain.services.workspace.list_workspaces()
        return next((item for item in rows if getattr(item, "workspace_id", "") == "personal"), rows[0] if rows else None)

    def _thread_payload(self, thread, workspace_id: str = "") -> dict[str, Any]:
        metadata = dict(getattr(thread, "meta", {}) or {})
        return {
            "thread_id": str(getattr(thread, "thread_id", "") or ""),
            "workspace_id": str(workspace_id or ""),
            "title": str(getattr(thread, "title", "") or ""),
            "status": str(getattr(thread, "status", "") or "active"),
            "summary": str(getattr(thread, "summary", "") or ""),
            "default_key": str(metadata.get("default_key") or ""),
            "default_thread": bool(metadata.get("default_key")),
        }

    def _list_threads(self, *, workspace_id: str = "", limit: int = 50) -> tuple[list[dict[str, Any]], str]:
        domain = self._core_domain
        if domain is None:
            return [], ""
        workspace = self._workspace_by_public_id(workspace_id)
        workspace_row_id = getattr(workspace, "id", None)
        public_workspace_id = str(getattr(workspace, "workspace_id", "") or "")
        rows = domain.services.thread.list_threads(
            principal_id=domain.principal.id,
            workspace_id=workspace_row_id,
            limit=limit,
        )
        return [self._thread_payload(row, public_workspace_id) for row in rows], public_workspace_id

    async def _publish_thread_event(self, current_thread_id: str, *, event_type: str, payload: dict[str, Any]) -> int:
        gateway = self._gateway_getter() if callable(self._gateway_getter) else None
        publisher = getattr(gateway, "publish_thread_delivery_event", None) if gateway is not None else None
        if not callable(publisher) or not current_thread_id:
            return 0
        return int(await publisher(current_thread_id, event_type=event_type, payload=payload))

    def _context_ids(self, *, session_id: str = "", workspace_id: str = "") -> dict[str, Any]:
        domain = self._core_domain
        event_context = get_event_context()
        resolved_session_id = str(session_id or event_context.get("session_id") or "").strip()
        active_workspace_id = str(workspace_id or event_context.get("workspace_id") or event_context.get("active_workspace_id") or "").strip()
        current_thread_id = str(event_context.get("thread_id") or "").strip()
        session_row = domain.services.session.get_by_session_id(resolved_session_id) if domain is not None and resolved_session_id else None
        if session_row is not None and not current_thread_id:
            current_thread = domain.services.thread.get_by_id(getattr(session_row, "thread_id", None))
            current_thread_id = str(getattr(current_thread, "thread_id", "") or "")
        if session_row is not None and not active_workspace_id:
            workspace_row = domain.services.workspace.get_by_id(getattr(session_row, "active_workspace_id", None))
            active_workspace_id = str(getattr(workspace_row, "workspace_id", "") or "")
        return {
            "session_id": resolved_session_id,
            "workspace_id": active_workspace_id,
            "current_thread_id": current_thread_id,
        }

    async def manage_threads(
        self,
        action: str = "list",
        thread_id: str = "",
        title: str = "",
        workspace_id: str = "",
        limit: int = 50,
        switch_after_create: bool = False,
        force: bool = False,
        reason: str = "",
        session_id: str = "",
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        domain = self._core_domain
        if domain is None:
            return {"ok": False, "code": "core_domain_unavailable", "message": "Core domain is not available."}

        normalized_action = str(action or "list").strip().lower()
        context = self._context_ids(session_id=session_id, workspace_id=workspace_id)
        resolved_session_id = str(context["session_id"])
        active_workspace_id = str(context["workspace_id"])
        current_thread_id = str(context["current_thread_id"])
        safe_limit = max(1, min(int(limit or 50), 200))

        if normalized_action == "list":
            threads, public_workspace_id = self._list_threads(workspace_id=active_workspace_id, limit=safe_limit)
            for item in threads:
                item["active"] = bool(item["thread_id"] and item["thread_id"] == current_thread_id)
            return {
                "ok": True,
                "action": "list",
                "session_id": resolved_session_id,
                "active_thread_id": current_thread_id,
                "workspace_id": public_workspace_id or active_workspace_id,
                "threads": threads,
            }

        if normalized_action == "create":
            workspace = self._workspace_by_public_id(active_workspace_id)
            if workspace is None:
                return {"ok": False, "code": "workspace_not_found", "message": "Workspace is required."}
            thread = domain.services.thread.create_thread(
                principal_id=domain.principal.id,
                workspace_id=workspace.id,
                title=str(title or "").strip() or "新会话",
            )
            payload = self._thread_payload(thread, str(getattr(workspace, "workspace_id", "") or ""))
            delivered = 0
            if switch_after_create:
                delivered = await self._publish_thread_event(
                    current_thread_id,
                    event_type="thread.switched",
                    payload={
                        "thread_id": current_thread_id,
                        "session_id": resolved_session_id,
                        "target_thread_id": payload["thread_id"],
                        "workspace_id": payload["workspace_id"],
                        "reason": str(reason or "create_thread").strip(),
                        "source": "manage_threads",
                    },
                )
            return {"ok": True, "action": "create", "thread": payload, "switch_event_delivered": delivered}

        target_thread_id = str(thread_id or "").strip()
        if not target_thread_id:
            return {"ok": False, "code": "thread_id_required", "message": "thread_id is required."}
        target_thread = domain.services.thread.get_by_thread_id(target_thread_id)
        if target_thread is None:
            return {"ok": False, "code": "thread_not_found", "message": f"Unknown thread: {target_thread_id}"}

        if normalized_action == "switch":
            workspace = domain.services.workspace.get_by_id(getattr(target_thread, "home_workspace_id", None) or getattr(target_thread, "workspace_id", None))
            target_payload = self._thread_payload(target_thread, str(getattr(workspace, "workspace_id", "") or ""))
            delivered = await self._publish_thread_event(
                current_thread_id or target_thread_id,
                event_type="thread.switched",
                payload={
                    "thread_id": current_thread_id,
                    "session_id": resolved_session_id,
                    "target_thread_id": target_thread_id,
                    "workspace_id": target_payload["workspace_id"],
                    "reason": str(reason or "").strip(),
                    "source": "manage_threads",
                },
            )
            return {
                "ok": True,
                "action": "switch",
                "thread": target_payload,
                "session_id": resolved_session_id,
                "event_delivered": delivered,
            }

        if normalized_action == "delete":
            workspace = domain.services.workspace.get_by_id(getattr(target_thread, "home_workspace_id", None) or getattr(target_thread, "workspace_id", None))
            public_workspace_id = str(getattr(workspace, "workspace_id", "") or active_workspace_id)
            result = domain.services.thread.delete_thread(
                principal_id=domain.principal.id,
                thread_id=target_thread_id,
                force=bool(force),
            )
            threads, _ = self._list_threads(workspace_id=public_workspace_id, limit=safe_limit)
            fallback_thread_id = next((item["thread_id"] for item in threads if item.get("default_thread")), "")
            if not fallback_thread_id and threads:
                fallback_thread_id = threads[0]["thread_id"]
            delivered = 0
            if result.deleted:
                delivered = await self._publish_thread_event(
                    current_thread_id or target_thread_id,
                    event_type="thread.deleted",
                    payload={
                        "thread_id": current_thread_id,
                        "session_id": resolved_session_id,
                        "deleted_thread_id": target_thread_id,
                        "fallback_thread_id": fallback_thread_id,
                        "workspace_id": public_workspace_id,
                        "reason": str(reason or "").strip(),
                        "source": "manage_threads",
                    },
                )
            return {
                "ok": result.deleted,
                "action": "delete",
                "thread_id": target_thread_id,
                "deleted": result.deleted,
                "reason": result.reason,
                "default_thread": result.default_thread,
                "fallback_thread_id": fallback_thread_id,
                "event_delivered": delivered,
            }

        return {"ok": False, "code": "unsupported_action", "message": "action must be list, create, switch, or delete."}
