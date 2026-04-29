from __future__ import annotations

from core.db.models.operation import Operation
from core.db.repositories.base import RepositoryBase


class OperationRepository(RepositoryBase):
    def create(
        self,
        *,
        operation_id: str,
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
        requested_by_session_id=None,
        status: str = "queued",
        metadata: dict | None = None,
    ) -> Operation:
        operation = Operation(
            operation_id=operation_id,
            thread_id=thread_id,
            workspace_id=workspace_id,
            requested_by_session_id=requested_by_session_id,
            requested_by_actor_id=requested_by_actor_id,
            requested_by_run_id=requested_by_run_id,
            operation_type=operation_type,
            execution_target=execution_target,
            execution_target_type=execution_target_type,
            execution_target_id=execution_target_id,
            target_endpoint_id=target_endpoint_id,
            status=status,
            title=title,
            meta=dict(metadata or {}),
        )
        self.session.add(operation)
        self.session.flush()
        return operation

    def get_by_operation_id(self, operation_id: str) -> Operation | None:
        return self.session.query(Operation).filter_by(operation_id=operation_id).one_or_none()

    def get_by_id(self, row_id) -> Operation | None:
        return self.session.query(Operation).filter_by(id=row_id).one_or_none()

    def update_status(self, *, operation_id, status: str, result_summary: str | None = None, metadata: dict | None = None) -> Operation | None:
        operation = self.get_by_id(operation_id)
        if operation is None:
            return None
        operation.status = status
        if result_summary is not None:
            operation.result_summary = result_summary
        if metadata is not None:
            merged = dict(operation.meta or {})
            merged.update(dict(metadata))
            operation.meta = merged
        self.session.flush()
        return operation
