from __future__ import annotations

from core.db.models.task import TaskState
from core.db.repositories.base import RepositoryBase


class TaskStateRepository(RepositoryBase):
    def delete_all_for_principal(self, principal_id) -> None:
        self.session.query(TaskState).filter_by(principal_id=principal_id).delete()
        self.session.flush()

    def create(
        self,
        *,
        task_id: str,
        principal_id,
        title: str,
        scope_user_id: str,
        scope_session_id: str,
        task_type: str = "task",
        status: str = "active",
        execution_target: str = "core_only",
        due_at: str = "",
        next_run_at: str = "",
        workspace_id=None,
        raw_record: dict | None = None,
        meta: dict | None = None,
    ) -> TaskState:
        row = TaskState(
            task_id=task_id,
            principal_id=principal_id,
            workspace_id=workspace_id,
            scope_user_id=scope_user_id,
            scope_session_id=scope_session_id,
            task_type=task_type,
            status=status,
            title=title,
            execution_target=execution_target,
            due_at=due_at,
            next_run_at=next_run_at,
            raw_record=dict(raw_record or {}),
            meta=dict(meta or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row
