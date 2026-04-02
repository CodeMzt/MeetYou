"""
Deterministic lightweight task management backed by the memory store.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

_VALID_TASK_STATUSES = {"open", "blocked", "done"}
_DEFAULT_LIST_LIMIT = 8
_MAX_LIST_LIMIT = 20
_SPACE_RE = re.compile(r"\s+")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _utcnow_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _normalize_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "").strip())


def _normalize_status(value: Any, *, default: str = "open") -> str:
    normalized = str(value or default).strip().lower() or default
    if normalized not in _VALID_TASK_STATUSES:
        raise ValueError(
            "task_status must be one of: open, blocked, done."
        )
    return normalized


def _slugify(value: str) -> str:
    lowered = re.sub(r"\s+", "-", str(value or "").strip().lower())
    lowered = _SLUG_RE.sub("-", lowered).strip("-")
    return lowered or "task"


def _looks_like_match(record: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystacks = [
        _normalize_text(record.get("task_key")),
        _normalize_text(record.get("content")),
        _normalize_text(record.get("project")),
        _normalize_text(record.get("deadline")),
    ]
    lowered = query.lower()
    return any(lowered in item.lower() for item in haystacks if item)


class TaskManager:
    def __init__(self, memory):
        self._memory = memory

    def _iter_user_tasks(self, user_id: str) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for record in self._memory._store.get("records", []):
            if record.get("type") != "task":
                continue
            if record.get("status") != "active":
                continue
            if record.get("scope", {}).get("user_id") not in {user_id, "global"}:
                continue
            tasks.append(record)
        return tasks

    def _find_task_record(self, user_id: str, task_key: str) -> dict[str, Any] | None:
        normalized_key = _normalize_text(task_key)
        if not normalized_key:
            return None
        for record in self._iter_user_tasks(user_id):
            if _normalize_text(record.get("task_key")) == normalized_key:
                return record
        return None

    def _ensure_unique_task_key(self, user_id: str, preferred_key: str) -> str:
        base = _slugify(preferred_key)
        candidate = base
        index = 2
        while self._find_task_record(user_id, candidate) is not None:
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    def _compact_task(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_key": _normalize_text(record.get("task_key")),
            "summary": _normalize_text(record.get("content")),
            "project": _normalize_text(record.get("project")),
            "task_status": _normalize_text(record.get("task_status")),
            "deadline": _normalize_text(record.get("deadline")),
            "created_at": _normalize_text(record.get("created_at")),
            "updated_at": _normalize_text(record.get("last_updated_at")),
        }

    def _sort_tasks(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        status_rank = {"open": 0, "blocked": 1, "done": 2}

        def sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
            deadline = _normalize_text(record.get("deadline")) or "9999-99-99"
            updated_at = _normalize_text(record.get("last_updated_at")) or ""
            return (
                status_rank.get(_normalize_text(record.get("task_status")), 9),
                deadline,
                -len(updated_at),
                updated_at,
            )

        return sorted(tasks, key=sort_key)

    async def _maybe_embed(self, text: str) -> list[float]:
        try:
            return await self._memory._get_embedding(text)
        except Exception:
            return []

    async def _persist(self, record: dict[str, Any], *, relink: bool = False) -> None:
        if relink and record.get("embedding"):
            try:
                self._memory._link_semantic_edges(record)
            except Exception:
                pass
        await self._memory.save_memory_graph()

    async def _create_task(
        self,
        *,
        user_id: str,
        summary: str,
        task_key: str = "",
        project: str = "",
        task_status: str = "open",
        deadline: str = "",
    ) -> dict[str, Any]:
        normalized_summary = _normalize_text(summary)
        if not normalized_summary:
            raise ValueError("create requires a non-empty summary.")

        status = _normalize_status(task_status or "open")
        task_key_value = self._ensure_unique_task_key(
            user_id,
            task_key or normalized_summary,
        )
        now = _utcnow_iso()
        embedding = await self._maybe_embed(normalized_summary)
        record = {
            "id": f"task_{uuid4().hex[:16]}",
            "type": "task",
            "scope": self._memory._record_scope(user_id, "", "task"),
            "content": normalized_summary,
            "canonical_text": normalized_summary.lower(),
            "embedding": embedding,
            "embedding_model": self._memory._embedding_model,
            "strength": 0.72,
            "importance": 0.7,
            "confidence": 1.0,
            "created_at": now,
            "last_accessed_at": now,
            "last_updated_at": now,
            "access_count": 0,
            "status": "active",
            "tags": [],
            "entity_keys": [],
            "source_record_ids": [],
            "task_key": task_key_value,
            "project": _normalize_text(project),
            "task_status": status,
            "deadline": _normalize_text(deadline) or None,
        }
        self._memory._store["records"].append(record)
        await self._persist(record, relink=True)
        return record

    async def _update_task(
        self,
        *,
        user_id: str,
        task_key: str,
        summary: str = "",
        project: str = "",
        task_status: str = "",
        deadline: str | None = None,
        clear_deadline: bool = False,
    ) -> dict[str, Any]:
        record = self._find_task_record(user_id, task_key)
        if record is None:
            raise ValueError(f"task_key not found: {task_key}")

        changed = False
        normalized_summary = _normalize_text(summary)
        if normalized_summary:
            record["content"] = normalized_summary
            record["canonical_text"] = normalized_summary.lower()
            record["embedding"] = await self._maybe_embed(normalized_summary)
            record["embedding_model"] = self._memory._embedding_model
            changed = True

        normalized_project = _normalize_text(project)
        if project != "":
            record["project"] = normalized_project
            changed = True

        if task_status:
            record["task_status"] = _normalize_status(task_status, default=record.get("task_status") or "open")
            changed = True

        if clear_deadline:
            record["deadline"] = None
            changed = True
        elif deadline is not None:
            record["deadline"] = _normalize_text(deadline) or None
            changed = True

        if not changed:
            raise ValueError("update requires at least one field to change.")

        record["last_updated_at"] = _utcnow_iso()
        await self._persist(record, relink=True)
        return record

    def _filters_payload(
        self,
        *,
        task_status: str = "",
        project: str = "",
        query: str = "",
        limit: int,
    ) -> dict[str, Any]:
        payload = {"limit": limit}
        if task_status:
            payload["task_status"] = task_status
        if project:
            payload["project"] = project
        if query:
            payload["query"] = query
        return payload

    def _next_action_hint(self, action: str, tasks: list[dict[str, Any]]) -> str:
        if action == "create" and tasks:
            return f"Use task_key={tasks[0]['task_key']} to update or complete it later."
        if action == "complete" and tasks:
            return "List active tasks again if you want to review what is still open."
        if not tasks:
            return "No matching tasks were found."
        blocked_count = sum(1 for task in tasks if task.get("task_status") == "blocked")
        if blocked_count:
            return "Review blocked tasks and decide what dependency needs to be cleared."
        return "Use task_key from this list with manage_tasks:update or manage_tasks:complete."

    async def manage_tasks(
        self,
        action: str,
        task_key: str = "",
        summary: str = "",
        project: str = "",
        task_status: str = "",
        deadline: str | None = None,
        query: str = "",
        limit: int = _DEFAULT_LIST_LIMIT,
        session_id: str = "",
        source=None,
    ) -> str:
        del session_id

        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"create", "list", "update", "complete"}:
            return "Error: manage_tasks action must be one of create, list, update, complete."

        try:
            safe_limit = max(1, min(int(limit), _MAX_LIST_LIMIT))
        except (TypeError, ValueError):
            safe_limit = _DEFAULT_LIST_LIMIT

        user_id = self._memory._resolve_user_id(source)

        try:
            if normalized_action == "create":
                record = await self._create_task(
                    user_id=user_id,
                    summary=summary,
                    task_key=task_key,
                    project=project,
                    task_status=task_status or "open",
                    deadline=_normalize_text(deadline),
                )
                tasks = [self._compact_task(record)]
                filters = self._filters_payload(limit=1)
            elif normalized_action == "list":
                query_text = _normalize_text(query)
                project_filter = _normalize_text(project)
                status_filter = str(task_status or "").strip().lower()
                if status_filter and status_filter not in _VALID_TASK_STATUSES and status_filter != "all":
                    raise ValueError("task_status for list must be open, blocked, done, or all.")

                matched: list[dict[str, Any]] = []
                for record in self._iter_user_tasks(user_id):
                    current_status = _normalize_text(record.get("task_status")).lower()
                    if status_filter:
                        if status_filter != "all" and current_status != status_filter:
                            continue
                    elif current_status == "done":
                        continue
                    if project_filter and _normalize_text(record.get("project")).lower() != project_filter.lower():
                        continue
                    if not _looks_like_match(record, query_text):
                        continue
                    matched.append(record)
                tasks = [
                    self._compact_task(record)
                    for record in self._sort_tasks(matched)[:safe_limit]
                ]
                filters = self._filters_payload(
                    task_status=status_filter or "active",
                    project=project_filter,
                    query=query_text,
                    limit=safe_limit,
                )
            elif normalized_action == "update":
                record = await self._update_task(
                    user_id=user_id,
                    task_key=task_key,
                    summary=summary,
                    project=project,
                    task_status=task_status,
                    deadline=deadline,
                    clear_deadline=deadline == "",
                )
                tasks = [self._compact_task(record)]
                filters = self._filters_payload(limit=1)
            else:
                record = await self._update_task(
                    user_id=user_id,
                    task_key=task_key,
                    task_status="done",
                )
                tasks = [self._compact_task(record)]
                filters = self._filters_payload(limit=1)
        except ValueError as exc:
            return f"Error: manage_tasks failed: {exc}"

        payload = {
            "action": normalized_action,
            "tasks": tasks,
            "task_count": len(tasks),
            "filters_applied": filters,
            "next_action_hint": self._next_action_hint(normalized_action, tasks),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
