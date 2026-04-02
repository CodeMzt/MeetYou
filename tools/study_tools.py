"""
Study planning and learning helper tools.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from tools.document_tools import DocumentTools, _normalize_text, _trim_text


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_materials(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [str(item) for item in (value or []) if str(item).strip()]


class StudyTools:
    def __init__(self, document_tools: DocumentTools):
        self._document_tools = document_tools
        self._progress_path = Path("user/study_progress.json")

    def _load_progress(self) -> dict[str, Any]:
        if not self._progress_path.exists():
            return {"topics": []}
        try:
            return json.loads(self._progress_path.read_text(encoding="utf-8"))
        except Exception:
            return {"topics": []}

    def _save_progress(self, payload: dict[str, Any]) -> None:
        self._progress_path.parent.mkdir(parents=True, exist_ok=True)
        self._progress_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _collect_material_text(self, materials: list[str], *, goal: str) -> dict[str, Any]:
        raw = await self._document_tools.read_local_documents(materials, goal=goal, chunking="auto")
        return json.loads(raw)

    def _extract_points_from_text(self, text: str, *, limit: int = 12) -> list[str]:
        candidates = []
        for line in re.split(r"[\n\r]+|(?<=[.!?。！？])\s+", str(text or "")):
            normalized = line.strip(" -")
            if len(normalized) < 18:
                continue
            if any(token in normalized.lower() for token in (" is ", " are ", " means ", " refers to ", " because ", "important", "key", "核心", "关键", "定义", "表示", "意味着")):
                candidates.append(normalized)
        if not candidates:
            for line in str(text or "").splitlines():
                normalized = line.strip(" -")
                if len(normalized) >= 18:
                    candidates.append(normalized)
        deduped: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            compact = _normalize_text(item)
            if compact.lower() in seen:
                continue
            seen.add(compact.lower())
            deduped.append(compact)
            if len(deduped) >= limit:
                break
        return deduped

    def _parse_deadline_days(self, deadline: str) -> int | None:
        normalized = str(deadline or "").strip()
        if not normalized:
            return None
        for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
            try:
                target = datetime.strptime(normalized, pattern)
                now = datetime.now()
                return max((target.date() - now.date()).days, 0)
            except ValueError:
                continue
        return None

    async def build_study_plan(
        self,
        topic: str,
        deadline: str = "",
        materials: list[str] | str | None = None,
        cadence: str = "daily",
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> str:
        del session_id, source, route_context, activity_callback
        normalized_topic = _normalize_text(topic)
        material_list = _safe_materials(materials)
        material_payload = await self._collect_material_text(material_list, goal=f"study plan for {normalized_topic}") if material_list else {"documents": []}
        days_remaining = self._parse_deadline_days(deadline)
        if days_remaining is None:
            days_remaining = 14

        session_count = max(3, min(days_remaining or 14, 21))
        review_frequency = max(1, math.ceil(session_count / 4))
        plan_steps = [
            {"phase": "foundation", "sessions": max(1, math.ceil(session_count * 0.35)), "focus": "Build a clear mental model and identify weak spots."},
            {"phase": "practice", "sessions": max(1, math.ceil(session_count * 0.45)), "focus": "Solve exercises, reproduce examples, and test recall."},
            {"phase": "review", "sessions": max(1, session_count - math.ceil(session_count * 0.35) - math.ceil(session_count * 0.45)), "focus": "Run spaced review, timed recall, and summary refinement."},
        ]
        payload = {
            "tool": "build_study_plan",
            "topic": normalized_topic,
            "deadline": _normalize_text(deadline),
            "days_remaining": days_remaining,
            "cadence": _normalize_text(cadence) or "daily",
            "material_count": len(material_payload.get("documents", [])),
            "plan": plan_steps,
            "review_frequency_days": review_frequency,
            "materials": material_payload.get("documents", []),
            "answer_style": "Turn this scaffold into a practical study plan with concrete milestones, practice, and review.",
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def extract_learning_points(
        self,
        materials: list[str] | str,
        goal: str = "",
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> str:
        del session_id, source, route_context, activity_callback
        material_list = _safe_materials(materials)
        material_payload = await self._collect_material_text(material_list, goal=goal or "extract learning points")
        points: list[dict[str, Any]] = []
        for index, document in enumerate(material_payload.get("documents", []), start=1):
            if document.get("status") != "ok":
                continue
            for point in self._extract_points_from_text(document.get("content_excerpt") or "", limit=6):
                points.append(
                    {
                        "source_id": index,
                        "source_name": document.get("name"),
                        "point": point,
                    }
                )
        payload = {
            "tool": "extract_learning_points",
            "goal": _normalize_text(goal),
            "materials": material_payload.get("documents", []),
            "learning_points": points[:24],
            "answer_style": "Use these points as the grounded basis for explanations, summaries, or next-step study guidance.",
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def quiz_me(
        self,
        topic: str = "",
        materials: list[str] | str | None = None,
        question_count: int = 5,
        difficulty: str = "medium",
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> str:
        del session_id, source, route_context, activity_callback
        points_payload = await self.extract_learning_points(materials or [], goal=f"quiz for {topic}")
        points = json.loads(points_payload).get("learning_points", [])
        questions: list[dict[str, Any]] = []
        for index, item in enumerate(points[: max(1, int(question_count or 5))], start=1):
            point = str(item.get("point") or "")
            prompt = _trim_text(point, 180)
            questions.append(
                {
                    "index": index,
                    "question": f"Explain or recall this idea in your own words: {prompt}",
                    "answer_hint": prompt,
                    "difficulty": _normalize_text(difficulty) or "medium",
                    "source_name": item.get("source_name"),
                }
            )
        payload = {
            "tool": "quiz_me",
            "topic": _normalize_text(topic),
            "questions": questions,
            "answer_style": "Ask the questions directly. Keep the answer hints hidden unless the user asks for them.",
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def generate_flashcards(
        self,
        materials: list[str] | str,
        limit: int = 10,
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> str:
        del session_id, source, route_context, activity_callback
        points_payload = await self.extract_learning_points(materials, goal="flashcards")
        points = json.loads(points_payload).get("learning_points", [])
        cards = []
        for index, item in enumerate(points[: max(1, int(limit or 10))], start=1):
            point = str(item.get("point") or "")
            cards.append(
                {
                    "index": index,
                    "front": f"What is the key idea behind: {point[:72]}?",
                    "back": point,
                    "source_name": item.get("source_name"),
                }
            )
        payload = {
            "tool": "generate_flashcards",
            "flashcards": cards,
            "answer_style": "Present the cards cleanly and keep the source references when useful.",
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def track_mastery(
        self,
        action: str = "update",
        topic: str = "",
        score: float | int | None = None,
        notes: str = "",
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        activity_callback=None,
    ) -> str:
        del session_id, source, route_context, activity_callback
        normalized_action = str(action or "update").strip().lower()
        progress = self._load_progress()

        if normalized_action == "list":
            return json.dumps(
                {
                    "tool": "track_mastery",
                    "action": "list",
                    "topics": progress.get("topics", []),
                },
                ensure_ascii=False,
                indent=2,
            )

        normalized_topic = _normalize_text(topic)
        if not normalized_topic:
            return json.dumps(
                {
                    "tool": "track_mastery",
                    "status": "missing_topic",
                    "action": normalized_action,
                },
                ensure_ascii=False,
                indent=2,
            )

        topic_entry = None
        for entry in progress.setdefault("topics", []):
            if _normalize_text(entry.get("topic")) == normalized_topic:
                topic_entry = entry
                break

        if topic_entry is None:
            topic_entry = {
                "topic_id": f"topic_{uuid4().hex[:10]}",
                "topic": normalized_topic,
                "score": 0.0,
                "notes": "",
                "updated_at": _utcnow_iso(),
            }
            progress["topics"].append(topic_entry)

        if normalized_action in {"update", "record"}:
            if score is not None:
                try:
                    topic_entry["score"] = max(0.0, min(float(score), 1.0))
                except (TypeError, ValueError):
                    pass
            if notes:
                topic_entry["notes"] = _trim_text(notes, 1000)
            topic_entry["updated_at"] = _utcnow_iso()
            self._save_progress(progress)
            status = "updated"
        elif normalized_action == "get":
            status = "loaded"
        else:
            return json.dumps(
                {
                    "tool": "track_mastery",
                    "status": "invalid_action",
                    "allowed_actions": ["update", "record", "get", "list"],
                },
                ensure_ascii=False,
                indent=2,
            )

        return json.dumps(
            {
                "tool": "track_mastery",
                "action": normalized_action,
                "status": status,
                "topic": topic_entry,
            },
            ensure_ascii=False,
            indent=2,
        )
