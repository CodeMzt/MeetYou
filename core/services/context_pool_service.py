from __future__ import annotations

import re
from uuid import uuid4
from typing import Any

from core.db.repositories import ContextPoolRepository, SessionRepository, ThreadRepository, WorkspaceRepository
from core.services.base import ServiceBase


_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class ContextPoolService(ServiceBase):
    @staticmethod
    def _canonicalize(text: str) -> str:
        return " ".join(_TOKEN_RE.findall(str(text or "").lower()))

    @classmethod
    def _tokens(cls, text: str) -> set[str]:
        return set(_TOKEN_RE.findall(cls._canonicalize(text)))

    @staticmethod
    def _workspace_tags(*values) -> list[str]:
        tags: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            tags.append(text)
        return tags

    def add_item(
        self,
        *,
        principal_id,
        content: str,
        thread_id=None,
        session_id=None,
        message_id=None,
        source_client_id=None,
        source_agent_id=None,
        home_workspace_id=None,
        active_workspace_id=None,
        item_type: str = "turn",
        role: str = "",
        importance: float = 0.5,
        workspace_tags: list[str] | None = None,
        metadata: dict | None = None,
    ):
        text = str(content or "").strip()
        if not text:
            return None
        with self.session_scope() as session:
            return ContextPoolRepository(session).create(
                context_id=f"ctx_{uuid4().hex}",
                principal_id=principal_id,
                thread_id=thread_id,
                session_id=session_id,
                message_id=message_id,
                source_client_id=source_client_id,
                source_agent_id=source_agent_id,
                home_workspace_id=home_workspace_id,
                active_workspace_id=active_workspace_id,
                item_type=str(item_type or "turn").strip() or "turn",
                role=str(role or "").strip(),
                content=text,
                canonical_text=self._canonicalize(text),
                importance=max(0.0, min(1.0, float(importance or 0.5))),
                workspace_tags=list(workspace_tags or []),
                meta=dict(metadata or {}),
            )

    def record_message(
        self,
        *,
        principal_id,
        message,
        thread=None,
        session=None,
        client=None,
        active_workspace=None,
        home_workspace=None,
        metadata: dict | None = None,
    ):
        home_workspace_id = getattr(thread, "home_workspace_id", None) or getattr(thread, "workspace_id", None)
        active_workspace_id = getattr(message, "active_workspace_id", None) or getattr(session, "active_workspace_id", None)
        home_workspace_key = getattr(home_workspace, "workspace_id", "") or ""
        active_workspace_key = getattr(active_workspace, "workspace_id", "") or ""
        return self.add_item(
            principal_id=principal_id,
            thread_id=getattr(thread, "id", None),
            session_id=getattr(session, "id", None),
            message_id=getattr(message, "id", None),
            source_client_id=getattr(client, "id", None),
            home_workspace_id=home_workspace_id,
            active_workspace_id=active_workspace_id,
            item_type="turn",
            role=getattr(message, "role", "") or "",
            content=getattr(message, "content", "") or "",
            importance=0.65 if getattr(message, "role", "") == "user" else 0.45,
            workspace_tags=self._workspace_tags(home_workspace_key, active_workspace_key),
            metadata={
                **dict(metadata or {}),
                "message_id": getattr(message, "message_id", ""),
                "thread_id": getattr(thread, "thread_id", ""),
                "session_id": getattr(session, "session_id", ""),
                "client_id": getattr(client, "client_id", ""),
                "home_workspace_id": home_workspace_key,
                "active_workspace_id": active_workspace_key,
            },
        )

    def query(
        self,
        *,
        principal_id,
        query_text: str,
        thread_id=None,
        session_id=None,
        active_workspace_id=None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        query_tokens = self._tokens(query_text)
        with self.session_scope() as session:
            candidates = ContextPoolRepository(session).list_candidates(
                principal_id=principal_id,
                thread_id=thread_id,
                session_id=session_id,
                active_workspace_id=active_workspace_id,
                limit=200,
            )
            rows = []
            for item in candidates:
                item_tokens = set(_TOKEN_RE.findall(str(item.canonical_text or "")))
                lexical = len(query_tokens & item_tokens) / max(len(query_tokens), 1) if query_tokens else 0.0
                same_session = bool(session_id is not None and item.session_id == session_id)
                same_thread = bool(thread_id is not None and item.thread_id == thread_id)
                same_workspace = bool(
                    active_workspace_id is not None
                    and (item.active_workspace_id == active_workspace_id or item.home_workspace_id == active_workspace_id)
                )
                score = (
                    0.55 * lexical
                    + 0.2 * float(item.importance or 0.0)
                    + (0.18 if same_thread else 0.0)
                    + (0.12 if same_session else 0.0)
                    + (0.1 if same_workspace else 0.0)
                )
                if score <= 0 and query_tokens:
                    continue
                rows.append(
                    {
                        "context_id": item.context_id,
                        "item_type": item.item_type,
                        "role": item.role,
                        "content": item.content,
                        "score": round(score, 4),
                        "same_session": same_session,
                        "same_thread": same_thread,
                        "same_workspace": same_workspace,
                        "workspace_tags": list(item.workspace_tags or []),
                        "metadata": dict(item.meta or {}),
                        "created_at": item.created_at.isoformat() if getattr(item, "created_at", None) else "",
                    }
                )
            rows.sort(key=lambda row: row["score"], reverse=True)
            return rows[: max(1, int(limit or 8))]

    def query_by_public_ids(
        self,
        *,
        principal_id,
        query_text: str,
        thread_id: str = "",
        session_id: str = "",
        active_workspace_id: str = "",
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        with self.session_scope() as session:
            thread_row = ThreadRepository(session).get_by_thread_id(thread_id) if thread_id else None
            session_row = SessionRepository(session).get_by_session_id(session_id) if session_id else None
            workspace_row = WorkspaceRepository(session).get_by_workspace_id(active_workspace_id) if active_workspace_id else None
            thread_row_id = getattr(thread_row, "id", None)
            session_row_id = getattr(session_row, "id", None)
            workspace_row_id = getattr(workspace_row, "id", None)
        return self.query(
            principal_id=principal_id,
            query_text=query_text,
            thread_id=thread_row_id,
            session_id=session_row_id,
            active_workspace_id=workspace_row_id,
            limit=limit,
        )
