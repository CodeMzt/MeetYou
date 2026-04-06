"""
Lightweight native tools for summarization and structure-first transformations.
"""

from __future__ import annotations

import json
import re
from typing import Any

from tools.document_tools import _normalize_text, _trim_text

_SENTENCE_RE = re.compile(r"(?<=[。！？.!?])\s+|\n+")
_ACTION_HINT_RE = re.compile(
    r"(?i)\b(todo|action item|follow[- ]?up|need to|should|must|assign|owner|deadline|next step)\b|待办|跟进|负责人|截止|下一步"
)
_DUE_HINT_RE = re.compile(r"(?i)\b(today|tomorrow|next week|by [^,.;\n]+)\b|今天|明天|本周|下周|截止[^\n，。]*")


def _split_sentences(text: str) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    parts = [part.strip(" -•\t") for part in _SENTENCE_RE.split(normalized) if part.strip(" -•\t")]
    return [part for part in parts if part]


def _keyword_score(sentence: str, focus: str) -> int:
    normalized_focus = _normalize_text(focus).lower()
    if not normalized_focus:
        return 0
    score = 0
    for token in re.split(r"[\s,，。;；]+", normalized_focus):
        if token and token in sentence.lower():
            score += 2
    return score


def _best_sentences(text: str, *, focus: str = "", limit: int = 5) -> list[str]:
    candidates = _split_sentences(text)
    scored = []
    for index, sentence in enumerate(candidates):
        length_score = min(len(sentence), 220) / 55
        scored.append((_keyword_score(sentence, focus) + length_score, index, sentence))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = [sentence for _, _, sentence in scored[: max(1, limit)]]
    return selected or candidates[:1]


def _outline_from_text(text: str, *, focus: str = "", max_sections: int = 4) -> list[dict[str, Any]]:
    sentences = _best_sentences(text, focus=focus, limit=max_sections * 2)
    sections: list[dict[str, Any]] = []
    for index in range(0, len(sentences), 2):
        chunk = sentences[index : index + 2]
        if not chunk:
            continue
        sections.append(
            {
                "title": f"Section {len(sections) + 1}",
                "bullets": [_trim_text(sentence, 220) for sentence in chunk],
            }
        )
        if len(sections) >= max_sections:
            break
    return sections


class LightweightTools:
    async def summarize_text(
        self,
        text: str,
        style: str = "brief",
        focus: str = "",
        max_points: int = 5,
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> str:
        del session_id, source, route_context, activity_callback
        normalized_style = _normalize_text(style).lower() or "brief"
        points = _best_sentences(text, focus=focus, limit=max(1, min(int(max_points or 5), 8)))
        summary = " ".join(points[:2]).strip()
        payload: dict[str, Any] = {
            "tool": "summarize_text",
            "style": normalized_style,
            "focus": _normalize_text(focus),
            "summary": _trim_text(summary, 500),
            "highlights": [_trim_text(item, 220) for item in points],
        }
        if normalized_style == "outline":
            payload["sections"] = _outline_from_text(text, focus=focus, max_sections=max(1, min(len(points), 4)))
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def organize_notes(
        self,
        text: str,
        structure: str = "outline",
        title: str = "",
        focus: str = "",
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> str:
        del session_id, source, route_context, activity_callback
        normalized_structure = _normalize_text(structure).lower() or "outline"
        sections = _outline_from_text(text, focus=focus, max_sections=4)
        payload = {
            "tool": "organize_notes",
            "title": _normalize_text(title) or "Structured Notes",
            "structure": normalized_structure,
            "focus": _normalize_text(focus),
            "sections": sections,
        }
        payload["rendered_markdown"] = "\n\n".join(
            [f"## {section['title']}\n" + "\n".join(f"- {bullet}" for bullet in section["bullets"]) for section in sections]
        ).strip()
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def extract_action_items(
        self,
        text: str,
        focus: str = "",
        max_items: int = 8,
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> str:
        del session_id, source, route_context, activity_callback
        candidates = _split_sentences(text)
        action_items: list[dict[str, Any]] = []
        for sentence in candidates:
            if not _ACTION_HINT_RE.search(sentence):
                continue
            action_items.append(
                {
                    "task": _trim_text(sentence, 240),
                    "due_hint": (_DUE_HINT_RE.search(sentence).group(0) if _DUE_HINT_RE.search(sentence) else ""),
                    "owner_hint": "unknown",
                }
            )
            if len(action_items) >= max(1, min(int(max_items or 8), 12)):
                break
        if not action_items:
            for sentence in _best_sentences(text, focus=focus, limit=max(1, min(int(max_items or 8), 5))):
                action_items.append({"task": _trim_text(sentence, 240), "due_hint": "", "owner_hint": "unknown"})
        payload = {
            "tool": "extract_action_items",
            "focus": _normalize_text(focus),
            "item_count": len(action_items),
            "action_items": action_items,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
