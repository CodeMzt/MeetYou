from __future__ import annotations

from typing import Any

from core.runtime_context import get_event_context
from core.research.external_adapter import ResearchAdapterConfig
from core.research.report_artifacts import create_research_report_derivatives
from core.services.research_execution_service import ResearchExecutionService
from core.services.v5_service import ResearchTaskCitationError, ResearchTaskStateError
from tools.academic_sources import AcademicSourceRegistry


class ResearchTools:
    def __init__(self) -> None:
        self._core_domain = None

    def set_core_domain(self, core_domain) -> None:
        self._core_domain = core_domain

    @staticmethod
    def _route_value(route_context: dict[str, Any] | None, *keys: str) -> str:
        context = dict(route_context or {})
        event_context = get_event_context()
        for key in keys:
            value = str(context.get(key) or event_context.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _route_project_id(route_context: dict[str, Any] | None) -> str:
        context = dict(route_context or {})
        event_context = get_event_context()
        project = context.get("project") if isinstance(context.get("project"), dict) else {}
        return str(context.get("project_id") or project.get("project_id") or event_context.get("project_id") or "").strip()

    async def search_academic_sources(
        self,
        query: str,
        adapters: list[str] | None = None,
        limit: int = 10,
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        return AcademicSourceRegistry.search_payload(query, adapters=adapters, limit=limit)

    async def create_research_task(
        self,
        topic: str,
        project_id: str = "",
        thread_id: str = "",
        source_policy: dict[str, Any] | None = None,
        output_format: str = "markdown",
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        domain = self._core_domain
        if domain is None:
            return {"ok": False, "code": "core_domain_unavailable", "message": "Core domain is not available."}
        normalized_project_id = str(project_id or "").strip() or self._route_project_id(route_context)
        normalized_thread_id = str(thread_id or "").strip() or self._route_value(route_context, "thread_id")
        project = domain.services.project.get_by_project_id(normalized_project_id) if normalized_project_id else None
        thread = domain.services.thread.get_by_thread_id(normalized_thread_id) if normalized_thread_id else None
        if normalized_project_id and project is None:
            return {"ok": False, "code": "project_not_found", "message": f"Unknown project: {normalized_project_id}"}
        if normalized_thread_id and thread is None:
            return {"ok": False, "code": "thread_not_found", "message": f"Unknown thread: {normalized_thread_id}"}
        try:
            task = domain.services.research_task.create_task(
                principal_id=domain.principal.id,
                project_id=getattr(project, "id", None),
                thread_id=getattr(thread, "id", None),
                topic=topic,
                source_policy=source_policy,
                output_format=output_format,
                metadata={"created_from": "tool.create_research_task"},
            )
        except ValueError as exc:
            return {"ok": False, "code": "invalid_research_task", "message": str(exc)}
        return {
            "ok": True,
            "research_task_id": task.research_task_id,
            "project_id": str(getattr(project, "project_id", "") or ""),
            "thread_id": str(getattr(thread, "thread_id", "") or ""),
            "status": task.status,
            "topic": task.topic,
            "plan": dict(task.plan or {}),
            "source_policy": dict(task.source_policy or {}),
        }

    async def manage_research_tasks(
        self,
        action: str = "list",
        research_task_id: str = "",
        project_id: str = "",
        thread_id: str = "",
        status: str = "",
        plan: dict[str, Any] | None = None,
        evidence_ledger: list[dict[str, Any]] | None = None,
        summary: str = "",
        report_markdown: str = "",
        report_filename: str = "",
        limit: int = 50,
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        domain = self._core_domain
        if domain is None:
            return {"ok": False, "code": "core_domain_unavailable", "message": "Core domain is not available."}
        normalized_action = str(action or "list").strip().lower()
        if normalized_action == "list":
            normalized_project_id = str(project_id or "").strip() or self._route_project_id(route_context)
            normalized_thread_id = str(thread_id or "").strip() or self._route_value(route_context, "thread_id")
            project = domain.services.project.get_by_project_id(normalized_project_id) if normalized_project_id else None
            thread = domain.services.thread.get_by_thread_id(normalized_thread_id) if normalized_thread_id else None
            if normalized_project_id and project is None:
                return {"ok": False, "code": "project_not_found", "message": f"Unknown project: {normalized_project_id}"}
            if normalized_thread_id and thread is None:
                return {"ok": False, "code": "thread_not_found", "message": f"Unknown thread: {normalized_thread_id}"}
            rows = domain.services.research_task.list_tasks(
                principal_id=domain.principal.id,
                project_id=getattr(project, "id", None),
                thread_id=getattr(thread, "id", None),
                limit=limit,
            )
            return {
                "ok": True,
                "tasks": [
                    {
                        "research_task_id": row.research_task_id,
                        "topic": row.topic,
                        "status": row.status,
                        "summary": row.summary,
                        "plan": dict(row.plan or {}),
                    }
                    for row in rows
                ],
            }
        if not research_task_id:
            return {"ok": False, "code": "research_task_id_required", "message": "research_task_id is required."}
        task = domain.services.research_task.get_by_research_task_id(research_task_id)
        if task is None:
            return {"ok": False, "code": "research_task_not_found", "message": f"Unknown research task: {research_task_id}"}
        if normalized_action in {"run", "execute"}:
            result = ResearchExecutionService(
                domain.services,
                adapter_config=ResearchAdapterConfig.from_env(),
            ).run_task(research_task_id)
            refreshed = domain.services.research_task.get_by_research_task_id(research_task_id) or task
            return {
                **dict(result or {}),
                "research_task_id": refreshed.research_task_id,
                "status": refreshed.status,
                "topic": refreshed.topic,
                "summary": refreshed.summary,
                "plan": dict(refreshed.plan or {}),
                "evidence_ledger": list(refreshed.evidence_ledger or []),
            }
        fields: dict[str, Any] = {}
        transition_action = "" if normalized_action in {"list", "update"} else normalized_action
        if status:
            fields["status"] = status
        if plan is not None:
            fields["plan"] = plan
        if evidence_ledger is not None:
            fields["evidence_ledger"] = evidence_ledger
        if summary:
            fields["summary"] = summary
        artifact_payload: dict[str, Any] = {}
        if report_markdown:
            if not transition_action:
                transition_action = "complete"
            if transition_action != "complete":
                return {
                    "ok": False,
                    "code": "research_action_invalid",
                    "message": "report_markdown can only be submitted with action=complete or without an action.",
                }
            try:
                domain.services.research_task.normalize_update_fields(
                    current_status=str(getattr(task, "status", "") or "planned"),
                    action=transition_action,
                    fields=fields,
                    existing_metadata=dict(getattr(task, "meta", {}) or {}),
                )
            except ResearchTaskStateError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            validation_ledger = evidence_ledger if evidence_ledger is not None else list(task.evidence_ledger or [])
            try:
                citation_validation = domain.services.research_task.validate_report_citations(
                    report_markdown,
                    validation_ledger,
                )
            except ResearchTaskCitationError as exc:
                return {
                    "ok": False,
                    "code": "research_report_citation_invalid",
                    "message": str(exc),
                    "missing_source_ids": exc.missing_source_ids,
                    "citation_ids": exc.citation_ids,
                    "evidence_source_ids": exc.evidence_source_ids,
                }
            artifact = domain.services.artifact.create_text_artifact(
                principal_id=domain.principal.id,
                project_id=getattr(task, "project_id", None),
                thread_id=getattr(task, "thread_id", None),
                text=report_markdown,
                filename=report_filename or f"{research_task_id}.md",
                artifact_type="research_report",
                metadata={"research_task_id": research_task_id, "citation_validation": citation_validation},
            )
            try:
                derived_artifacts = create_research_report_derivatives(
                    domain.services.artifact,
                    task=task,
                    report_markdown=report_markdown,
                    source_artifact=artifact,
                    citation_validation=citation_validation,
                    runner="tool.manage_research_tasks.report_submit.v1",
                )
            except Exception as exc:  # noqa: BLE001 - tool callers need a structured failure.
                return {
                    "ok": False,
                    "code": "research_report_derivative_failed",
                    "message": "Research report derivative artifact creation failed.",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            fields["artifact_id"] = artifact.id
            fields.setdefault("metadata", {})
            fields["metadata"] = {
                **dict(fields.get("metadata") or {}),
                "artifact_id": artifact.artifact_id,
                "citation_validation": citation_validation,
                "derived_artifacts": derived_artifacts,
                "derived_artifact_ids": [item["artifact_id"] for item in derived_artifacts],
            }
            artifact_payload = {
                "artifact_id": artifact.artifact_id,
                "download_url": f"/runtime/artifacts/{artifact.artifact_id}/download",
                "filename": artifact.filename,
                "checksum": artifact.checksum,
                "citation_validation": citation_validation,
                "derived_artifacts": derived_artifacts,
            }
        try:
            task = domain.services.research_task.transition_task(
                research_task_id=research_task_id,
                action=transition_action,
                fields=fields,
            ) or task
        except ResearchTaskStateError as exc:
            return {"ok": False, "code": exc.code, "message": str(exc)}
        return {
            "ok": True,
            "research_task_id": task.research_task_id,
            "status": task.status,
            "topic": task.topic,
            "summary": task.summary,
            "plan": dict(task.plan or {}),
            "evidence_ledger": list(task.evidence_ledger or []),
            "artifact": artifact_payload,
        }
