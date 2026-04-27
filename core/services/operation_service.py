from __future__ import annotations

from uuid import uuid4

from core.db.repositories import OperationRepository
from core.services.base import ServiceBase


class OperationService(ServiceBase):
    def create_operation(
        self,
        *,
        thread_id,
        workspace_id,
        operation_type: str,
        execution_target: str,
        title: str = "",
        execution_target_type: str = "endpoint",
        execution_target_id: str = "",
        target_endpoint_id=None,
        requested_by_actor_id=None,
        requested_by_run_id=None,
        requested_by_client_id=None,
        requested_by_session_id=None,
        status: str = "queued",
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return OperationRepository(session).create(
                operation_id=f"op_{uuid4().hex}",
                thread_id=thread_id,
                workspace_id=workspace_id,
                operation_type=operation_type,
                execution_target=execution_target,
                title=title,
                execution_target_type=execution_target_type,
                execution_target_id=execution_target_id,
                target_endpoint_id=target_endpoint_id,
                requested_by_actor_id=requested_by_actor_id,
                requested_by_run_id=requested_by_run_id,
                requested_by_client_id=requested_by_client_id,
                requested_by_session_id=requested_by_session_id,
                status=status,
                metadata=metadata,
            )

    def get_by_operation_id(self, operation_id: str):
        with self.session_scope() as session:
            return OperationRepository(session).get_by_operation_id(operation_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return OperationRepository(session).get_by_id(row_id)

    def update_status(self, *, operation_id, status: str, result_summary: str | None = None, metadata: dict | None = None):
        with self.session_scope() as session:
            return OperationRepository(session).update_status(
                operation_id=operation_id,
                status=status,
                result_summary=result_summary,
                metadata=metadata,
            )
