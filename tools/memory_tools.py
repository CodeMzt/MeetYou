"""
High-level memory tools for the main assistant.
"""

from __future__ import annotations

import json
import re
from typing import Any

from core.tool_runtime.models import ToolCallResult, ToolErrorCategory, ToolSourceType
from tools.object_operations import build_object_operation_payload
from tools.system_tools import request_user_confirmation

_REMEMBER_CATEGORY_PREFIXES = {
    "profile": "Durable user profile fact",
    "preference": "Durable user preference",
    "relationship": "Durable relationship fact",
    "project": "Ongoing project state",
    "commitment": "User commitment to remember",
    "fact": "Durable memory candidate",
}

_REMEMBER_CATEGORY_DEFAULT_IMPORTANCE = {
    "profile": 0.76,
    "preference": 0.72,
    "relationship": 0.74,
    "project": 0.78,
    "commitment": 0.82,
    "fact": 0.68,
}

_MEMORY_ID_RE = re.compile(r"id=([A-Za-z0-9_\-]+)")


def _clamp_importance(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_category(category: str) -> str:
    normalized = str(category or "").strip().lower()
    return normalized if normalized in _REMEMBER_CATEGORY_PREFIXES else "fact"


def _memory_candidate_text(category: str, content: str) -> str:
    prefix = _REMEMBER_CATEGORY_PREFIXES[category]
    return f"{prefix}: {content.strip()}"


def _remember_tags(category: str) -> list[str]:
    return ["remember_knowledge", f"remember_category:{category}"]


def _compact_profile_entry(entry: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "fact_key": str(entry.get("fact_key") or "").strip(),
        "fact_value": str(entry.get("fact_value") or "").strip(),
        "content": str(entry.get("content") or "").strip(),
        "score": entry.get("score"),
    }
    return {key: value for key, value in payload.items() if value not in ("", None)}


def _compact_fact_entry(entry: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "fact_key": str(entry.get("fact_key") or "").strip(),
        "fact_value": str(entry.get("fact_value") or "").strip(),
        "content": str(entry.get("content") or "").strip(),
        "score": entry.get("score"),
    }
    return {key: value for key, value in payload.items() if value not in ("", None)}


def _compact_event_entry(entry: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "content": str(entry.get("content") or "").strip(),
        "created_at": str(entry.get("created_at") or "").strip(),
        "score": entry.get("score"),
    }
    return {key: value for key, value in payload.items() if value not in ("", None)}


def _memory_object(record: dict[str, Any], memory) -> dict[str, Any]:
    category = ""
    category_getter = getattr(memory, "_remember_category", None)
    if callable(category_getter):
        category = str(category_getter(record) or "").strip().lower()
    content = str(record.get("content") or "").strip()
    return {
        "object_type": "memory",
        "object_id": str(record.get("id") or "").strip(),
        "record_id": str(record.get("id") or "").strip(),
        "memory_type": str(record.get("type") or "").strip(),
        "status": str(record.get("status") or "active").strip(),
        "category": category,
        "preview": content[:120],
        "content": content,
        "fact_key": str(record.get("fact_key") or "").strip(),
        "fact_value": str(record.get("fact_value") or "").strip(),
        "created_at": str(record.get("created_at") or "").strip(),
        "updated_at": str(record.get("last_updated_at") or "").strip(),
    }


class MemoryTools:
    def __init__(self, memory):
        self._memory = memory

    def _iter_user_memories(self, source, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        user_id = self._memory._resolve_user_id(source)
        records = []
        for record in self._memory._store.get("records", []):
            if record.get("type") not in {"episode", "fact", "profile"}:
                continue
            if record.get("scope", {}).get("user_id") not in {user_id, "global"}:
                continue
            if not include_inactive and str(record.get("status") or "active") != "active":
                continue
            records.append(record)
        return records

    def _memory_match_score(self, record: dict[str, Any], needle: str) -> int:
        lowered = str(needle or "").strip().lower()
        if not lowered:
            return 0
        values = [
            str(record.get("id") or "").strip(),
            str(record.get("content") or "").strip(),
            str(record.get("fact_key") or "").strip(),
            str(record.get("fact_value") or "").strip(),
        ]
        best = 0
        for value in values:
            current = value.lower()
            if not current:
                continue
            if current == lowered:
                best = max(best, 100)
            elif lowered in current:
                best = max(best, 70)
        return best

    def _find_memory_targets(
        self,
        *,
        memory_id: str = "",
        query: str = "",
        source=None,
        include_inactive: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
        pool = self._iter_user_memories(source, include_inactive=include_inactive)
        normalized_id = str(memory_id or "").strip()
        if normalized_id:
            exact = [record for record in pool if str(record.get("id") or "").strip() == normalized_id]
            return exact, [_memory_object(record, self._memory) for record in exact[:5]], True
        needle = str(query or "").strip()
        if not needle:
            return [], [], False
        exact_matches = [
            record
            for record in pool
            if needle.lower()
            in {
                str(record.get("id") or "").strip().lower(),
                str(record.get("content") or "").strip().lower(),
            }
        ]
        if len(exact_matches) == 1:
            return exact_matches, [_memory_object(exact_matches[0], self._memory)], True
        matched = [record for record in pool if self._memory_match_score(record, needle) > 0]
        matched.sort(key=lambda record: str(record.get("last_updated_at") or ""), reverse=True)
        return matched, [_memory_object(record, self._memory) for record in matched[:5]], False

    async def _confirm_memory_operation(
        self,
        *,
        action: str,
        memory_count: int,
        candidates: list[dict[str, Any]],
        session_id: str,
        source=None,
    ) -> bool:
        action_label = {
            "delete": "删除",
            "invalidate": "失效",
            "forget": "忘记",
        }.get(action, action)
        preview = "、".join(str(item.get("preview") or item.get("object_id") or "") for item in candidates[:3])
        return await request_user_confirmation(
            f"即将{action_label}{memory_count}条记忆：{preview}",
            session_id=session_id,
            source=source,
            timeout_seconds=30,
        )

    async def remember_knowledge(
        self,
        content: str,
        category: str = "fact",
        importance: float | None = None,
        session_id: str = "",
        source=None,
    ) -> str | ToolCallResult:
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return ToolCallResult.failure(
                tool_name="remember_knowledge",
                source=ToolSourceType.BUILTIN,
                action_risk="write",
                code="memory_content_required",
                category=ToolErrorCategory.VALIDATION,
                message="remember_knowledge requires non-empty content.",
            )

        normalized_category = _normalize_category(category)
        importance_value = (
            _REMEMBER_CATEGORY_DEFAULT_IMPORTANCE[normalized_category]
            if importance is None
            else _clamp_importance(float(importance))
        )
        memory_text = _memory_candidate_text(normalized_category, normalized_content)

        try:
            save_result = await self._memory.save_memory(
                memory_text=memory_text,
                text_emotion_intensity=importance_value,
                session_id=session_id,
                source=source,
                tags=_remember_tags(normalized_category),
            )
        except Exception as exc:
            return ToolCallResult.failure(
                tool_name="remember_knowledge",
                source=ToolSourceType.BUILTIN,
                action_risk="write",
                code="memory_save_failed",
                category=ToolErrorCategory.EXECUTION,
                message="remember_knowledge failed.",
                details={"exception_type": type(exc).__name__, "exception_message": str(exc)},
            )
        matched_id = ""
        match = _MEMORY_ID_RE.search(str(save_result or ""))
        if match:
            matched_id = match.group(1)
        objects = []
        if matched_id:
            matched = [record for record in self._iter_user_memories(source, include_inactive=True) if str(record.get("id") or "") == matched_id]
            if matched:
                objects = [_memory_object(matched[0], self._memory)]
        payload = build_object_operation_payload(
            action="create",
            object_type="memory",
            status="success",
            objects=objects,
            summary="已保存记忆。",
            next_action_hint="如需纠错，可继续使用 manage_memories 的 detail、edit、invalidate 或 delete。",
            extra={
                "saved": True,
                "category": normalized_category,
                "importance": importance_value,
                "memory_text": memory_text,
                "result": save_result,
                "usage_hint": (
                    "Use this for durable user facts, preferences, ongoing project state, "
                    "or commitments worth remembering later."
                ),
            },
        )
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def search_memory(
        self,
        query: str,
        session_id: str = "",
        source=None,
    ) -> str | ToolCallResult:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return ToolCallResult.failure(
                tool_name="search_memory",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="memory_query_required",
                category=ToolErrorCategory.VALIDATION,
                message="search_memory requires a non-empty query.",
            )

        try:
            raw = await self._memory.recall_memory_structured(
                normalized_query,
                session_id=session_id,
                source=source,
                reinforce=False,
            )
            payload = json.loads(raw)
        except Exception as exc:
            return ToolCallResult.failure(
                tool_name="search_memory",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="memory_search_failed",
                category=ToolErrorCategory.EXECUTION,
                message="search_memory failed.",
                details={"exception_type": type(exc).__name__, "exception_message": str(exc)},
            )

        profile = [
            _compact_profile_entry(item)
            for item in payload.get("profile", [])
            if isinstance(item, dict)
        ]
        facts = [
            _compact_fact_entry(item)
            for item in payload.get("facts", [])
            if isinstance(item, dict)
        ]
        recent_events = [
            _compact_event_entry(item)
            for item in payload.get("recent_events", [])
            if isinstance(item, dict)
        ]

        return json.dumps(
            {
                "query": normalized_query,
                "found": bool(profile or facts or recent_events),
                "usage_hint": (
                    "Use only details that are explicitly supported by memory. "
                    "If the current user message conflicts with memory, trust the current user message."
                ),
                "profile": profile,
                "facts": facts,
                "recent_events": recent_events,
            },
            ensure_ascii=False,
            indent=2,
        )

    async def manage_memories(
        self,
        action: str,
        memory_id: str = "",
        memory_ids: list[str] | None = None,
        query: str = "",
        content: str = "",
        limit: int = 8,
        session_id: str = "",
        source=None,
    ) -> str | ToolCallResult:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"list", "detail", "edit", "delete", "invalidate", "forget"}:
            return ToolCallResult.failure(
                tool_name="manage_memories",
                source=ToolSourceType.BUILTIN,
                action_risk="write",
                code="memory_action_invalid",
                category=ToolErrorCategory.VALIDATION,
                message="manage_memories action must be one of list, detail, edit, delete, invalidate, forget.",
                details={"action": normalized_action},
            )
        try:
            safe_limit = max(1, min(int(limit), 20))
        except (TypeError, ValueError):
            safe_limit = 8

        if normalized_action == "list":
            matched = self._iter_user_memories(source, include_inactive=True)
            query_text = str(query or "").strip().lower()
            if query_text:
                matched = [record for record in matched if self._memory_match_score(record, query_text) > 0]
            matched.sort(key=lambda record: str(record.get("last_updated_at") or ""), reverse=True)
            objects = [_memory_object(record, self._memory) for record in matched[:safe_limit]]
            payload = build_object_operation_payload(
                action="list",
                object_type="memory",
                status="success",
                objects=objects,
                summary=f"已返回 {len(objects)} 条记忆。",
                filters_applied={"limit": safe_limit, "query": query_text},
                next_action_hint="可继续使用 detail 查看详情，或用 edit / invalidate / delete 管理指定记忆。",
                extra={"memories": objects, "memory_count": len(objects)},
            )
            return json.dumps(payload, ensure_ascii=False, indent=2)

        normalized_memory_ids = [str(item).strip() for item in (memory_ids or []) if str(item).strip()]
        if normalized_memory_ids:
            matched = [
                record
                for record in self._iter_user_memories(source, include_inactive=True)
                if str(record.get("id") or "").strip() in set(normalized_memory_ids)
            ]
            candidates = [_memory_object(record, self._memory) for record in matched[:5]]
            exact = True
        else:
            matched, candidates, exact = self._find_memory_targets(
                memory_id=memory_id,
                query=query,
                source=source,
                include_inactive=True,
            )

        if not matched:
            payload = build_object_operation_payload(
                action=normalized_action,
                object_type="memory",
                status="not_found",
                objects=[],
                summary="未找到匹配的记忆。",
                candidates=candidates,
                error={"code": "memory_not_found", "message": "未找到匹配的记忆。", "details": {"memory_id": memory_id, "query": query}},
                next_action_hint="请先使用 list 查看可管理的记忆，或提供更明确的 memory_id。",
                extra={"memories": [], "memory_count": 0},
            )
            return json.dumps(payload, ensure_ascii=False, indent=2)

        if len(matched) > 1 and not exact:
            payload = build_object_operation_payload(
                action=normalized_action,
                object_type="memory",
                status="ambiguous",
                objects=[],
                summary="存在多条相似记忆，暂不执行对象操作。",
                candidates=candidates,
                error={"code": "memory_ambiguous", "message": "存在多条相似记忆，暂不执行对象操作。", "details": {"candidate_count": len(matched)}},
                next_action_hint="请改用 memory_id 指定目标记忆。",
                extra={"memories": [], "memory_count": 0},
            )
            return json.dumps(payload, ensure_ascii=False, indent=2)

        if normalized_action == "detail":
            objects = [_memory_object(matched[0], self._memory)]
            payload = build_object_operation_payload(
                action=normalized_action,
                object_type="memory",
                status="success",
                objects=objects,
                summary=f"已定位记忆 {objects[0]['object_id']}。",
                next_action_hint="如需修改，可继续使用 edit、invalidate、forget 或 delete。",
                extra={"memories": objects, "memory_count": len(objects)},
            )
            return json.dumps(payload, ensure_ascii=False, indent=2)

        if normalized_action == "edit":
            normalized_content = str(content or "").strip()
            if not normalized_content:
                return ToolCallResult.failure(
                    tool_name="manage_memories",
                    source=ToolSourceType.BUILTIN,
                    action_risk="write",
                    code="memory_content_required",
                    category=ToolErrorCategory.VALIDATION,
                    message="manage_memories edit requires non-empty content.",
                )
            record = matched[0]
            record["content"] = normalized_content
            record["canonical_text"] = self._memory._canonicalize(normalized_content)
            embedding = await self._memory._get_embedding(normalized_content)
            if embedding:
                record["embedding"] = embedding
                record["embedding_model"] = self._memory._embedding_model
            record["last_updated_at"] = getattr(self._memory, "_store", {}).get("metadata", {}).get("updated_at") or ""
            if not record["last_updated_at"]:
                from tools.memory_layers import dt_to_iso, utcnow

                record["last_updated_at"] = dt_to_iso(utcnow())
            await self._memory.save_memory_graph()
            objects = [_memory_object(record, self._memory)]
            payload = build_object_operation_payload(
                action=normalized_action,
                object_type="memory",
                status="success",
                objects=objects,
                summary="已更新记忆内容。",
                next_action_hint="可继续使用 detail 检查更新结果。",
                extra={"memories": objects, "memory_count": len(objects)},
            )
            return json.dumps(payload, ensure_ascii=False, indent=2)

        confirmed = await self._confirm_memory_operation(
            action=normalized_action,
            memory_count=len(matched),
            candidates=candidates,
            session_id=session_id,
            source=source,
        )
        if not confirmed:
            payload = build_object_operation_payload(
                action=normalized_action,
                object_type="memory",
                status="cancelled",
                objects=[],
                summary="用户未确认记忆对象操作，未执行变更。",
                candidates=candidates,
                next_action_hint="如需继续，请重新发起操作并在确认框中同意。",
                extra={"memories": [], "memory_count": 0},
            )
            return json.dumps(payload, ensure_ascii=False, indent=2)

        current_status = "deleted" if normalized_action == "delete" else "invalidated"
        for record in matched:
            record["status"] = current_status
            from tools.memory_layers import dt_to_iso, utcnow

            record["last_updated_at"] = dt_to_iso(utcnow())
        await self._memory.save_memory_graph()
        objects = [_memory_object(record, self._memory) for record in matched]
        payload = build_object_operation_payload(
            action=normalized_action,
            object_type="memory",
            status="success",
            objects=objects,
            summary="已删除记忆。" if normalized_action == "delete" else "已使记忆失效。",
            next_action_hint="后续检索将不再返回这些记忆。",
            extra={"memories": objects, "memory_count": len(objects)},
        )
        return json.dumps(payload, ensure_ascii=False, indent=2)
