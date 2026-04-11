from __future__ import annotations

from core.db.models.operation import OperationCall
from core.db.repositories.base import RepositoryBase


class OperationCallRepository(RepositoryBase):
    def create(
        self,
        *,
        call_id: str,
        operation_id,
        capability_id,
        target_agent_id=None,
        status: str = "queued",
        arguments: dict | None = None,
        result: dict | None = None,
        error: dict | None = None,
    ) -> OperationCall:
        row = OperationCall(
            call_id=call_id,
            operation_id=operation_id,
            capability_id=capability_id,
            target_agent_id=target_agent_id,
            status=status,
            arguments=dict(arguments or {}),
            result=dict(result or {}),
            error=dict(error or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_call_id(self, call_id: str) -> OperationCall | None:
        return self.session.query(OperationCall).filter_by(call_id=call_id).one_or_none()

    def update_status(self, *, call_id: str, status: str, result: dict | None = None, error: dict | None = None) -> OperationCall | None:
        row = self.get_by_call_id(call_id)
        if row is None:
            return None
        row.status = status
        if result is not None:
            row.result = dict(result)
        if error is not None:
            row.error = dict(error)
        self.session.flush()
        return row
