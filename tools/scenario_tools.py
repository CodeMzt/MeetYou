"""
High-level scenario orchestration tools for the main assistant.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

from core.tool_runtime.models import ToolCallResult, ToolErrorCategory, ToolSourceType
from tools.memory_tools import MemoryTools
from tools.authoritative_sources import AuthoritativeSourceRegistry
from tools.task_manager import TaskManager
from tools.web_search import WebSearchTools

ActivityCallback = Callable[[str, str, dict[str, Any] | None], Awaitable[None]]

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_SUMMARY_LIMIT = 800
_NOTION_SEARCH_TOOL_CANDIDATES = (
    "post-search",
    "search",
    "search_pages",
    "notion_search",
)
_NOTION_PAGE_TOOL_CANDIDATES = (
    "retrieve-a-page",
    "retrieve_page",
    "notion_retrieve_page",
)
_NOTION_CHILDREN_TOOL_CANDIDATES = (
    "retrieve-block-children",
    "retrieve_block_children",
    "notion_retrieve_block_children",
)
_KNOWLEDGE_HINTS = (
    "之前",
    "上次",
    "以前",
    "记得",
    "聊过",
    "讨论过",
    "项目",
    "方案",
    "notion",
    "文档",
    "需求",
    "会议",
    "谁说过",
    "what did we",
    "previous",
    "earlier",
    "remember",
    "project",
    "spec",
    "notion",
)
_LIVE_WEB_HINTS = (
    "最新",
    "今天",
    "实时",
    "现在",
    "新闻",
    "天气",
    "价格",
    "推荐",
    "对比",
    "测评",
    "recent",
    "latest",
    "today",
    "news",
    "weather",
    "price",
    "recommend",
    "compare",
)


def _normalize_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "").strip())


def _trim_text(value: Any, limit: int = _SUMMARY_LIMIT) -> str:
    normalized = _normalize_text(value)
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _looks_like_url(value: str) -> bool:
    return bool(_URL_RE.search(str(value or "").strip()))


def _extract_json_payload(text: str) -> dict[str, Any] | list[Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()

    candidates = [raw]
    object_match = re.search(r"(\{.*\})", raw, re.DOTALL)
    if object_match:
        candidates.append(object_match.group(1).strip())
    array_match = re.search(r"(\[.*\])", raw, re.DOTALL)
    if array_match:
        candidates.append(array_match.group(1).strip())

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (TypeError, json.JSONDecodeError):
            continue
    return None


def _tool_failure_message(result: ToolCallResult) -> str:
    if result.error is None:
        return ""
    message = _normalize_text(result.error.message)
    backend_error = _normalize_text(result.error.details.get("backend_error")) if isinstance(result.error.details, dict) else ""
    if backend_error:
        return f"{message} {backend_error}".strip()
    return message


def _collect_strings(value: Any, *, limit: int = 12) -> list[str]:
    results: list[str] = []

    def walk(node: Any) -> None:
        if len(results) >= limit:
            return
        if isinstance(node, str):
            text = _normalize_text(node)
            if text:
                results.append(text)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
                if len(results) >= limit:
                    return
            return
        if isinstance(node, dict):
            preferred_keys = (
                "plain_text",
                "content",
                "title",
                "name",
                "text",
                "rich_text",
                "caption",
            )
            for key in preferred_keys:
                if key in node:
                    walk(node.get(key))
                    if len(results) >= limit:
                        return
            for nested_key, nested_value in node.items():
                if nested_key in preferred_keys:
                    continue
                walk(nested_value)
                if len(results) >= limit:
                    return

    walk(value)
    seen: set[str] = set()
    deduped: list[str] = []
    for item in results:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _memory_sources_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    source_id = 1

    for entry in payload.get("profile", []):
        source_label = _normalize_text(entry.get("source_label"))
        title = _normalize_text(entry.get("fact_key") or "Memory fact")
        if source_label:
            title = f"{title} [{source_label}]"
        summary = _normalize_text(entry.get("fact_value") or entry.get("content"))
        if not summary:
            continue
        sources.append(
            {
                "id": source_id,
                "title": title,
                "source_type": "memory",
                "url": "",
                "page_id": "",
                "summary": summary,
                "confidence": entry.get("score"),
            }
        )
        source_id += 1

    for entry in payload.get("facts", []):
        source_label = _normalize_text(entry.get("source_label"))
        summary = _normalize_text(entry.get("content"))
        if not summary:
            continue
        title = _normalize_text(entry.get("fact_key") or "Long-term fact")
        if source_label:
            title = f"{title} [{source_label}]"
        sources.append(
            {
                "id": source_id,
                "title": title,
                "source_type": "memory",
                "url": "",
                "page_id": "",
                "summary": summary,
                "confidence": entry.get("score"),
            }
        )
        source_id += 1

    for entry in payload.get("recent_events", []):
        source_label = _normalize_text(entry.get("source_label"))
        summary = _normalize_text(entry.get("content"))
        if not summary:
            continue
        title = _normalize_text(entry.get("created_at") or "Recent event")
        if source_label:
            title = f"{title} [{source_label}]"
        sources.append(
            {
                "id": source_id,
                "title": title,
                "source_type": "memory",
                "url": "",
                "page_id": "",
                "summary": summary,
                "confidence": entry.get("score"),
            }
        )
        source_id += 1

    return sources


class ScenarioTools:
    def __init__(self, memory, context_manager, mcp_manager, mode_manager=None, task_manager=None):
        self._memory = memory
        self._context_manager = context_manager
        self._mcp_manager = mcp_manager
        self._mode_manager = mode_manager
        self._memory_tools = MemoryTools(memory)
        self._task_manager = task_manager or TaskManager(memory)
        self._web_tools = WebSearchTools(mcp_manager)
        self._authoritative_sources = AuthoritativeSourceRegistry(mode_manager, self._web_tools)

    async def _emit_activity(
        self,
        callback: ActivityCallback | None,
        phase: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if callback is None:
            return
        await callback(
            phase,
            content,
            {
                "activity_kind": "tool_chain",
                **(metadata or {}),
            },
        )

    def _relay_activity(
        self,
        callback: ActivityCallback | None,
        phase_map: dict[str, str] | None = None,
    ) -> ActivityCallback | None:
        if callback is None:
            return None

        async def relay(phase: str, content: str, metadata: dict[str, Any] | None = None) -> None:
            mapped_phase = (phase_map or {}).get(phase, phase)
            await self._emit_activity(callback, mapped_phase, content, metadata)

        return relay

    def _should_load_context(self, query: str, goal: str = "") -> bool:
        if self._mode_manager is not None:
            semantic_getter = getattr(self._mode_manager, "should_preload_context", None)
            if callable(semantic_getter):
                return bool(semantic_getter(query, goal))
        haystack = f"{query}\n{goal}".lower()
        return any(hint in haystack for hint in _KNOWLEDGE_HINTS)

    def _looks_like_live_web_query(self, query: str) -> bool:
        if self._mode_manager is not None:
            semantic_getter = getattr(self._mode_manager, "is_live_web_query", None)
            if callable(semantic_getter):
                return bool(semantic_getter(query))
        lowered = str(query or "").lower()
        return any(hint in lowered for hint in _LIVE_WEB_HINTS)

    async def _maybe_load_session_context(
        self,
        session_id: str,
        *,
        query: str,
        goal: str = "",
        activity_callback: ActivityCallback | None = None,
    ) -> str:
        if not session_id or not self._should_load_context(query, goal):
            return ""
        await self._emit_activity(
            activity_callback,
            "loading_context",
            "Loading recent conversation context",
            {"session_id": session_id},
        )
        try:
            context_text = await self._context_manager.load_context(session_id)
        except Exception:
            return ""
        return _trim_text(context_text, 500)

    def _default_source_profile(self, route_context: dict[str, Any] | None, query: str) -> str:
        if isinstance(route_context, dict) and route_context.get("source_profile"):
            return str(route_context["source_profile"])
        if self._mode_manager is not None:
            return self._mode_manager.classify_research_source_profile(query)
        lowered = str(query or "").lower()
        if any(token in lowered for token in ("paper", "doi", "arxiv", "论文", "文献")):
            return "academic"
        if any(token in lowered for token in ("policy", "law", "regulation", "政策", "法规")):
            return "policy"
        if any(token in lowered for token in ("finance", "stock", "earnings", "财报", "股票")):
            return "finance"
        if any("\u4e00" <= char <= "\u9fff" for char in str(query or "")):
            return "tech_cn"
        return "tech_global"

    def _classify_source_type(self, url: str) -> str:
        lowered = str(url or "").lower()
        if ".gov" in lowered or "gov.cn" in lowered:
            return "government"
        if any(token in lowered for token in ("docs.", "/docs", "developer.")):
            return "official_docs"
        if any(token in lowered for token in ("github.com", "gitee.com")):
            return "repo_release"
        if any(token in lowered for token in ("sec.gov", "edgar", "ir.", "investor")):
            return "ir"
        if any(token in lowered for token in ("arxiv.org", "pubmed", "doi.org", "crossref.org")):
            return "paper"
        return "web"

    def _build_evidence_object(self, source: dict[str, Any], *, source_profile: str) -> dict[str, Any]:
        url = _normalize_text(source.get("url"))
        if self._mode_manager is not None:
            is_primary = self._mode_manager.is_primary_source(url, source_profile)
        else:
            is_primary = False
        return {
            "source_id": source.get("id"),
            "title": _normalize_text(source.get("title")),
            "url": url,
            "domain": re.sub(r"^www\.", "", re.sub(r":\d+$", "", re.sub(r"/.*$", "", url.replace("https://", "").replace("http://", "")))),
            "published_date": _normalize_text(source.get("published_date")),
            "excerpt": _trim_text(source.get("summary") or source.get("snippet"), 320),
            "reader": _normalize_text(source.get("reader")),
            "source_type": self._classify_source_type(url),
            "credible_level": "primary" if is_primary else "secondary",
            "is_primary_source": is_primary,
            "citation": f"[{source.get('id')}] {_normalize_text(source.get('title'))}",
        }

    def _decorate_research_payload(
        self,
        payload: dict[str, Any],
        *,
        source_profile: str,
    ) -> dict[str, Any]:
        search_payload = dict(payload)
        sources = list(search_payload.get("sources") or [])
        evidence = [
            self._build_evidence_object(source, source_profile=source_profile)
            for source in sources
            if isinstance(source, dict)
        ]
        search_payload["source_profile"] = source_profile
        search_payload["evidence"] = evidence
        search_payload["citation_blocks"] = [
            {"source_id": item["source_id"], "citation": item["citation"]}
            for item in evidence
        ]
        return search_payload

    def _default_source_profile(self, route_context: dict[str, Any] | None, query: str) -> str:
        if isinstance(route_context, dict) and route_context.get("source_profile"):
            return str(route_context["source_profile"])
        if self._mode_manager is not None:
            return self._mode_manager.classify_research_source_profile(query)
        lowered = str(query or "").lower()
        if any(token in lowered for token in ("paper", "doi", "arxiv", "study", "trial", "pubmed")):
            return "academic_biomed"
        if any(token in lowered for token in ("policy", "law", "regulation", "government", "fda", "who")):
            return "policy_global"
        if any(token in lowered for token in ("finance", "stock", "earnings", "macro", "inflation", "gdp")):
            return "finance_macro"
        if any(token in lowered for token in ("cve", "kev", "vulnerability", "exploit")):
            return "cyber_threat"
        if any("\u4e00" <= char <= "\u9fff" for char in str(query or "")):
            return "policy_cn"
        return "tech_updates"

    def _can_use_authoritative_catalog(self) -> bool:
        getter = getattr(self._mode_manager, "get_source_catalog_status", None)
        if not callable(getter):
            return False
        status = getter() or {}
        return bool(status.get("available"))

    async def _fallback_web_research(
        self,
        query: str,
        *,
        source_profile: str,
        session_id: str,
        activity_callback: ActivityCallback | None,
    ) -> dict[str, Any] | ToolCallResult:
        raw = await self._web_tools.search_web(
            query,
            session_id=session_id,
            activity_callback=self._relay_activity(
                activity_callback,
                {"searching": "searching_web"},
            ),
            source_profile=source_profile,
        )
        if isinstance(raw, ToolCallResult):
            return raw
        payload = _extract_json_payload(raw)
        if not isinstance(payload, dict):
            return {
                "search_error": _trim_text(raw),
                "catalog_unavailable": not self._can_use_authoritative_catalog(),
                "sources": [],
            }
        decorated = self._decorate_research_payload(payload, source_profile=source_profile)
        decorated.setdefault("catalog_unavailable", not self._can_use_authoritative_catalog())
        return decorated

    async def research_topic(
        self,
        query: str,
        goal: str = "",
        session_id: str = "",
        source=None,
        activity_callback: ActivityCallback | None = None,
        route_context: dict[str, Any] | None = None,
    ) -> str | ToolCallResult:
        del source
        normalized_query = _normalize_text(query)
        if not normalized_query:
            return ToolCallResult.failure(
                tool_name="research_topic",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="research_query_required",
                category=ToolErrorCategory.VALIDATION,
                message="research_topic requires a non-empty query.",
            )
        source_profile = self._default_source_profile(route_context, normalized_query)

        await self._emit_activity(
            activity_callback,
            "routing",
            f"Routing request to web research: {normalized_query}",
            {"tool_name": "research_topic", "source_profile": source_profile},
        )
        session_context = await self._maybe_load_session_context(
            session_id,
            query=normalized_query,
            goal=goal,
            activity_callback=activity_callback,
        )

        authoritative_payload: dict[str, Any] = {}
        if self._can_use_authoritative_catalog():
            authoritative_payload = await self._authoritative_sources.search(
                normalized_query,
                source_profile=source_profile,
                limit=5,
                activity_callback=self._relay_activity(
                    activity_callback,
                    {"searching_web": "searching_web"},
                ),
            )

        fallback_payload = None
        if not authoritative_payload.get("sources"):
            fallback_payload = await self._fallback_web_research(
                normalized_query,
                source_profile=source_profile,
                session_id=session_id,
                activity_callback=activity_callback,
            )

        if isinstance(fallback_payload, ToolCallResult):
            fallback_error = _tool_failure_message(fallback_payload)
        else:
            fallback_error = ""

        if not authoritative_payload.get("sources") and not isinstance(fallback_payload, dict):
            return json.dumps(
                {
                    "chain": "research_topic",
                    "query": normalized_query,
                    "goal": _normalize_text(goal),
                    "source_profile": source_profile,
                    "session_context": session_context,
                    "search_error": fallback_error or "Research backends returned no usable results.",
                    "catalog_unavailable": not self._can_use_authoritative_catalog(),
                    "answer_style": "If search failed, say web search is unavailable instead of inventing facts.",
                },
                ensure_ascii=False,
                indent=2,
            )

        if authoritative_payload.get("sources"):
            search_payload = self._decorate_research_payload(
                {
                    "query": normalized_query,
                    "search_backend": "source_catalog",
                    "summary_hint": "",
                    "sources": authoritative_payload.get("sources", []),
                    "partial_failures": authoritative_payload.get("partial_failures", []),
                    "catalog_status": authoritative_payload.get("catalog_status", {}),
                    "catalog_unavailable": authoritative_payload.get("catalog_unavailable", False),
                },
                source_profile=source_profile,
            )
            additional_results = []
            if isinstance(fallback_payload, dict):
                additional_results = list((fallback_payload.get("additional_results") or []))[:3]
                if fallback_payload.get("sources"):
                    additional_results.extend(list(fallback_payload.get("sources") or [])[:2])
            search_payload["additional_results"] = additional_results
        else:
            search_payload = fallback_payload or {
                "search_error": "No usable research results.",
                "catalog_unavailable": True,
            }

        return json.dumps(
            {
                "chain": "research_topic",
                "query": normalized_query,
                "goal": _normalize_text(goal),
                "source_profile": source_profile,
                "session_context": session_context,
                "search": search_payload,
                "answer_style": "Lead with the answer, then cite sourced claims inline like [1], [2].",
            },
            ensure_ascii=False,
            indent=2,
        )

    async def inspect_page(
        self,
        url: str,
        goal: str = "",
        session_id: str = "",
        source=None,
        activity_callback: ActivityCallback | None = None,
        route_context: dict[str, Any] | None = None,
    ) -> str | ToolCallResult:
        del source
        normalized_url = _normalize_text(url)
        if not normalized_url:
            return ToolCallResult.failure(
                tool_name="inspect_page",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="inspect_url_required",
                category=ToolErrorCategory.VALIDATION,
                message="inspect_page requires a non-empty URL.",
            )
        source_profile = self._default_source_profile(route_context, normalized_url)

        await self._emit_activity(
            activity_callback,
            "routing",
            f"Inspecting direct page: {normalized_url}",
            {"tool_name": "inspect_page", "url": normalized_url, "source_profile": source_profile},
        )
        session_context = await self._maybe_load_session_context(
            session_id,
            query=normalized_url,
            goal=goal,
            activity_callback=activity_callback,
        )
        raw = await self._web_tools.read_web_page(
            normalized_url,
            session_id=session_id,
            activity_callback=self._relay_activity(activity_callback),
            source_profile=source_profile,
        )
        if isinstance(raw, ToolCallResult):
            payload = None
            raw_text = _tool_failure_message(raw)
        else:
            payload = _extract_json_payload(raw)
            raw_text = raw

        if not isinstance(payload, dict):
            return json.dumps(
                {
                    "chain": "inspect_page",
                    "url": normalized_url,
                    "goal": _normalize_text(goal),
                    "source_profile": source_profile,
                    "session_context": session_context,
                    "page_error": _trim_text(raw_text),
                    "answer_style": "If the page could not be read, say what failed and avoid pretending to know the page contents.",
                },
                ensure_ascii=False,
                indent=2,
            )

        return json.dumps(
            {
                "chain": "inspect_page",
                "url": normalized_url,
                "goal": _normalize_text(goal),
                "source_profile": source_profile,
                "session_context": session_context,
                "page": self._decorate_research_payload(
                    {
                        "sources": [payload.get("source")] if isinstance(payload.get("source"), dict) else [],
                        **payload,
                    },
                    source_profile=source_profile,
                ),
                "answer_style": "Explain the page directly and cite it as [1] if you use page facts.",
            },
            ensure_ascii=False,
            indent=2,
        )

    async def track_source_updates(
        self,
        source_profile: str,
        watchlist: list[str] | str | None = None,
        since: str = "",
        limit: int = 8,
        session_id: str = "",
        source=None,
        activity_callback: ActivityCallback | None = None,
        route_context: dict[str, Any] | None = None,
    ) -> str:
        del session_id, source, route_context
        normalized_profile = _normalize_text(source_profile) or "tech_updates"
        payload = await self._authoritative_sources.track_updates(
            source_profile=normalized_profile,
            watchlist=watchlist,
            since=since,
            limit=limit,
            activity_callback=self._relay_activity(
                activity_callback,
                {"searching_web": "searching_web"},
            ),
        )
        payload["tool"] = "track_source_updates"
        payload["status"] = "ok" if payload.get("updates") else "no_updates"
        payload["answer_style"] = "Summarize the freshest relevant updates first, then list sources inline with citations."
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _notion_tool_names(self) -> list[str]:
        names: list[str] = []
        for tool_name, server_name in self._mcp_manager.tool_map.items():
            if "notion" not in str(server_name or "").lower():
                continue
            names.append(tool_name)
        return names

    def _pick_notion_tool(self, exact_candidates: tuple[str, ...], fragments: tuple[str, ...]) -> str:
        notion_tools = self._notion_tool_names()
        notion_lower_map = {name.lower(): name for name in notion_tools}
        for candidate in exact_candidates:
            chosen = notion_lower_map.get(candidate.lower())
            if chosen:
                return chosen
        for name in notion_tools:
            lowered = name.lower()
            if all(fragment in lowered for fragment in fragments):
                return name
        return ""

    async def _call_mcp_text(self, tool_name: str, arguments: dict[str, Any]) -> str:
        result = await self._mcp_manager.call_mcp_tool(tool_name, arguments)
        return "\n".join(
            item.text
            for item in result.content
            if getattr(item, "type", "") == "text"
        ).strip()

    def _extract_notion_title(self, item: dict[str, Any]) -> str:
        direct_title = _normalize_text(item.get("title") or item.get("name"))
        if direct_title:
            return direct_title
        properties = item.get("properties")
        strings = _collect_strings(properties, limit=4)
        if strings:
            return strings[0]
        fallback_strings = _collect_strings(item, limit=4)
        return fallback_strings[0] if fallback_strings else ""

    def _normalize_notion_search_results(
        self,
        payload: dict[str, Any] | list[Any] | None,
    ) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = payload.get("results") or payload.get("data") or payload.get("items") or []
        else:
            items = []

        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            page_id = _normalize_text(item.get("id"))
            url = _normalize_text(item.get("url"))
            title = self._extract_notion_title(item) or page_id or url or "Notion result"
            summary_text = _collect_strings(item.get("properties"), limit=6)
            if not summary_text:
                summary_text = _collect_strings(item, limit=6)
            summary = _trim_text(" ".join(summary_text), 400)
            normalized.append(
                {
                    "page_id": page_id,
                    "url": url,
                    "title": title,
                    "summary": summary or title,
                    "object": _normalize_text(item.get("object") or item.get("type")),
                }
            )
        return normalized

    async def _read_notion_page(self, page_id: str, title: str) -> dict[str, Any] | None:
        page_tool = self._pick_notion_tool(_NOTION_PAGE_TOOL_CANDIDATES, ("page",))
        children_tool = self._pick_notion_tool(_NOTION_CHILDREN_TOOL_CANDIDATES, ("block", "children"))

        fragments: list[str] = []
        page_url = ""

        if page_tool:
            try:
                raw_page = await self._call_mcp_text(page_tool, {"page_id": page_id})
                payload = _extract_json_payload(raw_page)
                if isinstance(payload, dict):
                    page_url = _normalize_text(payload.get("url"))
                    fragments.extend(_collect_strings(payload, limit=8))
            except Exception:
                pass

        if children_tool:
            try:
                raw_children = await self._call_mcp_text(children_tool, {"block_id": page_id})
                payload = _extract_json_payload(raw_children)
                if isinstance(payload, (dict, list)):
                    fragments.extend(_collect_strings(payload, limit=12))
            except Exception:
                pass

        summary = _trim_text(" ".join(fragment for fragment in fragments if fragment), 500)
        if not summary:
            return None
        return {
            "title": title,
            "source_type": "notion",
            "url": page_url,
            "page_id": page_id,
            "summary": summary,
        }

    async def _search_notion_knowledge(
        self,
        query: str,
        activity_callback: ActivityCallback | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        search_tool = self._pick_notion_tool(_NOTION_SEARCH_TOOL_CANDIDATES, ("search",))
        if not search_tool:
            return [], ["Notion MCP is unavailable or does not expose a search tool."]

        await self._emit_activity(
            activity_callback,
            "searching_knowledge",
            f"Searching Notion knowledge: {query}",
            {"tool_name": "search_knowledge"},
        )
        failures: list[str] = []

        try:
            raw = await self._call_mcp_text(search_tool, {"query": query})
        except Exception as exc:
            return [], [f"Notion search failed: {exc}"]

        payload = _extract_json_payload(raw)
        results = self._normalize_notion_search_results(payload)
        sources: list[dict[str, Any]] = []

        for index, item in enumerate(results[:3], start=1):
            detailed = None
            if item.get("page_id"):
                detailed = await self._read_notion_page(item["page_id"], item["title"])
            source = detailed or {
                "title": item["title"],
                "source_type": "notion",
                "url": item.get("url", ""),
                "page_id": item.get("page_id", ""),
                "summary": item.get("summary", ""),
            }
            source["id"] = index
            sources.append(source)

        if not sources and raw:
            failures.append("Notion search returned no readable results.")
        return sources, failures

    async def search_knowledge(
        self,
        query: str,
        scope: str = "auto",
        session_id: str = "",
        source=None,
        activity_callback: ActivityCallback | None = None,
    ) -> str | ToolCallResult:
        normalized_query = _normalize_text(query)
        normalized_scope = str(scope or "auto").strip().lower() or "auto"
        if normalized_scope not in {"auto", "memory", "notion"}:
            return ToolCallResult.failure(
                tool_name="search_knowledge",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="knowledge_scope_invalid",
                category=ToolErrorCategory.VALIDATION,
                message="search_knowledge scope must be one of auto, memory, notion.",
                details={"scope": normalized_scope},
            )
        if not normalized_query:
            return ToolCallResult.failure(
                tool_name="search_knowledge",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="knowledge_query_required",
                category=ToolErrorCategory.VALIDATION,
                message="search_knowledge requires a non-empty query.",
            )

        await self._emit_activity(
            activity_callback,
            "routing",
            f"Routing request to knowledge search: {normalized_query}",
            {"tool_name": "search_knowledge"},
        )

        if _looks_like_url(normalized_query):
            return json.dumps(
                {
                    "chain": "search_knowledge",
                    "query": normalized_query,
                    "scope_used": [],
                    "found": False,
                    "sources": [],
                    "route_suggestion": {
                        "preferred_tool": "inspect_page",
                        "reason": "This looks like a direct URL. Use inspect_page for page reading.",
                    },
                },
                ensure_ascii=False,
                indent=2,
            )

        if normalized_scope == "auto" and self._looks_like_live_web_query(normalized_query):
            return json.dumps(
                {
                    "chain": "search_knowledge",
                    "query": normalized_query,
                    "scope_used": [],
                    "found": False,
                    "sources": [],
                    "route_suggestion": {
                        "preferred_tool": "research_topic",
                        "reason": "This looks like a live external-information request rather than private knowledge lookup.",
                    },
                },
                ensure_ascii=False,
                indent=2,
            )

        await self._emit_activity(
            activity_callback,
            "loading_context",
            "Loading private knowledge sources",
            {"tool_name": "search_knowledge"},
        )

        failures: list[str] = []
        sources: list[dict[str, Any]] = []
        scope_used: list[str] = []

        if normalized_scope in {"auto", "memory"}:
            try:
                memory_raw = await self._memory_tools.search_memory(
                    normalized_query,
                    session_id=session_id,
                    source=source,
                )
                memory_payload = _extract_json_payload(memory_raw)
                if isinstance(memory_payload, dict):
                    memory_sources = _memory_sources_from_payload(memory_payload)
                    if memory_sources:
                        scope_used.append("memory")
                        sources.extend(memory_sources)
            except Exception as exc:
                failures.append(f"Memory search failed: {exc}")

        if normalized_scope in {"auto", "notion"}:
            notion_sources, notion_failures = await self._search_notion_knowledge(
                normalized_query,
                activity_callback=activity_callback,
            )
            if notion_sources:
                scope_used.append("notion")
                offset = len(sources)
                for index, item in enumerate(notion_sources, start=1):
                    item["id"] = offset + index
                    sources.append(item)
            failures.extend(notion_failures)

        return json.dumps(
            {
                "chain": "search_knowledge",
                "query": normalized_query,
                "scope_used": scope_used,
                "found": bool(sources),
                "sources": sources,
                "partial_failures": failures,
                "answer_style": "Use only the returned private knowledge sources. If nothing was found, say so plainly.",
            },
            ensure_ascii=False,
            indent=2,
        )

    async def manage_tasks(
        self,
        action: str,
        task_key: str = "",
        task_keys: list[str] | None = None,
        summary: str = "",
        completion_summary: str = "",
        project: str = "",
        task_status: str = "",
        deadline: str | None = None,
        query: str = "",
        limit: int = 8,
        schedule_kind: str | None = None,
        due_at: str | None = None,
        timezone: str | None = None,
        recurrence: Any = None,
        auto_run: Any = None,
        job_prompt: str | None = None,
        notify_policy: str | None = None,
        session_id: str = "",
        source=None,
        activity_callback: ActivityCallback | None = None,
    ) -> str:
        await self._emit_activity(
            activity_callback,
            "routing",
            f"Routing request to task manager: {action}",
            {"tool_name": "manage_tasks"},
        )
        await self._emit_activity(
            activity_callback,
            "updating_tasks",
            f"Updating tasks with action: {action}",
            {"tool_name": "manage_tasks"},
        )
        return await self._task_manager.manage_tasks(
            action=action,
            task_key=task_key,
            task_keys=task_keys,
            summary=summary,
            completion_summary=completion_summary,
            project=project,
            task_status=task_status,
            deadline=deadline,
            query=query,
            limit=limit,
            schedule_kind=schedule_kind,
            due_at=due_at,
            timezone=timezone,
            recurrence=recurrence,
            auto_run=auto_run,
            job_prompt=job_prompt,
            notify_policy=notify_policy,
            session_id=session_id,
            source=source,
        )

    async def list_skills(
        self,
        query: str = "",
        skill_type: str = "all",
        session_id: str = "",
        source=None,
        activity_callback: ActivityCallback | None = None,
    ) -> str:
        del session_id, source
        await self._emit_activity(
            activity_callback,
            "routing",
            "Listing available skills",
            {"tool_name": "list_skills", "skill_type": skill_type},
        )
        if self._mode_manager is None:
            payload = {
                "tool": "list_skills",
                "skill_count": 0,
                "skills": [],
                "error": "skill_registry_unavailable",
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)
        skills = self._mode_manager.list_skills(skill_type=skill_type, query=query)
        payload = {
            "tool": "list_skills",
            "query": _normalize_text(query),
            "skill_type": _normalize_text(skill_type) or "all",
            "skill_count": len(skills),
            "skills": skills,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def load_skill(
        self,
        skill_id: str,
        inject_context: bool = True,
        session_id: str = "",
        source=None,
        activity_callback: ActivityCallback | None = None,
        route_context: dict[str, Any] | None = None,
    ) -> str:
        del session_id, source
        normalized_id = _normalize_text(skill_id)
        await self._emit_activity(
            activity_callback,
            "routing",
            f"Loading skill: {normalized_id}",
            {"tool_name": "load_skill", "skill_id": normalized_id},
        )
        if self._mode_manager is None:
            payload = {
                "tool": "load_skill",
                "skill_id": normalized_id,
                "loaded": False,
                "error": "skill_registry_unavailable",
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)
        skill = self._mode_manager.load_skill(normalized_id)
        if skill is None:
            payload = {
                "tool": "load_skill",
                "skill_id": normalized_id,
                "loaded": False,
                "error": "skill_not_found",
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)

        injected_into_context = False
        if inject_context and isinstance(route_context, dict):
            loaded_skills = [str(item).strip() for item in route_context.get("loaded_skills", []) if str(item).strip()]
            if skill["id"] not in loaded_skills:
                loaded_skills.append(skill["id"])
                route_context["loaded_skills"] = loaded_skills
            injected_into_context = True

        payload = {
            "tool": "load_skill",
            "skill_id": skill["id"],
            "loaded": True,
            "injected_into_context": injected_into_context,
            "skill": skill,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    async def create_skill(
        self,
        title: str,
        summary: str,
        content: str,
        skill_id: str = "",
        recommended_tools: list[str] | None = None,
        applicable_modes: list[str] | None = None,
        scenarios: list[str] | None = None,
        inject_context: bool = False,
        session_id: str = "",
        source=None,
        activity_callback: ActivityCallback | None = None,
        route_context: dict[str, Any] | None = None,
    ) -> str:
        del session_id, source
        await self._emit_activity(
            activity_callback,
            "routing",
            f"Creating reusable skill: {_normalize_text(title) or _normalize_text(skill_id)}",
            {"tool_name": "create_skill"},
        )
        if self._mode_manager is None:
            payload = {
                "tool": "create_skill",
                "created": False,
                "error": "skill_registry_unavailable",
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)
        try:
            created = self._mode_manager.create_skill(
                skill_id=skill_id,
                title=title,
                summary=summary,
                content=content,
                recommended_tools=recommended_tools,
                applicable_modes=applicable_modes,
                scenarios=scenarios,
            )
        except Exception as exc:
            payload = {
                "tool": "create_skill",
                "created": False,
                "error": str(exc),
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)

        injected_into_context = False
        if inject_context and isinstance(route_context, dict):
            loaded_skills = [str(item).strip() for item in route_context.get("loaded_skills", []) if str(item).strip()]
            if created["id"] not in loaded_skills:
                loaded_skills.append(created["id"])
                route_context["loaded_skills"] = loaded_skills
            injected_into_context = True

        payload = {
            "tool": "create_skill",
            "created": True,
            "injected_into_context": injected_into_context,
            "skill": created,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
