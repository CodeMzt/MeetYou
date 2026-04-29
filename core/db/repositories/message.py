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
        run_id=None,
        channel: str = "message",
        status: str = "completed",
        content_type: str = "text",
        created_by_actor_id=None,
        origin_endpoint_id=None,
        active_workspace_id=None,
        meta: dict | None = None,
    ) -> Message:
        row = Message(
            message_id=message_id,
            thread_id=thread_id,
            session_id=session_id,
            run_id=run_id,
            role=role,
            channel=channel,
            content=content,
            content_type=content_type,
            status=status,
            created_by_actor_id=created_by_actor_id,
            origin_endpoint_id=origin_endpoint_id,
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

    def get_by_endpoint_message_id(
        self,
        *,
        thread_id,
        endpoint_message_id: str,
        origin_endpoint_id=None,
        role: str = "user",
    ) -> Message | None:
        normalized = str(endpoint_message_id or "").strip()
        if not normalized:
            return None
        query = self.session.query(Message).filter_by(thread_id=thread_id, role=role)
        if origin_endpoint_id is not None:
            query = query.filter_by(origin_endpoint_id=origin_endpoint_id)
        for row in query.order_by(Message.created_at.asc()).all():
            meta = dict(row.meta or {})
            if str(meta.get("endpoint_message_id") or "").strip() == normalized:
                return row
        return None

    def get_by_message_id(self, message_id: str) -> Message | None:
        return self.session.query(Message).filter_by(message_id=message_id).one_or_none()
