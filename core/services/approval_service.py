from __future__ import annotations

from uuid import uuid4

from core.db.repositories import ApprovalRepository
from core.services.base import ServiceBase


class ApprovalService(ServiceBase):
    def create_approval(self, *, operation_id, approval_type: str, risk_level: str):
        with self.session_scope() as session:
            return ApprovalRepository(session).create(
                approval_id=f"approval_{uuid4().hex}",
                operation_id=operation_id,
                approval_type=approval_type,
                risk_level=risk_level,
            )

    def get_by_approval_id(self, approval_id: str):
        with self.session_scope() as session:
            return ApprovalRepository(session).get_by_approval_id(approval_id)

    def decide_approval(self, *, approval_id: str, decision: str, reason: str = "", decided_by_actor_id=None):
        with self.session_scope() as session:
            return ApprovalRepository(session).decide(
                approval_id=approval_id,
                decision=decision,
                reason=reason,
                decided_by_actor_id=decided_by_actor_id,
            )
