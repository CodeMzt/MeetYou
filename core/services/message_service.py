from __future__ import annotations

from uuid import uuid4

from core.db.base import utcnow
from core.db.models import Message, Thread
from core.db.repositories import MessageRepository
from core.services.base import ServiceBase
from core.services.thread_titles import can_auto_title_thread


class MessageService(ServiceBase):
    def create_message(
        self,
        *,
        thread_id,
        role: str,
        content: str,
        session_id=None,
        run_id=None,
        channel: str = "message",
        content_type: str = "text",
        status: str = "completed",
        created_by_actor_id=None,
        origin_endpoint_id=None,
        active_workspace_id=None,
        parent_message_id=None,
        branch_id=None,
        revision_of_message_id=None,
        variant_index: int = 0,
        visibility: str = "active",
        meta: dict | None = None,
    ):
        with self.session_scope() as session:
            message = MessageRepository(session).create(
                message_id=f"msg_{uuid4().hex}",
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
                parent_message_id=parent_message_id,
                branch_id=branch_id,
                revision_of_message_id=revision_of_message_id,
                variant_index=variant_index,
                visibility=visibility,
                meta=meta,
            )
            self._maybe_mark_auto_title_pending(session, message)
            return message

    def _maybe_mark_auto_title_pending(self, session, message: Message) -> None:
        if str(getattr(message, "role", "") or "").strip().lower() != "user":
            return
        if str(getattr(message, "channel", "") or "message").strip().lower() != "message":
            return
        thread = session.get(Thread, getattr(message, "thread_id", None))
        if not can_auto_title_thread(thread):
            return
        user_message_count = (
            session.query(Message)
            .filter(
                Message.thread_id == message.thread_id,
                Message.role == "user",
                Message.channel == "message",
            )
            .count()
        )
        if user_message_count != 1:
            return
        metadata = dict(getattr(thread, "meta", {}) or {})
        metadata.update(
            {
                "auto_title_pending": True,
                "auto_title_source_message_id": getattr(message, "message_id", ""),
                "auto_title_requested_at": utcnow().isoformat(),
                "auto_title_strategy": "model",
            }
        )
        thread.meta = metadata
        thread.updated_at = utcnow()
        session.flush()

    def list_messages_for_thread(self, thread_id):
        with self.session_scope() as session:
            repo = MessageRepository(session)
            thread = session.get(Thread, thread_id)
            if thread is not None and getattr(thread, "current_leaf_message_id", None):
                path = repo.list_branch_path(
                    thread_id=thread_id,
                    leaf_message_id=thread.current_leaf_message_id,
                )
                if path:
                    return path
            return repo.list_by_thread_id(thread_id)

    def load_thread_context_window(
        self,
        *,
        thread_id,
        before_message_id: str = "",
        exclude_endpoint_message_id: str = "",
        limit: int = 24,
    ) -> dict:
        with self.session_scope() as session:
            return MessageRepository(session).load_thread_context_window(
                thread_id=thread_id,
                before_message_id=before_message_id,
                exclude_endpoint_message_id=exclude_endpoint_message_id,
                limit=limit,
            )

    def list_older_thread_context_messages(
        self,
        *,
        thread_id,
        before_message_id: str = "",
        exclude_endpoint_message_id: str = "",
        offset: int = 24,
        limit: int = 80,
    ):
        with self.session_scope() as session:
            return MessageRepository(session).list_older_thread_context_messages(
                thread_id=thread_id,
                before_message_id=before_message_id,
                exclude_endpoint_message_id=exclude_endpoint_message_id,
                offset=offset,
                limit=limit,
            )

    def get_by_endpoint_message_id(
        self,
        *,
        thread_id,
        endpoint_message_id: str,
        origin_endpoint_id=None,
        role: str = "user",
    ):
        with self.session_scope() as session:
            return MessageRepository(session).get_by_endpoint_message_id(
                thread_id=thread_id,
                endpoint_message_id=endpoint_message_id,
                origin_endpoint_id=origin_endpoint_id,
                role=role,
            )

    def get_by_message_id(self, message_id: str):
        with self.session_scope() as session:
            return MessageRepository(session).get_by_message_id(message_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return MessageRepository(session).get_by_id(row_id)
