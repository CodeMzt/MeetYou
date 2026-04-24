"""
Skill registry management for project skills.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_SKILL_FILE_RE = re.compile(
    r"^\[Skill Metadata\]\s*(\{[\s\S]*?\})\s*\[Skill Content\]\s*([\s\S]*)$",
    re.DOTALL,
)
_SKILL_ID_RE = re.compile(r"[^a-z0-9_]+")

_DEFAULT_MODE_SKILL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "normal": {
        "id": "mode:normal",
        "skill_type": "mode",
        "title": "Normal Mode Skill",
        "summary": "通用日常协作范式，优先使用共享基础能力处理轻量任务。",
        "file_name": "mode-normal",
        "applicable_modes": ["normal"],
        "scenarios": ["ordinary conversation", "light planning", "lightweight web lookup"],
        "recommended_tools": [
            "search_knowledge",
            "search_memory",
            "search_web",
            "read_web_page",
            "remember_knowledge",
        ],
    },
    "documents": {
        "id": "mode:documents",
        "skill_type": "mode",
        "title": "Documents Mode Skill",
        "summary": "本地文件与工作区处理范式，强调先读取再修改。",
        "file_name": "mode-documents",
        "applicable_modes": ["documents"],
        "scenarios": ["workspace analysis", "document reading", "document writing"],
        "recommended_tools": [
            "analyze_workspace",
            "read_local_documents",
            "write_local_document",
            "rewrite_local_document",
            "compile_report",
        ],
    },
    "research": {
        "id": "mode:research",
        "skill_type": "mode",
        "title": "Research Mode Skill",
        "summary": "深度研究范式，强调来源可信度、新鲜度与证据结构。",
        "file_name": "mode-research",
        "applicable_modes": ["research"],
        "scenarios": ["source-heavy analysis", "update tracking", "evidence-backed reports"],
        "recommended_tools": [
            "research_topic",
            "inspect_page",
            "track_source_updates",
            "compile_report",
        ],
    },
    "office": {
        "id": "mode:office",
        "skill_type": "mode",
        "title": "Office Mode Skill",
        "summary": "办公协调范式，处理日程、消息草稿、会议材料与同步事项。",
        "file_name": "mode-office",
        "applicable_modes": ["office"],
        "scenarios": ["meeting prep", "message drafts", "schedule coordination"],
        "recommended_tools": [
            "manage_schedule",
            "draft_message",
            "meeting_brief",
            "sync_notes",
        ],
    },
    "study": {
        "id": "mode:study",
        "skill_type": "mode",
        "title": "Study Mode Skill",
        "summary": "学习辅导范式，强调知识提炼、练习与掌握度追踪。",
        "file_name": "mode-study",
        "applicable_modes": ["study"],
        "scenarios": ["study plans", "flashcards", "quizzes", "learning summaries"],
        "recommended_tools": [
            "build_study_plan",
            "extract_learning_points",
            "quiz_me",
            "generate_flashcards",
            "track_mastery",
        ],
    },
    "danxi": {
        "id": "mode:danxi",
        "skill_type": "mode",
        "title": "Danxi Mode Skill",
        "summary": "旦夕校园论坛范式，强调论坛浏览、信息整理与低风险普通用户操作。",
        "file_name": "mode-danxi",
        "applicable_modes": ["danxi"],
        "scenarios": ["forum browsing", "thread search", "favorites", "subscriptions", "reply drafting"],
        "recommended_tools": [
            "danxi_list_posts",
            "danxi_get_post",
            "danxi_list_floors",
            "danxi_search_posts",
            "danxi_list_messages",
        ],
    },
}

_DEFAULT_REUSABLE_SKILL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "task_recognition": {
        "id": "task_recognition",
        "skill_type": "reusable",
        "title": "Task Recognition Skill",
        "summary": "识别提醒、追踪、阻塞与任务状态请求，并衔接任务工具。",
        "file_name": "task-recognition",
        "applicable_modes": ["normal", "documents", "office", "study"],
        "scenarios": ["reminders", "follow-ups", "task updates", "blocking notes"],
        "recommended_tools": ["manage_tasks"],
    },
    "research_grounding": {
        "id": "research_grounding",
        "skill_type": "reusable",
        "title": "Research Grounding Skill",
        "summary": "将研究回答绑定到来源、证据对象与引用结构。",
        "file_name": "research-grounding",
        "applicable_modes": ["research"],
        "scenarios": ["citations", "source validation", "evidence tables"],
        "recommended_tools": ["research_topic", "inspect_page", "track_source_updates"],
    },
    "study_coaching": {
        "id": "study_coaching",
        "skill_type": "reusable",
        "title": "Study Coaching Skill",
        "summary": "将资料转化为学习计划、练习与记忆巩固动作。",
        "file_name": "study-coaching",
        "applicable_modes": ["study"],
        "scenarios": ["quiz sessions", "flashcards", "study plans"],
        "recommended_tools": [
            "build_study_plan",
            "extract_learning_points",
            "quiz_me",
            "generate_flashcards",
            "track_mastery",
        ],
    },
    "knowledge_synthesis": {
        "id": "knowledge_synthesis",
        "skill_type": "reusable",
        "title": "Knowledge Synthesis Skill",
        "summary": "把材料提炼为摘要、结构化笔记与重点行动项。",
        "file_name": "knowledge-synthesis",
        "applicable_modes": ["normal", "documents", "research", "office", "study"],
        "scenarios": ["summaries", "outlines", "structured notes"],
        "recommended_tools": ["summarize_text", "organize_notes", "extract_action_items"],
    },
    "office_coordination": {
        "id": "office_coordination",
        "skill_type": "reusable",
        "title": "Office Coordination Skill",
        "summary": "将会议与协同材料转成简报、待办与后续沟通稿。",
        "file_name": "office-coordination",
        "applicable_modes": ["office", "documents"],
        "scenarios": ["meeting notes", "coordination briefs", "follow-up actions"],
        "recommended_tools": ["organize_notes", "extract_action_items", "meeting_brief", "draft_message"],
    },
    "model_capability_refresh": {
        "id": "model_capability_refresh",
        "skill_type": "reusable",
        "title": "Model Capability Refresh Skill",
        "summary": "刷新并核验模型 context/output 能力，优先官方 API，失败时落回官方文档或版本化 registry。",
        "file_name": "model-capability-refresh",
        "applicable_modes": ["normal", "research", "documents", "automation"],
        "scenarios": ["model context lookup", "model update tracking", "provider capability refresh"],
        "recommended_tools": [],
    },
    "hotspot_tracking": {
        "id": "hotspot_tracking",
        "skill_type": "reusable",
        "title": "Hotspot Tracking Skill",
        "summary": "追踪热点话题、多源比对并形成结构化摘要。",
        "file_name": "hotspot-tracking",
        "applicable_modes": ["normal", "research"],
        "scenarios": ["news digests", "hot topics", "trend tracking"],
        "recommended_tools": ["research_topic", "inspect_page", "track_source_updates", "summarize_text"],
    },
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _normalize_identifier(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("mode:"):
        suffix = _SKILL_ID_RE.sub("_", raw.split(":", 1)[1]).strip("_")
        return f"mode:{suffix}" if suffix else ""
    return _SKILL_ID_RE.sub("_", raw.replace("-", "_")).strip("_")


def _display_file_name(skill_id: str) -> str:
    normalized = _normalize_identifier(skill_id)
    if normalized.startswith("mode:"):
        return f"mode-{normalized.split(':', 1)[1].replace('_', '-')}"
    return normalized.replace("_", "-")


def _read_text_file(path: str) -> str:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = _repo_root() / resolved
    return resolved.read_text(encoding="utf-8").strip()


@dataclass
class SkillRecord:
    skill_id: str
    skill_type: str
    title: str
    summary: str
    path: str
    content: str = ""
    applicable_modes: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)
    recommended_tools: list[str] = field(default_factory=list)

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        payload = {
            "id": self.skill_id,
            "skill_type": self.skill_type,
            "title": self.title,
            "summary": self.summary,
            "storage_path": self.path,
            "applicable_modes": list(self.applicable_modes),
            "scenarios": list(self.scenarios),
            "recommended_tools": list(self.recommended_tools),
        }
        if include_content:
            payload["content"] = self.content
        return payload


class SkillRegistryManager:
    def __init__(self, skill_dir: str = "prompt/SKILL"):
        self._repo_root = _repo_root()
        self._skill_dir = Path(skill_dir)
        if not self._skill_dir.is_absolute():
            self._skill_dir = self._repo_root / self._skill_dir

    def _resolve_skill_path(self, file_name: str) -> Path:
        return self._skill_dir / file_name

    def _read_skill_content(self, path: Path, *, include_content: bool) -> str:
        if not include_content:
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""

    def _mode_skill_record(self, mode: str, *, include_content: bool = False) -> SkillRecord | None:
        payload = _DEFAULT_MODE_SKILL_DEFINITIONS.get(str(mode or "").strip())
        if payload is None:
            return None
        absolute_path = self._resolve_skill_path(payload["file_name"])
        content = self._read_skill_content(absolute_path, include_content=include_content)
        return SkillRecord(
            skill_id=payload["id"],
            skill_type="mode",
            title=payload["title"],
            summary=payload["summary"],
            path=str(absolute_path),
            content=content,
            applicable_modes=list(payload.get("applicable_modes") or []),
            scenarios=list(payload.get("scenarios") or []),
            recommended_tools=list(payload.get("recommended_tools") or []),
        )

    def _builtin_reusable_skill_record(self, skill_id: str, *, include_content: bool = False) -> SkillRecord | None:
        payload = _DEFAULT_REUSABLE_SKILL_DEFINITIONS.get(_normalize_identifier(skill_id))
        if payload is None:
            return None
        absolute_path = self._resolve_skill_path(payload["file_name"])
        content = self._read_skill_content(absolute_path, include_content=include_content)
        return SkillRecord(
            skill_id=payload["id"],
            skill_type="reusable",
            title=payload["title"],
            summary=payload["summary"],
            path=str(absolute_path),
            content=content,
            applicable_modes=list(payload.get("applicable_modes") or []),
            scenarios=list(payload.get("scenarios") or []),
            recommended_tools=list(payload.get("recommended_tools") or []),
        )

    def _parse_project_skill_file(self, path: Path) -> SkillRecord | None:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        match = _PROJECT_SKILL_FILE_RE.match(raw)
        if not match:
            return None
        metadata = json.loads(match.group(1))
        content = match.group(2).strip()
        skill_id = _normalize_identifier(metadata.get("id") or path.stem)
        return SkillRecord(
            skill_id=skill_id,
            skill_type="reusable",
            title=str(metadata.get("title") or skill_id),
            summary=str(metadata.get("summary") or "").strip(),
            path=str(path.resolve()),
            content=content,
            applicable_modes=[str(item).strip() for item in metadata.get("applicable_modes", []) if str(item).strip()],
            scenarios=[str(item).strip() for item in metadata.get("scenarios", []) if str(item).strip()],
            recommended_tools=[str(item).strip() for item in metadata.get("recommended_tools", []) if str(item).strip()],
        )

    def _iter_created_skill_records(self) -> list[SkillRecord]:
        if not self._skill_dir.exists():
            return []
        records: list[SkillRecord] = []
        for path in sorted(self._skill_dir.glob("*.md")):
            try:
                record = self._parse_project_skill_file(path)
            except Exception:
                record = None
            if record is not None:
                records.append(record)
        return records

    def list_skills(self, *, skill_type: str = "all", query: str = "") -> list[dict[str, Any]]:
        requested_type = str(skill_type or "all").strip().lower()
        query_text = str(query or "").strip().lower()
        records: list[SkillRecord] = []
        if requested_type in {"all", "mode"}:
            for mode in _DEFAULT_MODE_SKILL_DEFINITIONS:
                record = self._mode_skill_record(mode)
                if record is not None:
                    records.append(record)
        if requested_type in {"all", "reusable"}:
            for skill_id in _DEFAULT_REUSABLE_SKILL_DEFINITIONS:
                record = self._builtin_reusable_skill_record(skill_id)
                if record is not None:
                    records.append(record)
            records.extend(self._iter_created_skill_records())

        def matches(record: SkillRecord) -> bool:
            if not query_text:
                return True
            haystack = "\n".join(
                [
                    record.skill_id,
                    record.title,
                    record.summary,
                    " ".join(record.applicable_modes),
                    " ".join(record.scenarios),
                    " ".join(record.recommended_tools),
                ]
            ).lower()
            return query_text in haystack

        filtered = [record.to_dict() for record in records if matches(record)]
        filtered.sort(key=lambda item: (item["skill_type"], item["id"]))
        return filtered

    def load_skill(self, skill_id: str) -> dict[str, Any] | None:
        normalized_id = _normalize_identifier(skill_id)
        if normalized_id.startswith("mode:"):
            record = self._mode_skill_record(normalized_id.split(":", 1)[1], include_content=True)
            return record.to_dict(include_content=True) if record is not None else None

        builtin = self._builtin_reusable_skill_record(normalized_id, include_content=True)
        if builtin is not None:
            return builtin.to_dict(include_content=True)

        for record in self._iter_created_skill_records():
            if record.skill_id == normalized_id:
                return record.to_dict(include_content=True)
        return None

    def create_skill(
        self,
        *,
        skill_id: str,
        title: str,
        summary: str,
        content: str,
        recommended_tools: list[str] | None = None,
        applicable_modes: list[str] | None = None,
        scenarios: list[str] | None = None,
        source: str = "agent",
    ) -> dict[str, Any]:
        del source
        normalized_id = _normalize_identifier(skill_id or title)
        if not normalized_id or normalized_id.startswith("mode:"):
            raise ValueError("skill_id must resolve to a reusable skill identifier.")
        if self.load_skill(normalized_id) is not None:
            raise ValueError(f"skill already exists: {normalized_id}")

        normalized_title = str(title or normalized_id).strip()
        normalized_summary = str(summary or "").strip()
        normalized_content = str(content or "").strip()
        if not normalized_summary:
            raise ValueError("summary is required.")
        if not normalized_content:
            raise ValueError("content is required.")

        payload = {
            "id": normalized_id,
            "title": normalized_title,
            "summary": normalized_summary,
            "recommended_tools": [str(item).strip() for item in (recommended_tools or []) if str(item).strip()],
            "applicable_modes": [str(item).strip() for item in (applicable_modes or []) if str(item).strip()],
            "scenarios": [str(item).strip() for item in (scenarios or []) if str(item).strip()],
        }
        rendered = "\n".join(
            [
                "[Skill Metadata]",
                json.dumps(payload, ensure_ascii=False, indent=2),
                "",
                "[Skill Content]",
                normalized_content,
                "",
            ]
        )
        self._skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = self._skill_dir / f"{_display_file_name(normalized_id)}.md"
        skill_path.write_text(rendered, encoding="utf-8")
        created = self.load_skill(normalized_id)
        if created is None:
            raise ValueError(f"failed to load created skill: {normalized_id}")
        return created
