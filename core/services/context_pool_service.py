from __future__ import annotations

import json
import re
from uuid import uuid4
from typing import Any

from core.db.repositories import (
    ClientRepository,
    ContextPoolRepository,
    SessionRepository,
    ThreadRepository,
    WorkspaceRepository,
)
from core.services.base import ServiceBase


_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
DEFAULT_MAX_ACTIVE_ITEMS_PER_PRINCIPAL = 500
MAX_CONTEXT_POOL_CONTENT_CHARS = 6000
MIN_NON_MESSAGE_CONTEXT_CHARS = 32


class ContextPoolService(ServiceBase):
    def __init__(self, session_factory, *, max_active_items_per_principal: int = DEFAULT_MAX_ACTIVE_ITEMS_PER_PRINCIPAL):
        super().__init__(session_factory)
        self.max_active_items_per_principal = max(1, int(max_active_items_per_principal or DEFAULT_MAX_ACTIVE_ITEMS_PER_PRINCIPAL))

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

    @staticmethod
    def _bounded_text(value: Any, *, limit: int = MAX_CONTEXT_POOL_CONTENT_CHARS) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 20].rstrip() + "\n...[truncated]"

    @staticmethod
    def _json_text(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value or "")

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        try:
            return json.loads(cls._json_text(value))
        except Exception:
            return str(value or "")

    @classmethod
    def _result_text(cls, result: Any) -> str:
        content = getattr(result, "content", None)
        text = str(getattr(content, "text", "") or "").strip()
        if text:
            return cls._bounded_text(text)
        if isinstance(result, dict):
            for key in ("summary", "message", "text", "stdout", "stderr"):
                text = str(result.get(key) or "").strip()
                if text:
                    return cls._bounded_text(text)
            return cls._bounded_text(cls._json_text(result))
        data = getattr(content, "data", None)
        if data not in (None, "", [], {}):
            return cls._bounded_text(cls._json_text(data))
        return cls._bounded_text(str(result or ""))

    def add_item(
        self,
        *,
        principal_id,
        content: str,
        thread_id=None,
        session_id=None,
        message_id=None,
        source_client_id=None,
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
        text = self._bounded_text(text)
        with self.session_scope() as session:
            repo = ContextPoolRepository(session)
            row = repo.create(
                context_id=f"ctx_{uuid4().hex}",
                principal_id=principal_id,
                thread_id=thread_id,
                session_id=session_id,
                message_id=message_id,
                source_client_id=source_client_id,
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
            repo.prune_for_principal(
                principal_id=principal_id,
                max_items=self.max_active_items_per_principal,
            )
            return row

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

    def _resolve_context_rows(self, event_context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = dict(event_context or {})
        source = context.get("source")
        if isinstance(source, dict):
            source_metadata = source.get("metadata", {})
        else:
            source_metadata = getattr(source, "metadata", {}) if source is not None else {}
        if not isinstance(source_metadata, dict):
            source_metadata = {}
        public_thread_id = str(context.get("thread_id") or "").strip()
        public_session_id = str(context.get("session_id") or "").strip()
        public_workspace_id = str(context.get("active_workspace_id") or context.get("workspace_id") or "").strip()
        public_client_id = str(context.get("client_id") or source_metadata.get("client_id") or "").strip()
        with self.session_scope() as session:
            thread_row = ThreadRepository(session).get_by_thread_id(public_thread_id) if public_thread_id else None
            session_row = SessionRepository(session).get_by_session_id(public_session_id) if public_session_id else None
            workspace_row = WorkspaceRepository(session).get_by_workspace_id(public_workspace_id) if public_workspace_id else None
            client_row = ClientRepository(session).get_by_client_id(public_client_id) if public_client_id else None
            return {
                "thread_id": getattr(thread_row, "id", None),
                "session_id": getattr(session_row, "id", None),
                "active_workspace_id": getattr(workspace_row, "id", None),
                "home_workspace_id": getattr(thread_row, "home_workspace_id", None),
                "source_client_id": getattr(client_row, "id", None),
                "public_thread_id": public_thread_id,
                "public_session_id": public_session_id,
                "public_workspace_id": public_workspace_id,
                "public_client_id": public_client_id,
            }

    def record_tool_result_by_context(
        self,
        *,
        principal_id,
        tool_name: str,
        result: Any,
        tool_args: dict | None = None,
        event_context: dict[str, Any] | None = None,
        metadata: dict | None = None,
    ):
        if not getattr(result, "ok", False):
            return None
        content = self._result_text(result)
        action_risk = str(getattr(result, "action_risk", "") or "read")
        if len(content) < MIN_NON_MESSAGE_CONTEXT_CHARS and action_risk not in {"local_write", "external_write", "destructive"}:
            return None
        tool_name = str(tool_name or getattr(result, "tool_name", "") or "").strip()
        if not tool_name:
            return None
        rows = self._resolve_context_rows(event_context)
        importance = 0.48
        if action_risk in {"local_write", "external_write", "destructive"}:
            importance = 0.64
        return self.add_item(
            principal_id=principal_id,
            thread_id=rows["thread_id"],
            session_id=rows["session_id"],
            source_client_id=rows["source_client_id"],
            home_workspace_id=rows["home_workspace_id"],
            active_workspace_id=rows["active_workspace_id"],
            item_type="tool_result",
            role="tool",
            content=f"Tool {tool_name} result:\n{content}",
            importance=importance,
            workspace_tags=self._workspace_tags(rows["public_workspace_id"]),
            metadata={
                **dict(metadata or {}),
                "tool_name": tool_name,
                "action_risk": action_risk,
                "source": str(getattr(result, "source", "") or ""),
                "tool_args": self._json_value(dict(tool_args or {})),
                "thread_id": rows["public_thread_id"],
                "session_id": rows["public_session_id"],
                "client_id": rows["public_client_id"],
                "active_workspace_id": rows["public_workspace_id"],
            },
        )

    def record_client_tool_operation_result(
        self,
        *,
        principal_id,
        client,
        call,
        operation,
        result: dict[str, Any],
        thread=None,
        workspace=None,
        metadata: dict | None = None,
    ):
        content = self._result_text(result)
        if not content:
            return None
        public_workspace_id = str(getattr(workspace, "workspace_id", "") or "")
        public_thread_id = str(getattr(thread, "thread_id", "") or "")
        return self.add_item(
            principal_id=principal_id,
            thread_id=getattr(thread, "id", None),
            session_id=getattr(operation, "requested_by_session_id", None),
            source_client_id=getattr(client, "id", None) or getattr(call, "target_client_id", None),
            home_workspace_id=getattr(thread, "home_workspace_id", None),
            active_workspace_id=getattr(operation, "workspace_id", None),
            item_type="client_tool_result",
            role="tool",
            content=f"Client {getattr(client, 'client_id', '')} tool operation result:\n{content}",
            importance=0.58,
            workspace_tags=self._workspace_tags(public_workspace_id),
            metadata={
                **dict(metadata or {}),
                "client_id": str(getattr(client, "client_id", "") or ""),
                "call_id": str(getattr(call, "call_id", "") or ""),
                "operation_id": str(getattr(operation, "operation_id", "") or ""),
                "operation_type": str(getattr(operation, "operation_type", "") or ""),
                "thread_id": public_thread_id,
                "active_workspace_id": public_workspace_id,
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
