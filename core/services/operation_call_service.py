from __future__ import annotations

from uuid import uuid4

from core.db.repositories import OperationCallRepository, OperationRepository
from core.services.base import ServiceBase


class OperationCallService(ServiceBase):
    def create_call(self, *, operation_id, capability_id, target_agent_id=None, status: str = "queued", arguments: dict | None = None):
        with self.session_scope() as session:
            return OperationCallRepository(session).create(
                call_id=f"call_{uuid4().hex}",
                operation_id=operation_id,
                capability_id=capability_id,
                target_agent_id=target_agent_id,
                status=status,
                arguments=arguments,
            )

    def get_by_call_id(self, call_id: str):
        with self.session_scope() as session:
            return OperationCallRepository(session).get_by_call_id(call_id)

    def mark_dispatched(self, *, call_id: str):
        with self.session_scope() as session:
            row = OperationCallRepository(session).update_status(call_id=call_id, status="dispatched")
            if row is not None:
                OperationRepository(session).update_status(operation_id=row.operation_id, status="dispatching")
            return row

    def mark_accepted(self, *, call_id: str):
        with self.session_scope() as session:
            row = OperationCallRepository(session).update_status(call_id=call_id, status="running")
            if row is not None:
                OperationRepository(session).update_status(operation_id=row.operation_id, status="running")
            return row

    def mark_progress(self, *, call_id: str, detail: str = "", metadata: dict | None = None):
        with self.session_scope() as session:
            row = OperationCallRepository(session).get_by_call_id(call_id)
            if row is None:
                return None
            OperationCallRepository(session).update_status(call_id=call_id, status="running")
            OperationRepository(session).update_status(
                operation_id=row.operation_id,
                status="running",
                metadata={"last_progress": {"detail": detail, **dict(metadata or {})}},
            )
            return row

    def mark_succeeded(self, *, call_id: str, result: dict | None = None):
        with self.session_scope() as session:
            row = OperationCallRepository(session).update_status(call_id=call_id, status="succeeded", result=result or {})
            if row is not None:
                summary = str((result or {}).get("summary") or (result or {}).get("message") or "")
                OperationRepository(session).update_status(
                    operation_id=row.operation_id,
                    status="succeeded",
                    result_summary=summary,
                    metadata={"result": dict(result or {})},
                )
            return row

    def mark_failed(self, *, call_id: str, error: dict | None = None):
        with self.session_scope() as session:
            row = OperationCallRepository(session).update_status(call_id=call_id, status="failed", error=error or {})
            if row is not None:
                OperationRepository(session).update_status(
                    operation_id=row.operation_id,
                    status="failed",
                    result_summary=str((error or {}).get("message") or ""),
                    metadata={"error": dict(error or {})},
                )
            return row
