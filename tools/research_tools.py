from __future__ import annotations

from typing import Any

from core.services.v5_service import ResearchTaskCitationError
from tools.academic_sources import AcademicSourceRegistry


class ResearchTools:
    def __init__(self) -> None:
        self._core_domain = None

    def set_core_domain(self, core_domain) -> None:
        self._core_domain = core_domain

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
        del route_context
        domain = self._core_domain
        if domain is None:
            return {"ok": False, "code": "core_domain_unavailable", "message": "Core domain is not available."}
        project = domain.services.project.get_by_project_id(project_id) if str(project_id or "").strip() else None
        thread = domain.services.thread.get_by_thread_id(thread_id) if str(thread_id or "").strip() else None
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
        status: str = "",
        plan: dict[str, Any] | None = None,
        evidence_ledger: list[dict[str, Any]] | None = None,
        summary: str = "",
        report_markdown: str = "",
        report_filename: str = "",
        limit: int = 50,
        route_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del route_context
        domain = self._core_domain
        if domain is None:
            return {"ok": False, "code": "core_domain_unavailable", "message": "Core domain is not available."}
        normalized_action = str(action or "list").strip().lower()
        if normalized_action == "list":
            project = domain.services.project.get_by_project_id(project_id) if str(project_id or "").strip() else None
            rows = domain.services.research_task.list_tasks(
                principal_id=domain.principal.id,
                project_id=getattr(project, "id", None),
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
        fields: dict[str, Any] = {}
        if normalized_action in {"start", "cancel", "complete"}:
            fields["status"] = {"start": "running", "cancel": "cancelled", "complete": "completed"}[normalized_action]
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
            fields["artifact_id"] = artifact.id
            fields.setdefault("metadata", {})
            fields["metadata"] = {
                **dict(fields.get("metadata") or {}),
                "artifact_id": artifact.artifact_id,
                "citation_validation": citation_validation,
            }
            fields.setdefault("status", "completed")
            artifact_payload = {
                "artifact_id": artifact.artifact_id,
                "download_url": f"/runtime/artifacts/{artifact.artifact_id}/download",
                "filename": artifact.filename,
                "checksum": artifact.checksum,
                "citation_validation": citation_validation,
            }
        task = domain.services.research_task.update_task(research_task_id=research_task_id, fields=fields) or task
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
