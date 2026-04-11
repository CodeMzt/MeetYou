from __future__ import annotations

from core.db.models.attachment import AttachmentUploadTicket
from core.db.repositories.base import RepositoryBase


class AttachmentUploadTicketRepository(RepositoryBase):
    def create(
        self,
        *,
        ticket_id: str,
        attachment_id,
        issuer_type: str,
        issuer_ref: str,
        expires_at: str,
        metadata: dict | None = None,
    ) -> AttachmentUploadTicket:
        ticket = AttachmentUploadTicket(
            ticket_id=ticket_id,
            attachment_id=attachment_id,
            issuer_type=issuer_type,
            issuer_ref=issuer_ref,
            expires_at=expires_at,
            meta=dict(metadata or {}),
        )
        self.session.add(ticket)
        self.session.flush()
        return ticket

    def get_by_ticket_id(self, ticket_id: str) -> AttachmentUploadTicket | None:
        return self.session.query(AttachmentUploadTicket).filter_by(ticket_id=ticket_id).one_or_none()

    def update_status(self, ticket_id: str, *, status: str, metadata: dict | None = None) -> AttachmentUploadTicket | None:
        ticket = self.get_by_ticket_id(ticket_id)
        if ticket is None:
            return None
        ticket.status = status
        if metadata is not None:
            merged = dict(ticket.meta or {})
            merged.update(dict(metadata))
            ticket.meta = merged
        self.session.flush()
        return ticket
