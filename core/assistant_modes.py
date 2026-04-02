"""
Assistant mode routing, prompt bundles, and shared mode configuration.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.source_catalog import SourceCatalogManager

ASSISTANT_MODE_AUTO = "auto"
ASSISTANT_MODES = ("documents", "research", "office", "study")
VALID_ASSISTANT_MODES = (ASSISTANT_MODE_AUTO, *ASSISTANT_MODES)

ACTION_RISKS = ("read", "local_write", "external_write", "destructive")
ACTION_RISK_RANK = {name: index for index, name in enumerate(ACTION_RISKS)}

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_PATH_RE = re.compile(
    r"(?i)(?:[a-z]:[\\/][^\s]+|(?:\.{1,2}[\\/]|[\\/])?[^\s]+\.(?:md|txt|pdf|docx|xlsx|pptx|csv|json|py|ts|tsx|js|jsx|html))"
)

_MODE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "documents": (
        "document",
        "docs",
        "file",
        "folder",
        "workspace",
        "directory",
        "repo",
        "repository",
        "project structure",
        "report",
        "summary file",
        "markdown",
        "pdf",
        "docx",
        "xlsx",
        "pptx",
        "csv",
        "json",
        "path",
        "local file",
        "local document",
        "read file",
        "write file",
        "rewrite file",
        "directory analysis",
        "directory tree",
        "文档",
        "文件",
        "目录",
        "文件夹",
        "工作区",
        "项目结构",
        "代码仓",
        "报告",
        "本地文件",
        "路径",
        "改写文档",
        "写入文档",
        "分析目录",
    ),
    "research": (
        "latest",
        "recent",
        "today",
        "news",
        "compare",
        "comparison",
        "recommend",
        "review",
        "what does this page say",
        "website",
        "web",
        "url",
        "source",
        "price",
        "policy",
        "regulation",
        "current",
        "official source",
        "最新",
        "最近",
        "今天",
        "新闻",
        "对比",
        "比较",
        "推荐",
        "评测",
        "网页",
        "链接",
        "网址",
        "一手信息",
        "资讯",
        "价格",
        "政策",
        "法规",
    ),
    "office": (
        "meeting",
        "agenda",
        "minutes",
        "schedule",
        "calendar",
        "invite",
        "attendee",
        "follow-up",
        "email",
        "message",
        "draft",
        "notion",
        "feishu",
        "sync notes",
        "todo",
        "task",
        "会议",
        "议程",
        "纪要",
        "日程",
        "日历",
        "排期",
        "邀请",
        "参会人",
        "邮件",
        "消息",
        "草稿",
        "同步笔记",
        "待办",
        "任务",
    ),
    "study": (
        "study",
        "learn",
        "learning",
        "course",
        "exam",
        "quiz",
        "flashcard",
        "mastery",
        "review",
        "practice",
        "syllabus",
        "lesson",
        "学习",
        "复习",
        "课程",
        "考试",
        "测验",
        "题目",
        "知识点",
        "闪卡",
        "掌握度",
        "练习",
        "讲义",
        "教案",
    ),
}

_RESEARCH_PROFILE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "academic": (
        "paper",
        "research paper",
        "journal",
        "doi",
        "arxiv",
        "pubmed",
        "citation",
        "论文",
        "文献",
        "期刊",
        "doi",
        "研究",
    ),
    "policy": (
        "policy",
        "regulation",
        "law",
        "government",
        "sec",
        "fda",
        "who",
        "gov",
        "政策",
        "法规",
        "监管",
        "政府",
        "央行",
        "证监会",
        "药监",
    ),
    "finance": (
        "finance",
        "stock",
        "earnings",
        "investor relations",
        "ir",
        "10-k",
        "10-q",
        "price target",
        "财报",
        "股票",
        "金融",
        "投资者关系",
        "业绩",
        "股价",
    ),
}

_PRIMARY_SOURCE_DOMAINS = {
    "gov.cn",
    "stats.gov.cn",
    "www.gov.cn",
    "who.int",
    "fda.gov",
    "sec.gov",
    "edgar.sec.gov",
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "crossref.org",
    "doi.org",
    "w3.org",
    "whatwg.org",
    "ietf.org",
    "github.com",
    "gitee.com",
}

_DEFAULT_SOURCE_PROFILES = {
    "workspace_local": {
        "label": "Workspace / Local Knowledge",
        "description": "Prefer local files, project notes, memory, and trusted private sources.",
        "primary_domains": [],
        "source_order": ["local", "memory", "notion"],
        "freshness": "workspace",
    },
    "study_materials": {
        "label": "Study Materials",
        "description": "Prefer local learning materials, notes, and explicit references from the user.",
        "primary_domains": [],
        "source_order": ["local", "memory", "notion", "academic"],
        "freshness": "coursework",
    },
    "tech_global": {
        "label": "Tech Global",
        "description": "Official docs, GitHub releases, standards, and vendor changelogs first.",
        "primary_domains": [
            "github.com",
            "docs.python.org",
            "developer.mozilla.org",
            "w3.org",
            "whatwg.org",
            "ietf.org",
        ],
        "source_order": ["official_docs", "standard", "repo_release", "vendor", "media"],
        "freshness": "high",
    },
    "tech_cn": {
        "label": "Tech China",
        "description": "Chinese-language official docs, cloud vendor docs, and official repositories first.",
        "primary_domains": [
            "help.aliyun.com",
            "cloud.tencent.com",
            "support.huaweicloud.com",
            "gitee.com",
            "github.com",
        ],
        "source_order": ["official_docs", "vendor", "repo_release", "media"],
        "freshness": "high",
    },
    "academic": {
        "label": "Academic",
        "description": "Papers, DOI records, PubMed, and preprint indexes first.",
        "primary_domains": [
            "arxiv.org",
            "pubmed.ncbi.nlm.nih.gov",
            "doi.org",
            "crossref.org",
        ],
        "source_order": ["paper", "index", "official", "media"],
        "freshness": "medium",
    },
    "policy": {
        "label": "Policy / Regulation",
        "description": "Government and regulator sources first.",
        "primary_domains": [
            "gov.cn",
            "stats.gov.cn",
            "who.int",
            "fda.gov",
            "sec.gov",
            "edgar.sec.gov",
        ],
        "source_order": ["government", "regulator", "official", "media"],
        "freshness": "high",
    },
    "finance": {
        "label": "Finance",
        "description": "Exchange filings, official IR, and regulator disclosures first.",
        "primary_domains": [
            "sec.gov",
            "edgar.sec.gov",
            "nasdaq.com",
            "nyse.com",
        ],
        "source_order": ["exchange", "regulator", "ir", "official", "media"],
        "freshness": "high",
    },
}

_DEFAULT_MODE_TOOL_BUNDLES = {
    "documents": {
        "tools": [
            "exec_sys_cmd",
            "get_current_system_time",
            "get_sys_vitals",
            "search_knowledge",
            "manage_tasks",
            "remember_knowledge",
            "analyze_workspace",
            "read_local_documents",
            "write_local_document",
            "rewrite_local_document",
            "compile_report",
        ],
        "mcp_servers": ["filesystem_tools"],
    },
    "research": {
        "tools": [
            "get_current_system_time",
            "search_knowledge",
            "remember_knowledge",
            "research_topic",
            "inspect_page",
            "track_source_updates",
            "compile_report",
        ],
        "mcp_servers": [],
    },
    "office": {
        "tools": [
            "get_current_system_time",
            "search_knowledge",
            "manage_tasks",
            "remember_knowledge",
            "read_local_documents",
            "write_local_document",
            "compile_report",
            "manage_schedule",
            "draft_message",
            "meeting_brief",
            "sync_notes",
        ],
        "mcp_servers": ["filesystem_tools"],
    },
    "study": {
        "tools": [
            "get_current_system_time",
            "search_knowledge",
            "remember_knowledge",
            "read_local_documents",
            "compile_report",
            "build_study_plan",
            "extract_learning_points",
            "quiz_me",
            "generate_flashcards",
            "track_mastery",
        ],
        "mcp_servers": ["filesystem_tools"],
    },
}

_DEFAULT_ROUTER_CONFIG = {
    "default_mode": ASSISTANT_MODE_AUTO,
    "sticky_current_mode": True,
    "allow_preferred_override": True,
}

_DEFAULT_DOCUMENT_PARSERS = {
    "max_file_bytes": 2_000_000,
    "max_total_chars": 24_000,
    "max_chunks_per_document": 12,
    "enable_ocr": True,
}

_DEFAULT_OFFICE_INTEGRATIONS = {
    "local": {"enabled": True, "draft_only": False},
    "notion": {"enabled": True, "draft_only": True},
    "feishu": {"enabled": True, "draft_only": True},
    "google": {"enabled": False, "draft_only": True},
    "outlook": {"enabled": False, "draft_only": True},
    "slack": {"enabled": False, "draft_only": True},
}

_MODE_PROMPT_FALLBACKS = {
    "documents": (
        "[Documents Mode]\n"
        "You are operating as a document and workspace specialist.\n"
        "Prefer local files, directory analysis, structured document reading, and safe draft-first writing.\n"
        "When editing documents, inspect first, summarize the current structure, and keep writes inside trusted roots unless the user explicitly confirms a broader target."
    ),
    "research": (
        "[Research Mode]\n"
        "You are operating as a research specialist.\n"
        "Prioritize first-party and official sources, reason explicitly about freshness, and ground claims in evidence objects and citations.\n"
        "When a direct URL exists, prefer inspecting it. When the user asks for latest information, favor fresh sources and say when evidence is partial."
    ),
    "office": (
        "[Office Mode]\n"
        "You are operating as an office and coordination specialist.\n"
        "Favor schedules, drafts, task state, meeting notes, and note synchronization.\n"
        "External side effects stay draft-first. Do not pretend that a message or calendar entry has been sent unless the tool confirms it."
    ),
    "study": (
        "[Study Mode]\n"
        "You are operating as a study coach.\n"
        "Favor plans, extracted learning points, quizzes, flashcards, and mastery tracking.\n"
        "Base explanations on the provided materials when possible, preserve source references, and optimize for retention and practice."
    ),
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_json_config(raw_value: Any) -> Any:
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if not stripped:
            return {}
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return {}
    return raw_value or {}


def _normalize_mode(value: Any, *, fallback: str = "documents") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in VALID_ASSISTANT_MODES:
        return normalized
    return fallback


def _normalize_path(path_value: str) -> str:
    return str(Path(path_value).expanduser().resolve())


def _domain_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    return parsed.netloc.lower().strip()


def _looks_like_chinese(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


@dataclass
class RouteDecision:
    requested_mode: str
    current_mode: str
    route_reason: str
    source_profile: str
    tool_bundle: list[str]
    mcp_servers: list[str]
    prompt_bundle: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_mode": self.requested_mode,
            "current_mode": self.current_mode,
            "route_reason": self.route_reason,
            "source_profile": self.source_profile,
            "tool_bundle": list(self.tool_bundle),
            "mcp_servers": list(self.mcp_servers),
            "prompt_bundle": self.prompt_bundle,
        }


class AssistantModeManager:
    def __init__(self, config_manager):
        self._config = config_manager
        self._source_catalog = SourceCatalogManager(config_manager)

    def _mode_registry(self) -> dict[str, Any]:
        return _deep_merge(
            {
                "enabled_modes": list(ASSISTANT_MODES),
                "prompt_dir": "prompt/modes",
                "tool_bundles": _DEFAULT_MODE_TOOL_BUNDLES,
            },
            _parse_json_config(self._config.get("assistant_modes")),
        )

    def get_mode_router_config(self) -> dict[str, Any]:
        return _deep_merge(_DEFAULT_ROUTER_CONFIG, _parse_json_config(self._config.get("mode_router")))

    def get_document_parser_config(self) -> dict[str, Any]:
        return _deep_merge(_DEFAULT_DOCUMENT_PARSERS, _parse_json_config(self._config.get("document_parsers")))

    def get_office_integrations(self) -> dict[str, Any]:
        return _deep_merge(_DEFAULT_OFFICE_INTEGRATIONS, _parse_json_config(self._config.get("office_integrations")))

    def get_source_catalog_path(self) -> str:
        return self._source_catalog.get_catalog_path()

    def get_source_catalog_status(self) -> dict[str, Any]:
        return self._source_catalog.get_catalog_status()

    def get_source_profiles(self) -> dict[str, Any]:
        catalog_profiles = self._source_catalog.get_source_profiles()
        legacy_profiles = _parse_json_config(self._config.get("source_profiles"))
        return _deep_merge(catalog_profiles, legacy_profiles)

    def get_source_profile(self, profile_name: str) -> dict[str, Any]:
        profiles = self.get_source_profiles()
        normalized = str(profile_name or "").strip() or "workspace_local"
        payload = profiles.get(normalized)
        if payload is None:
            payload = profiles.get("tech_updates") or profiles.get("workspace_local", {})
            normalized = "tech_updates" if "tech_updates" in profiles else "workspace_local"
        return {"name": normalized, **payload}

    def get_sources_for_profile(
        self,
        profile_name: str,
        *,
        official_only: bool | None = None,
    ) -> list[dict[str, Any]]:
        return self._source_catalog.get_sources(profile_name, official_only=official_only)

    def get_source_by_id(self, source_id: str) -> dict[str, Any] | None:
        return self._source_catalog.get_source_by_id(source_id)

    def resolve_source_auth_entries(self, source_config: dict[str, Any]) -> list[dict[str, Any]]:
        return self._source_catalog.resolve_auth_entries(source_config)

    def get_tool_bundle(self, mode: str) -> dict[str, list[str]]:
        registry = self._mode_registry()
        bundles = registry.get("tool_bundles") or {}
        payload = bundles.get(mode) or _DEFAULT_MODE_TOOL_BUNDLES.get(mode) or {"tools": [], "mcp_servers": []}
        return {
            "tools": [str(item) for item in payload.get("tools", []) if str(item).strip()],
            "mcp_servers": [str(item) for item in payload.get("mcp_servers", []) if str(item).strip()],
        }

    def get_prompt_for_mode(self, mode: str) -> str:
        registry = self._mode_registry()
        prompt_dir = registry.get("prompt_dir") or "prompt/modes"
        prompt_path = Path(str(prompt_dir)) / mode
        try:
            return prompt_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return _MODE_PROMPT_FALLBACKS.get(mode, "")

    def get_trusted_write_roots(self) -> list[str]:
        configured = _parse_json_config(self._config.get("trusted_write_roots"))
        if isinstance(configured, str):
            configured = [configured]
        roots = [str(item).strip() for item in (configured or []) if str(item).strip()]
        if not roots:
            cwd = Path.cwd()
            roots = [
                str(cwd),
                str(cwd / "user"),
                str(cwd / "docs"),
            ]
        normalized: list[str] = []
        for root in roots:
            try:
                normalized.append(_normalize_path(root))
            except Exception:
                continue
        return list(dict.fromkeys(normalized))

    def is_trusted_write_path(self, path_value: str) -> bool:
        if not path_value:
            return False
        try:
            candidate = Path(path_value).expanduser().resolve()
        except Exception:
            return False
        candidate_str = str(candidate)
        for root in self.get_trusted_write_roots():
            if candidate_str == root or candidate_str.startswith(f"{root}{os.sep}"):
                return True
        return False

    def classify_research_source_profile(self, text: str) -> str:
        classified = self._source_catalog.classify_research_profile(text)
        if classified:
            return classified
        if _looks_like_chinese(text):
            return "policy_cn"
        return "tech_updates"

    def is_primary_source(self, url: str, profile_name: str = "") -> bool:
        return self._source_catalog.is_primary_source(url, profile_name)

    async def resolve_context_limit(
        self,
        *,
        provider_name: str,
        api_url: str,
        model_name: str,
        adapter,
    ) -> dict[str, Any]:
        return (
            await self._source_catalog.resolve_context_limit(
                provider_name=provider_name,
                api_url=api_url,
                model_name=model_name,
                adapter=adapter,
            )
        ).to_dict()

    def route(
        self,
        input_info: dict[str, Any],
        *,
        session_metadata: dict[str, Any] | None = None,
        source=None,
    ) -> RouteDecision:
        session_metadata = session_metadata or {}
        router_config = self.get_mode_router_config()
        requested_mode = _normalize_mode(
            (input_info.get("metadata") or {}).get("preferred_mode")
            or input_info.get("preferred_mode")
            or router_config.get("default_mode")
            or ASSISTANT_MODE_AUTO,
            fallback=ASSISTANT_MODE_AUTO,
        )

        content = str(input_info.get("content") or "").strip()
        current_mode = _normalize_mode(session_metadata.get("current_mode") or "", fallback="")
        if requested_mode != ASSISTANT_MODE_AUTO and router_config.get("allow_preferred_override", True):
            bundle = self.get_tool_bundle(requested_mode)
            return RouteDecision(
                requested_mode=requested_mode,
                current_mode=requested_mode,
                route_reason=f"Preferred mode override requested: {requested_mode}",
                source_profile=self._default_source_profile_for_mode(requested_mode, content),
                tool_bundle=bundle["tools"],
                mcp_servers=bundle["mcp_servers"],
                prompt_bundle=requested_mode,
            )

        scores = {mode: 0 for mode in ASSISTANT_MODES}
        triggers = {mode: [] for mode in ASSISTANT_MODES}
        lowered = content.lower()

        for mode, keywords in _MODE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in lowered:
                    scores[mode] += 2
                    if len(triggers[mode]) < 4:
                        triggers[mode].append(keyword)

        if _URL_RE.search(content):
            scores["research"] += 4
            triggers["research"].append("direct_url")

        if _PATH_RE.search(content):
            scores["documents"] += 4
            triggers["documents"].append("local_path")

        source_kind = getattr(source, "kind", "") or ""
        source_id = getattr(source, "id", "") or ""
        if source_kind == "feishu":
            scores["office"] += 1
            triggers["office"].append("source:feishu")
        if source_id.lower().startswith("desktop"):
            scores["documents"] += 1

        if router_config.get("sticky_current_mode", True) and current_mode in ASSISTANT_MODES:
            scores[current_mode] += 1
            triggers[current_mode].append("sticky_current_mode")

        best_mode = max(scores.items(), key=lambda item: (item[1], item[0]))[0]
        if scores[best_mode] <= 0:
            best_mode = current_mode if current_mode in ASSISTANT_MODES else "documents"
            reason = (
                f"No strong routing signal found; reusing current mode {best_mode}."
                if current_mode in ASSISTANT_MODES
                else "No strong routing signal found; defaulting to documents for local work."
            )
        else:
            matched = ", ".join(dict.fromkeys(triggers[best_mode])) or "keyword_match"
            reason = f"Matched {best_mode} signals: {matched}"

        bundle = self.get_tool_bundle(best_mode)
        return RouteDecision(
            requested_mode=requested_mode,
            current_mode=best_mode,
            route_reason=reason,
            source_profile=self._default_source_profile_for_mode(best_mode, content),
            tool_bundle=bundle["tools"],
            mcp_servers=bundle["mcp_servers"],
            prompt_bundle=best_mode,
        )

    def _default_source_profile_for_mode(self, mode: str, content: str) -> str:
        if mode == "research":
            return self.classify_research_source_profile(content)
        if mode == "study":
            return "study_materials"
        return "workspace_local"
