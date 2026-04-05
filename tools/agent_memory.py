"""
High-level memory tools for the main assistant.
"""

from __future__ import annotations

import json
from typing import Any

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


class AgentMemoryTools:
    def __init__(self, memory):
        self._memory = memory

    async def remember_knowledge(
        self,
        content: str,
        category: str = "fact",
        importance: float | None = None,
        session_id: str = "",
        source=None,
    ) -> str:
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return "Error: remember_knowledge requires non-empty content."

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
            return f"Error: remember_knowledge failed: {exc}"

        return json.dumps(
            {
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
            ensure_ascii=False,
            indent=2,
        )

    async def search_memory(
        self,
        query: str,
        session_id: str = "",
        source=None,
    ) -> str:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return "Error: search_memory requires a non-empty query."

        try:
            raw = await self._memory.recall_memory_structured(
                normalized_query,
                session_id=session_id,
                source=source,
                reinforce=False,
            )
            payload = json.loads(raw)
        except Exception as exc:
            return f"Error: search_memory failed: {exc}"

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
