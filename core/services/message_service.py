from __future__ import annotations

from uuid import uuid4

from core.db.repositories import MessageRepository
from core.services.base import ServiceBase


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
        meta: dict | None = None,
    ):
        with self.session_scope() as session:
            return MessageRepository(session).create(
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
                meta=meta,
            )

    def list_messages_for_thread(self, thread_id):
        with self.session_scope() as session:
            return MessageRepository(session).list_by_thread_id(thread_id)

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
