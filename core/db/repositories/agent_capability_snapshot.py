from __future__ import annotations

from datetime import datetime

from core.db.models.agent import AgentCapabilitySnapshot
from core.db.repositories.base import RepositoryBase


class AgentCapabilitySnapshotRepository(RepositoryBase):
    def create(self, *, agent_id, revision: int, status: str, snapshot: dict, received_at: datetime) -> AgentCapabilitySnapshot:
        row = AgentCapabilitySnapshot(
            agent_id=agent_id,
            revision=revision,
            status=status,
            snapshot=dict(snapshot or {}),
            received_at=received_at.isoformat(),
        )
        self.session.add(row)
        self.session.flush()
        return row
