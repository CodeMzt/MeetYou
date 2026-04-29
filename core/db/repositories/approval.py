from __future__ import annotations

from core.db.models.approval import Approval
from core.db.repositories.base import RepositoryBase


class ApprovalRepository(RepositoryBase):
    def create(self, *, approval_id: str, operation_id, approval_type: str, risk_level: str) -> Approval:
        approval = Approval(
            approval_id=approval_id,
            operation_id=operation_id,
            approval_type=approval_type,
            risk_level=risk_level,
        )
        self.session.add(approval)
        self.session.flush()
        return approval

    def get_by_approval_id(self, approval_id: str) -> Approval | None:
        return self.session.query(Approval).filter_by(approval_id=approval_id).one_or_none()

    def decide(self, *, approval_id: str, decision: str, reason: str = "", decided_by_actor_id=None) -> Approval | None:
        approval = self.get_by_approval_id(approval_id)
        if approval is None:
            return None
        approval.decision = decision
        approval.reason = reason
        approval.status = "approved" if decision == "approve" else "rejected"
        approval.decided_by_actor_id = decided_by_actor_id
        self.session.flush()
        return approval
