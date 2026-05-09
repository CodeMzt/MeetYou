from __future__ import annotations

from core.db.models.message import Message
from core.db.repositories.base import RepositoryBase

_CONTEXT_ROLES = ("user", "assistant")


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
        parent_message_id=None,
        branch_id=None,
        revision_of_message_id=None,
        variant_index: int = 0,
        visibility: str = "active",
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
            parent_message_id=parent_message_id,
            branch_id=branch_id,
            revision_of_message_id=revision_of_message_id,
            variant_index=int(variant_index or 0),
            visibility=str(visibility or "active").strip() or "active",
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

    def _thread_context_query(
        self,
        *,
        thread_id,
        before_message_id: str = "",
    ):
        query = (
            self.session.query(Message)
            .filter(
                Message.thread_id == thread_id,
                Message.role.in_(_CONTEXT_ROLES),
                Message.channel == "message",
                Message.status == "completed",
            )
        )
        normalized_before = str(before_message_id or "").strip()
        before_row = self.get_by_message_id(normalized_before) if normalized_before else None
        if before_row is not None and getattr(before_row, "thread_id", None) == thread_id:
            query = query.filter(Message.created_at < before_row.created_at)
        if normalized_before:
            query = query.filter(Message.message_id != normalized_before)
        return query

    @staticmethod
    def _matches_endpoint_message_id(row: Message, endpoint_message_id: str) -> bool:
        normalized = str(endpoint_message_id or "").strip()
        if not normalized:
            return False
        meta = dict(getattr(row, "meta", {}) or {})
        return str(meta.get("endpoint_message_id") or "").strip() == normalized

    def load_thread_context_window(
        self,
        *,
        thread_id,
        before_message_id: str = "",
        exclude_endpoint_message_id: str = "",
        limit: int = 24,
    ) -> dict:
        bounded_limit = max(1, min(int(limit or 24), 200))
        query = self._thread_context_query(thread_id=thread_id, before_message_id=before_message_id)
        total_count = int(query.count())
        overfetch_limit = min(bounded_limit + 8, 240)
        rows_desc = list(query.order_by(Message.created_at.desc()).limit(overfetch_limit).all())
        rows: list[Message] = []
        excluded_count = 0
        for row in rows_desc:
            if self._matches_endpoint_message_id(row, exclude_endpoint_message_id):
                excluded_count += 1
                continue
            rows.append(row)
            if len(rows) >= bounded_limit:
                break
        effective_total_count = max(total_count - excluded_count, len(rows))
        return {
            "messages": list(reversed(rows)),
            "total_count": effective_total_count,
            "older_count": max(effective_total_count - len(rows), 0),
        }

    def list_older_thread_context_messages(
        self,
        *,
        thread_id,
        before_message_id: str = "",
        exclude_endpoint_message_id: str = "",
        offset: int = 24,
        limit: int = 80,
    ) -> list[Message]:
        bounded_offset = max(0, int(offset or 0))
        bounded_limit = max(1, min(int(limit or 80), 400))
        query = self._thread_context_query(thread_id=thread_id, before_message_id=before_message_id)
        overfetch_limit = min(bounded_limit + 8, 440)
        rows_desc = list(
            query.order_by(Message.created_at.desc())
            .offset(bounded_offset)
            .limit(overfetch_limit)
            .all()
        )
        rows: list[Message] = []
        for row in rows_desc:
            if self._matches_endpoint_message_id(row, exclude_endpoint_message_id):
                continue
            rows.append(row)
            if len(rows) >= bounded_limit:
                break
        return list(reversed(rows))

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

    def get_by_id(self, row_id) -> Message | None:
        return self.session.query(Message).filter_by(id=row_id).one_or_none()
