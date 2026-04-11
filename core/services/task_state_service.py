from __future__ import annotations

from core.db.repositories import TaskStateRepository
from core.services.base import ServiceBase


class TaskStateService(ServiceBase):
    def replace_tasks(self, *, principal_id, tasks: list[dict]) -> int:
        with self.session_scope() as session:
            repo = TaskStateRepository(session)
            repo.delete_all_for_principal(principal_id)
            count = 0
            for payload in tasks:
                repo.create(principal_id=principal_id, **payload)
                count += 1
            return count
