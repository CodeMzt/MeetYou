from __future__ import annotations

from core.db.models.message import Message
from core.db.repositories.base import RepositoryBase


class MessageRepository(RepositoryBase):
    def create(
        self,
        *,
        message_id: str,
        thread_id,
        role: str,
        content: str,
        session_id=None,
        channel: str = "message",
        status: str = "completed",
        source_client_id=None,
        active_workspace_id=None,
        meta: dict | None = None,
    ) -> Message:
        row = Message(
            message_id=message_id,
            thread_id=thread_id,
            session_id=session_id,
            role=role,
            channel=channel,
            content=content,
            status=status,
            source_client_id=source_client_id,
            active_workspace_id=active_workspace_id,
            meta=dict(meta or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_by_thread_id(self, thread_id) -> list[Message]:
        return list(
            self.session.query(Message)
            .filter_by(thread_id=thread_id)
            .order_by(Message.created_at.asc())
            .all()
        )

    def get_by_message_id(self, message_id: str) -> Message | None:
        return self.session.query(Message).filter_by(message_id=message_id).one_or_none()
