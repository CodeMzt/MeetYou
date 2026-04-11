from __future__ import annotations

from core.db.models.attachment import Attachment
from core.db.repositories.base import RepositoryBase


class AttachmentRepository(RepositoryBase):
    def get_by_id(self, attachment_id):
        return self.session.get(Attachment, attachment_id)

    def create(
        self,
        *,
        attachment_id: str,
        owner_type: str,
        owner_id: str,
        kind: str,
        mime_type: str,
        object_key: str,
        size_bytes: int = 0,
        origin_agent_id=None,
        origin_client_id=None,
        storage_class: str = "standard",
        lifecycle_policy: str = "normal",
        expires_at: str | None = None,
        sha256: str = "",
        status: str = "pending",
        metadata: dict | None = None,
    ) -> Attachment:
        attachment = Attachment(
            attachment_id=attachment_id,
            owner_type=owner_type,
            owner_id=owner_id,
            origin_agent_id=origin_agent_id,
            origin_client_id=origin_client_id,
            kind=kind,
            mime_type=mime_type,
            object_key=object_key,
            size_bytes=size_bytes,
            storage_class=storage_class,
            lifecycle_policy=lifecycle_policy,
            expires_at=expires_at,
            sha256=sha256,
            status=status,
            meta=dict(metadata or {}),
        )
        self.session.add(attachment)
        self.session.flush()
        return attachment

    def get_by_attachment_id(self, attachment_id: str) -> Attachment | None:
        return self.session.query(Attachment).filter_by(attachment_id=attachment_id).one_or_none()

    def update_attachment(
        self,
        attachment_id: str,
        *,
        status: str | None = None,
        size_bytes: int | None = None,
        sha256: str | None = None,
        metadata: dict | None = None,
    ) -> Attachment | None:
        attachment = self.get_by_attachment_id(attachment_id)
        if attachment is None:
            return None
        if status is not None:
            attachment.status = status
        if size_bytes is not None:
            attachment.size_bytes = size_bytes
        if sha256 is not None:
            attachment.sha256 = sha256
        if metadata is not None:
            merged = dict(attachment.meta or {})
            merged.update(dict(metadata))
            attachment.meta = merged
        self.session.flush()
        return attachment
