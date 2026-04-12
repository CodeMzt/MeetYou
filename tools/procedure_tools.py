from __future__ import annotations

import re
from typing import Any

from tools import system_tools


_SLUG_RE = re.compile(r"[^a-z0-9]+")


class ProcedureTools:
    def __init__(self) -> None:
        self._core_domain = None

    def set_core_domain(self, core_domain) -> None:
        self._core_domain = core_domain

    def _require_core_domain(self):
        if self._core_domain is None:
            error = RuntimeError("Core domain is not ready")
            error.tool_error_code = "core_domain_unavailable"
            error.tool_error_message = "Procedure governance is unavailable before the Core domain finishes booting."
            error.tool_error_retryable = True
            raise error
        return self._core_domain

    @staticmethod
    def _normalize_list(value: Any) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized = str(item or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    @staticmethod
    def _slugify(value: Any) -> str:
        return _SLUG_RE.sub("_", str(value or "").strip().lower()).strip("_")[:128]

    @staticmethod
    def _proposal_title(action: str) -> str:
        action_map = {
            "propose_create": "Create Procedure",
            "propose_update": "Update Procedure",
            "propose_delete": "Archive Procedure",
            "propose_pin": "Pin Procedure To Thread",
            "propose_unpin": "Unpin Procedure From Thread",
        }
        return action_map.get(action, "Procedure Governance")

    @staticmethod
    def _procedure_summary(detail: dict[str, Any]) -> str:
        procedure_id = str(detail.get("procedure_id") or "").strip()
        title = str(detail.get("title") or "").strip()
        if procedure_id and title and procedure_id != title:
            return f"{title} ({procedure_id})"
        return title or procedure_id or "Unnamed procedure"

    async def _confirm(self, *, prompt: str, action: str, session_id: str, source, metadata: dict[str, Any]) -> bool:
        return await system_tools.request_user_confirmation(
            prompt,
            session_id=session_id,
            source=source,
            timeout_seconds=120,
            metadata={
                "approval_type": "procedure_governance",
                "approval_operation_type": "procedure_governance",
                "approval_title": self._proposal_title(action),
                "risk_level": "write",
                **dict(metadata or {}),
            },
        )

    def _resolve_thread_for_session(self, services, session_id: str):
        session_row = services.session.get_by_session_id(session_id)
        if session_row is None:
            error = RuntimeError("Session not found")
            error.tool_error_code = "session_not_found"
            error.tool_error_message = f"Unknown session: {session_id}"
            raise error
        thread_row = services.thread.get_by_id(session_row.thread_id)
        if thread_row is None:
            error = RuntimeError("Thread not found")
            error.tool_error_code = "thread_not_found"
            error.tool_error_message = "Current session is not attached to a valid thread."
            raise error
        return session_row, thread_row

    async def manage_procedures(
        self,
        action: str,
        procedure_id: str = "",
        title: str = "",
        description: str = "",
        prompt_overlay: str = "",
        default_execution_target: str = "",
        risk_profile: str = "",
        applicable_modes: list[str] | None = None,
        recommended_capabilities: list[str] | None = None,
        recommended_source_profiles: list[str] | None = None,
        infer_keywords: list[str] | None = None,
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> dict[str, Any]:
        del route_context, activity_callback
        domain = self._require_core_domain()
        services = domain.services
        normalized_action = str(action or "").strip().lower()

        if normalized_action == "list":
            procedures = services.procedure.list_active(principal_id=domain.principal.id)
            return {
                "action": normalized_action,
                "count": len(procedures),
                "procedures": [services.procedure.get_detail_view(item) for item in procedures],
            }

        if normalized_action == "detail":
            detail = services.procedure.get_detail_by_procedure_id(str(procedure_id or "").strip())
            if detail is None:
                error = RuntimeError("Procedure not found")
                error.tool_error_code = "procedure_not_found"
                error.tool_error_message = f"Unknown procedure: {procedure_id}"
                raise error
            return {"action": normalized_action, "procedure": detail}

        if normalized_action == "propose_create":
            normalized_title = str(title or "").strip()
            if not normalized_title:
                error = RuntimeError("Title required")
                error.tool_error_code = "procedure_title_required"
                error.tool_error_message = "title is required when proposing a new procedure."
                raise error
            normalized_procedure_id = self._slugify(procedure_id or normalized_title)
            prompt = (
                f"Approve creating procedure {normalized_title} ({normalized_procedure_id})?\n"
                f"Description: {str(description or '').strip() or '<empty>'}\n"
                f"Default execution target: {str(default_execution_target or '').strip() or '<empty>'}"
            )
            confirmed = await self._confirm(
                prompt=prompt,
                action=normalized_action,
                session_id=session_id,
                source=source,
                metadata={"procedure_id": normalized_procedure_id},
            )
            if not confirmed:
                return {"action": normalized_action, "status": "rejected", "procedure_id": normalized_procedure_id}
            created = services.procedure.create_procedure(
                principal_id=domain.principal.id,
                procedure_id=normalized_procedure_id,
                title=normalized_title,
                description=description,
                prompt_overlay=prompt_overlay,
                default_execution_target=default_execution_target,
                risk_profile=risk_profile or "standard",
                applicable_modes=self._normalize_list(applicable_modes),
                recommended_capabilities=self._normalize_list(recommended_capabilities),
                recommended_source_profiles=self._normalize_list(recommended_source_profiles),
                meta={"infer_keywords": self._normalize_list(infer_keywords) or []},
            )
            return {"action": normalized_action, "status": "applied", "procedure": services.procedure.get_detail_view(created)}

        if normalized_action == "propose_update":
            normalized_procedure_id = str(procedure_id or "").strip()
            existing = services.procedure.get_by_procedure_id(normalized_procedure_id)
            if existing is None:
                error = RuntimeError("Procedure not found")
                error.tool_error_code = "procedure_not_found"
                error.tool_error_message = f"Unknown procedure: {normalized_procedure_id}"
                raise error
            before = services.procedure.get_detail_view(existing)
            prompt = (
                f"Approve updating procedure {self._procedure_summary(before)}?\n"
                f"New title: {str(title).strip() or before['title']}\n"
                f"New default execution target: {str(default_execution_target).strip() or before['default_execution_target']}"
            )
            confirmed = await self._confirm(
                prompt=prompt,
                action=normalized_action,
                session_id=session_id,
                source=source,
                metadata={"procedure_id": normalized_procedure_id},
            )
            if not confirmed:
                return {"action": normalized_action, "status": "rejected", "procedure_id": normalized_procedure_id}
            updated = services.procedure.update_procedure(
                procedure_id=normalized_procedure_id,
                title=title if title != "" else None,
                description=description if description != "" else None,
                prompt_overlay=prompt_overlay if prompt_overlay != "" else None,
                default_execution_target=default_execution_target if default_execution_target != "" else None,
                risk_profile=risk_profile if risk_profile != "" else None,
                applicable_modes=self._normalize_list(applicable_modes),
                recommended_capabilities=self._normalize_list(recommended_capabilities),
                recommended_source_profiles=self._normalize_list(recommended_source_profiles),
                meta={"infer_keywords": self._normalize_list(infer_keywords) or []} if infer_keywords is not None else None,
            )
            return {"action": normalized_action, "status": "applied", "procedure": services.procedure.get_detail_view(updated)}

        if normalized_action == "propose_delete":
            normalized_procedure_id = str(procedure_id or "").strip()
            existing = services.procedure.get_by_procedure_id(normalized_procedure_id)
            if existing is None:
                error = RuntimeError("Procedure not found")
                error.tool_error_code = "procedure_not_found"
                error.tool_error_message = f"Unknown procedure: {normalized_procedure_id}"
                raise error
            detail = services.procedure.get_detail_view(existing)
            prompt = f"Approve archiving procedure {self._procedure_summary(detail)}? This also clears thread pins that still point to it."
            confirmed = await self._confirm(
                prompt=prompt,
                action=normalized_action,
                session_id=session_id,
                source=source,
                metadata={"procedure_id": normalized_procedure_id},
            )
            if not confirmed:
                return {"action": normalized_action, "status": "rejected", "procedure_id": normalized_procedure_id}
            services.procedure.archive_procedure(procedure_id=normalized_procedure_id)
            cleared_count = services.thread.clear_pinned_procedure_for_procedure(procedure_id=normalized_procedure_id)
            return {
                "action": normalized_action,
                "status": "applied",
                "procedure_id": normalized_procedure_id,
                "cleared_thread_pin_count": cleared_count,
            }

        if normalized_action == "propose_pin":
            normalized_procedure_id = str(procedure_id or "").strip()
            existing = services.procedure.get_by_procedure_id(normalized_procedure_id)
            if existing is None or str(getattr(existing, "status", "") or "") != "active":
                error = RuntimeError("Procedure not found")
                error.tool_error_code = "procedure_not_found"
                error.tool_error_message = f"Unknown active procedure: {normalized_procedure_id}"
                raise error
            _, thread_row = self._resolve_thread_for_session(services, session_id)
            if str(getattr(thread_row, "pinned_procedure_id", "") or "") == normalized_procedure_id:
                return {"action": normalized_action, "status": "noop", "procedure_id": normalized_procedure_id}
            detail = services.procedure.get_detail_view(existing)
            prompt = f"Approve pinning procedure {self._procedure_summary(detail)} to the current thread?"
            confirmed = await self._confirm(
                prompt=prompt,
                action=normalized_action,
                session_id=session_id,
                source=source,
                metadata={"procedure_id": normalized_procedure_id, "thread_id": thread_row.thread_id},
            )
            if not confirmed:
                return {"action": normalized_action, "status": "rejected", "procedure_id": normalized_procedure_id}
            services.thread.set_pinned_procedure(thread_id=thread_row.id, pinned_procedure_id=normalized_procedure_id)
            refreshed_thread = services.thread.get_by_id(thread_row.id)
            return {
                "action": normalized_action,
                "status": "applied",
                "thread_id": getattr(refreshed_thread, "thread_id", ""),
                "procedure_context": services.procedure.get_thread_context(refreshed_thread),
            }

        if normalized_action == "propose_unpin":
            _, thread_row = self._resolve_thread_for_session(services, session_id)
            current_pinned = str(getattr(thread_row, "pinned_procedure_id", "") or "").strip()
            if not current_pinned:
                return {"action": normalized_action, "status": "noop", "thread_id": thread_row.thread_id}
            prompt = f"Approve unpinning procedure {current_pinned} from the current thread?"
            confirmed = await self._confirm(
                prompt=prompt,
                action=normalized_action,
                session_id=session_id,
                source=source,
                metadata={"procedure_id": current_pinned, "thread_id": thread_row.thread_id},
            )
            if not confirmed:
                return {"action": normalized_action, "status": "rejected", "thread_id": thread_row.thread_id}
            services.thread.set_pinned_procedure(thread_id=thread_row.id, pinned_procedure_id=None)
            refreshed_thread = services.thread.get_by_id(thread_row.id)
            return {
                "action": normalized_action,
                "status": "applied",
                "thread_id": getattr(refreshed_thread, "thread_id", ""),
                "procedure_context": services.procedure.get_thread_context(refreshed_thread),
            }

        error = RuntimeError("Unsupported action")
        error.tool_error_code = "unsupported_procedure_action"
        error.tool_error_message = f"Unsupported manage_procedures action: {normalized_action}"
        raise error
