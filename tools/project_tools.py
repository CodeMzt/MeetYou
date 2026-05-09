from __future__ import annotations

from typing import Any


def _row_iso(row, attr: str) -> str:
    value = getattr(row, attr, None)
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else ""


class ProjectTools:
    def __init__(self) -> None:
        self._core_domain = None

    def set_core_domain(self, core_domain) -> None:
        self._core_domain = core_domain

    def _domain_or_error(self):
        if self._core_domain is None:
            return None, {"ok": False, "code": "core_domain_unavailable", "message": "Core domain is not available."}
        return self._core_domain, None

    @staticmethod
    def _project_payload(project, *, workspace_id: str = "") -> dict[str, Any]:
        return {
            "project_id": str(getattr(project, "project_id", "") or ""),
            "workspace_id": workspace_id,
            "title": str(getattr(project, "title", "") or ""),
            "description": str(getattr(project, "description", "") or ""),
            "instructions": str(getattr(project, "instructions", "") or ""),
            "status": str(getattr(project, "status", "") or "active"),
            "memory_scope": dict(getattr(project, "memory_scope", {}) or {}),
            "metadata": dict(getattr(project, "meta", {}) or {}),
            "created_at": _row_iso(project, "created_at"),
            "updated_at": _row_iso(project, "updated_at"),
        }

    @staticmethod
    def _source_payload(source, *, project_id: str = "") -> dict[str, Any]:
        return {
            "source_id": str(getattr(source, "source_id", "") or ""),
            "project_id": project_id,
            "source_type": str(getattr(source, "source_type", "") or "note"),
            "title": str(getattr(source, "title", "") or ""),
            "content": str(getattr(source, "content", "") or ""),
            "content_type": str(getattr(source, "content_type", "") or "text"),
            "checksum": str(getattr(source, "checksum", "") or ""),
            "status": str(getattr(source, "status", "") or "active"),
            "metadata": dict(getattr(source, "meta", {}) or {}),
            "created_at": _row_iso(source, "created_at"),
            "updated_at": _row_iso(source, "updated_at"),
        }

    @staticmethod
    def _thread_payload(thread, *, project_id: str = "") -> dict[str, Any]:
        return {
            "thread_id": str(getattr(thread, "thread_id", "") or ""),
            "project_id": project_id,
            "title": str(getattr(thread, "title", "") or ""),
            "status": str(getattr(thread, "status", "") or "active"),
            "summary": str(getattr(thread, "summary", "") or ""),
            "created_at": _row_iso(thread, "created_at"),
            "updated_at": _row_iso(thread, "updated_at"),
        }

    async def manage_projects(
        self,
        action: str = "list",
        project_id: str = "",
        workspace_id: str = "",
        title: str = "",
        description: str = "",
        instructions: str = "",
        memory_scope: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        thread_id: str = "",
        limit: int = 50,
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        domain, error = self._domain_or_error()
        if error is not None:
            return error
        normalized_action = str(action or "list").strip().lower()
        workspace = domain.services.workspace.get_by_workspace_id(workspace_id) if str(workspace_id or "").strip() else None
        if workspace_id and workspace is None:
            return {"ok": False, "code": "workspace_not_found", "message": f"Unknown workspace: {workspace_id}"}

        if normalized_action == "list":
            rows = domain.services.project.list_projects(
                principal_id=domain.principal.id,
                workspace_id=getattr(workspace, "id", None),
                limit=limit,
            )
            return {
                "ok": True,
                "projects": [
                    self._project_payload(
                        row,
                        workspace_id=str(getattr(domain.services.workspace.get_by_id(getattr(row, "workspace_id", None)), "workspace_id", "") or ""),
                    )
                    for row in rows
                ],
            }

        if normalized_action == "create":
            try:
                project = domain.services.project.create_project(
                    principal_id=domain.principal.id,
                    workspace_id=getattr(workspace, "id", None),
                    title=title,
                    description=description,
                    instructions=instructions,
                    memory_scope=memory_scope,
                    metadata=metadata,
                )
            except ValueError as exc:
                return {"ok": False, "code": "project_invalid", "message": str(exc)}
            return {"ok": True, "project": self._project_payload(project, workspace_id=str(getattr(workspace, "workspace_id", "") or ""))}

        project = domain.services.project.get_by_project_id(project_id) if str(project_id or "").strip() else None
        if project is None and normalized_action not in {"detach_thread"}:
            return {"ok": False, "code": "project_not_found", "message": f"Unknown project: {project_id}"}

        if normalized_action == "get":
            project_workspace = domain.services.workspace.get_by_id(getattr(project, "workspace_id", None)) if getattr(project, "workspace_id", None) else None
            return {"ok": True, "project": self._project_payload(project, workspace_id=str(getattr(project_workspace, "workspace_id", "") or ""))}

        if normalized_action == "update":
            fields: dict[str, Any] = {}
            if title:
                fields["title"] = title
            if description:
                fields["description"] = description
            if instructions:
                fields["instructions"] = instructions
            if memory_scope is not None:
                fields["memory_scope"] = memory_scope
            if metadata is not None:
                fields["metadata"] = metadata
            project = domain.services.project.update_project(project_id=project_id, fields=fields)
            return {"ok": True, "project": self._project_payload(project, workspace_id=workspace_id)}

        if normalized_action == "archive":
            project = domain.services.project.archive_project(project_id=project_id)
            return {"ok": True, "project": self._project_payload(project, workspace_id=workspace_id)}

        if normalized_action == "list_threads":
            rows = domain.services.thread.list_threads(
                principal_id=domain.principal.id,
                project_id=getattr(project, "id", None),
                limit=limit,
            )
            return {"ok": True, "threads": [self._thread_payload(row, project_id=project_id) for row in rows]}

        if normalized_action in {"attach_thread", "detach_thread"}:
            thread = domain.services.thread.get_by_thread_id(thread_id)
            if thread is None:
                return {"ok": False, "code": "thread_not_found", "message": f"Unknown thread: {thread_id}"}
            target_project_id = getattr(project, "id", None) if normalized_action == "attach_thread" else None
            public_project_id = project_id if normalized_action == "attach_thread" else ""
            updated = domain.services.thread.update_thread(
                thread_row_id=thread.id,
                fields={"project_id": target_project_id},
            )
            return {"ok": True, "thread": self._thread_payload(updated, project_id=public_project_id)}

        return {"ok": False, "code": "project_action_invalid", "message": f"Unsupported project action: {normalized_action}"}

    async def manage_project_sources(
        self,
        action: str = "list",
        project_id: str = "",
        source_id: str = "",
        source_type: str = "note",
        title: str = "",
        content: str = "",
        content_type: str = "text",
        message_id: str = "",
        metadata: dict[str, Any] | None = None,
        include_archived: bool = False,
        limit: int = 50,
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        domain, error = self._domain_or_error()
        if error is not None:
            return error
        normalized_action = str(action or "list").strip().lower()
        project = domain.services.project.get_by_project_id(project_id) if str(project_id or "").strip() else None
        if project is None:
            return {"ok": False, "code": "project_not_found", "message": f"Unknown project: {project_id}"}

        if normalized_action == "list":
            rows = domain.services.project.list_sources(
                project_id=project_id,
                include_archived=include_archived,
                limit=limit,
            )
            return {"ok": True, "sources": [self._source_payload(row, project_id=project_id) for row in rows or []]}

        if normalized_action == "get":
            source = domain.services.project.get_source(project_id=project_id, source_id=source_id)
            if source is None:
                return {"ok": False, "code": "project_source_not_found", "message": f"Unknown project source: {source_id}"}
            return {"ok": True, "source": self._source_payload(source, project_id=project_id)}

        if normalized_action == "create":
            try:
                source = domain.services.project.add_source(
                    project_id=project_id,
                    principal_id=domain.principal.id,
                    source_type=source_type,
                    title=title,
                    content=content,
                    content_type=content_type,
                    metadata=metadata,
                )
            except ValueError as exc:
                return {"ok": False, "code": "project_source_invalid", "message": str(exc)}
            return {"ok": True, "source": self._source_payload(source, project_id=project_id)}

        if normalized_action == "save_message":
            source = domain.services.project.save_message_source(
                project_id=project_id,
                principal_id=domain.principal.id,
                message_id=message_id,
                title=title,
                metadata=metadata,
            )
            if source is None:
                return {"ok": False, "code": "project_or_message_not_found", "message": "Unknown project or message."}
            return {"ok": True, "source": self._source_payload(source, project_id=project_id)}

        return {"ok": False, "code": "project_source_action_invalid", "message": f"Unsupported project source action: {normalized_action}"}
