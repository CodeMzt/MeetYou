"""
High-level web search tools built on top of Tavily MCP and Playwright MCP.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from core.tool_runtime.models import ToolCallResult, ToolErrorCategory, ToolSourceType

logger = logging.getLogger("meetyou.web_search")

ActivityCallback = Callable[[str, str, dict[str, Any] | None], Awaitable[None]]

_DEFAULT_SEARCH_RESULTS = 5
_MAX_SEARCH_RESULTS = 8
_MIN_TAVILY_RESULTS = 5
_READ_TOP_K = 3
_SNIPPET_LIMIT = 280
_SUMMARY_LIMIT = 1200

_PLAYWRIGHT_BLOCK_PATTERNS = (
    "status of 429",
    "solvesimplechallenge",
    "our systems have detected unusual traffic",
    "unusual traffic from your computer network",
    "automated queries",
)

_NEWS_HINTS = (
    "news",
    "latest",
    "today",
    "recent",
    "breaking",
    "headline",
    "\u6700\u65b0",
    "\u4eca\u5929",
    "\u4eca\u65e5",
    "\u6700\u8fd1",
    "\u65b0\u95fb",
    "\u5934\u6761",
)


def _trim_text(text: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", (text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _looks_like_url(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value.strip())
    return bool(parsed.scheme and parsed.netloc)


def _guess_tavily_topic(query: str) -> str:
    lowered = (query or "").lower()
    if any(hint in lowered for hint in _NEWS_HINTS):
        return "news"
    return "general"


def _extract_json_payload(text: str) -> dict[str, Any] | list[Any] | None:
    raw = (text or "").strip()
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
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _extract_tavily_error(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("tavily api error:"):
        return raw
    return None


def _extract_tavily_text_payload(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None

    answer_match = re.search(r"(?im)^Answer:\s*(.+)$", raw)
    answer = answer_match.group(1).strip() if answer_match else ""

    details_section = raw.split("Detailed Results:", 1)[1] if "Detailed Results:" in raw else raw
    details_section = details_section.strip()
    results: list[dict[str, Any]] = []

    detailed_result_re = re.compile(
        r"(?ms)(?:^|\n)Title:\s*(?P<title>.*?)\nURL:\s*(?P<url>\S+)\nContent:\s*(?P<content>.*?)(?:\nRaw Content:\s*(?P<raw_content>.*?))?(?=\nTitle:\s|\Z)"
    )
    for match in detailed_result_re.finditer(details_section):
        url = match.group("url").strip()
        if not url:
            continue
        results.append(
            {
                "title": match.group("title").strip() or url,
                "url": url,
                "content": match.group("content").strip(),
                "raw_content": (match.group("raw_content") or "").strip(),
            }
        )

    if not results:
        source_result_re = re.compile(r"(?m)^-\s*(?P<title>.+?):\s*(?P<url>https?://\S+)\s*$")
        for match in source_result_re.finditer(raw):
            url = match.group("url").strip()
            if not url:
                continue
            results.append(
                {
                    "title": match.group("title").strip() or url,
                    "url": url,
                    "content": "",
                    "raw_content": "",
                }
            )

    if not results and not answer:
        return None
    return {"answer": answer, "results": results}


def _extract_tavily_payload(text: str) -> dict[str, Any] | list[Any] | None:
    payload = _extract_json_payload(text)
    if payload is not None:
        return payload
    return _extract_tavily_text_payload(text)


def _looks_like_tavily_empty_results(text: str) -> bool:
    raw = (text or "").strip().lower()
    if not raw or _extract_tavily_error(raw):
        return False
    return "detailed results:" in raw and "title:" not in raw and "url:" not in raw


def _normalize_tavily_search_payload(
    payload: dict[str, Any] | list[Any] | None,
    query: str,
    max_results: int,
) -> dict[str, Any]:
    if isinstance(payload, list):
        results = payload
        answer = ""
    elif isinstance(payload, dict):
        results = payload.get("results") or payload.get("data") or payload.get("items") or []
        answer = str(payload.get("answer") or payload.get("summary") or "")
    else:
        results = []
        answer = ""

    normalized_results: list[dict[str, Any]] = []
    for item in results[:max_results]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("link") or "").strip()
        if not url:
            continue
        normalized_results.append(
            {
                "title": str(item.get("title") or item.get("name") or url).strip(),
                "url": url,
                "snippet": _trim_text(
                    str(
                        item.get("content")
                        or item.get("snippet")
                        or item.get("description")
                        or item.get("raw_content")
                        or ""
                    ),
                    _SNIPPET_LIMIT,
                ),
                "published_date": str(
                    item.get("published_date")
                    or item.get("date")
                    or item.get("published")
                    or ""
                ).strip(),
                "score": item.get("score"),
            }
        )

    return {
        "query": query,
        "answer": _trim_text(answer, _SUMMARY_LIMIT),
        "results": normalized_results,
    }


def _normalize_tavily_extract_payload(
    payload: dict[str, Any] | list[Any] | None,
    url: str,
    fallback_title: str = "",
) -> dict[str, Any] | None:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("results") or payload.get("data") or payload.get("items") or []
        if isinstance(items, dict):
            items = [items]
    else:
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        item_url = str(item.get("url") or url).strip()
        if item_url and item_url != url:
            continue
        summary = str(
            item.get("raw_content")
            or item.get("content")
            or item.get("text")
            or item.get("excerpt")
            or ""
        )
        if not summary.strip():
            continue
        return {
            "title": str(item.get("title") or fallback_title or item_url or url).strip(),
            "url": item_url or url,
            "summary": _trim_text(summary, _SUMMARY_LIMIT),
            "reader": "tavily_extract",
        }
    return None


def _normalize_playwright_payload(text: str, url: str, fallback_title: str = "") -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None

    lowered = raw.lower()
    if any(pattern in lowered for pattern in _PLAYWRIGHT_BLOCK_PATTERNS):
        return None

    title_match = re.search(r"- Page Title:\s*(.+)", raw)
    url_match = re.search(r"- Page URL:\s*(.+)", raw)
    snapshot_match = re.search(r"### Snapshot\s*```(?:yaml)?\s*(.+?)\s*```", raw, re.DOTALL)

    summary_source = snapshot_match.group(1).strip() if snapshot_match else raw
    if not summary_source:
        return None

    return {
        "title": (title_match.group(1).strip() if title_match else fallback_title or url),
        "url": (url_match.group(1).strip() if url_match else url),
        "summary": _trim_text(summary_source, _SUMMARY_LIMIT),
        "reader": "playwright_snapshot",
    }


class WebSearchTools:
    def __init__(self, mcp_manager):
        self._mcp_manager = mcp_manager

    def _get_tavily_diagnostic(self) -> dict[str, Any]:
        getter = getattr(self._mcp_manager, "get_server_diagnostic", None)
        if callable(getter):
            payload = getter("tavily_web")
            if isinstance(payload, dict):
                return dict(payload)
        diagnostics = getattr(self._mcp_manager, "server_diagnostics", {}) or {}
        payload = diagnostics.get("tavily_web")
        return dict(payload) if isinstance(payload, dict) else {}

    def _tavily_unavailable_result(self) -> ToolCallResult:
        diagnostic = self._get_tavily_diagnostic()
        status = str(diagnostic.get("status") or "").strip()
        details: dict[str, Any] = {}

        if diagnostic:
            details["tavily_diagnostic"] = diagnostic

        if status == "requires_auth":
            missing_auth = [
                str(item).strip()
                for item in diagnostic.get("missing_auth", [])
                if str(item).strip()
            ]
            missing_auth_text = ", ".join(missing_auth) if missing_auth else "required auth env vars"
            return ToolCallResult.failure(
                tool_name="search_web",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="web_search_unavailable",
                category=ToolErrorCategory.DEPENDENCY,
                message=f"Web search is unavailable because Tavily MCP is missing auth env: {missing_auth_text}.",
                details=details,
            )

        if status == "not_enabled":
            return ToolCallResult.failure(
                tool_name="search_web",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="web_search_unavailable",
                category=ToolErrorCategory.DEPENDENCY,
                message="Web search is unavailable because Tavily MCP is disabled in Core MCP config.",
                details=details,
            )

        if status == "unavailable":
            error_text = str(diagnostic.get("error") or "").strip()
            message = "Web search is unavailable because Tavily MCP failed to initialize."
            if error_text:
                message = f"{message} Runtime error: {error_text}"
            return ToolCallResult.failure(
                tool_name="search_web",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="web_search_unavailable",
                category=ToolErrorCategory.DEPENDENCY,
                message=message,
                details=details,
                retryable=True,
            )

        return ToolCallResult.failure(
            tool_name="search_web",
            source=ToolSourceType.BUILTIN,
            action_risk="read",
            code="web_search_unavailable",
            category=ToolErrorCategory.DEPENDENCY,
            message="Web search is unavailable because Tavily MCP is not configured or TAVILY_API_KEY is missing.",
            details=details or None,
        )

    def has_tavily_search(self) -> bool:
        return "tavily-search" in self._mcp_manager.tool_map

    def has_tavily_extract(self) -> bool:
        return "tavily-extract" in self._mcp_manager.tool_map

    def has_playwright(self) -> bool:
        return "browser_navigate" in self._mcp_manager.tool_map and "browser_snapshot" in self._mcp_manager.tool_map

    async def _emit_activity(
        self,
        callback: ActivityCallback | None,
        phase: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if callback is None:
            return
        await callback(phase, content, metadata or {})

    async def _call_mcp_text(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        result = await self._mcp_manager.call_mcp_tool(tool_name, tool_args)
        return "\n".join(
            item.text
            for item in result.content
            if getattr(item, "type", "") == "text"
        ).strip()

    async def _read_url_with_fallback(
        self,
        url: str,
        *,
        title: str = "",
        activity_callback: ActivityCallback | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        extract_error: str | None = None

        if self.has_tavily_extract():
            try:
                text = await self._call_mcp_text("tavily-extract", {"urls": [url]})
                backend_error = _extract_tavily_error(text)
                if backend_error:
                    raise RuntimeError(backend_error)
                payload = _extract_tavily_payload(text)
                normalized = _normalize_tavily_extract_payload(payload, url, title)
                if normalized and normalized.get("summary"):
                    return normalized, None
                if text.strip() and not _looks_like_tavily_empty_results(text):
                    extract_error = f"Tavily extract returned an unreadable response for {url}"
                else:
                    extract_error = f"Tavily extract returned no readable content for {url}"
            except Exception as exc:
                logger.warning("Tavily extract failed for %s: %s", url, exc)
                extract_error = f"Tavily extract failed for {url}: {exc}"

        if self.has_playwright():
            try:
                await self._emit_activity(
                    activity_callback,
                    "browsing_page",
                    f"Opening page: {title or url}",
                    {"url": url},
                )
                await self._call_mcp_text("browser_navigate", {"url": url})
                snapshot_text = await self._call_mcp_text("browser_snapshot", {})
                normalized = _normalize_playwright_payload(snapshot_text, url, title)
                if normalized and normalized.get("summary"):
                    return normalized, extract_error
                if extract_error is None:
                    extract_error = f"Playwright snapshot returned no readable content for {url}"
            except Exception as exc:
                logger.warning("Playwright fallback failed for %s: %s", url, exc)
                if extract_error is None:
                    extract_error = f"Playwright fallback failed for {url}: {exc}"

        return None, extract_error

    async def search_web(
        self,
        query: str,
        max_results: int = _DEFAULT_SEARCH_RESULTS,
        session_id: str = "",
        source=None,
        activity_callback: ActivityCallback | None = None,
        source_profile: str = "",
    ) -> str | ToolCallResult:
        del session_id, source

        normalized_query = str(query or "").strip()
        if not normalized_query:
            return ToolCallResult.failure(
                tool_name="search_web",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="web_query_required",
                category=ToolErrorCategory.VALIDATION,
                message="search_web requires a non-empty query.",
            )

        if _looks_like_url(normalized_query):
            return ToolCallResult.failure(
                tool_name="search_web",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="web_direct_url_unsupported",
                category=ToolErrorCategory.VALIDATION,
                message="search_web is for discovery queries. Use read_web_page for a direct URL.",
            )

        if not self.has_tavily_search():
            return self._tavily_unavailable_result()

        try:
            safe_max_results = max(_MIN_TAVILY_RESULTS, min(int(max_results), _MAX_SEARCH_RESULTS))
        except (TypeError, ValueError):
            safe_max_results = _DEFAULT_SEARCH_RESULTS

        topic = _guess_tavily_topic(normalized_query)

        await self._emit_activity(
            activity_callback,
            "searching",
            f"Searching the web for: {normalized_query}",
            {"query": normalized_query},
        )

        try:
            search_text = await self._call_mcp_text(
                "tavily-search",
                {
                    "query": normalized_query,
                    "max_results": safe_max_results,
                    "search_depth": "advanced",
                    "topic": topic,
                    "include_raw_content": False,
                    "include_images": False,
                },
            )
        except Exception as exc:
            logger.error("Tavily search failed: %s", exc)
            return ToolCallResult.failure(
                tool_name="search_web",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="web_search_backend_failed",
                category=ToolErrorCategory.DEPENDENCY,
                message="Web search is unavailable right now.",
                details={"exception_type": type(exc).__name__, "exception_message": str(exc)},
                retryable=True,
            )

        backend_error = _extract_tavily_error(search_text)
        if backend_error:
            return ToolCallResult.failure(
                tool_name="search_web",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="web_search_backend_failed",
                category=ToolErrorCategory.DEPENDENCY,
                message="Web search is unavailable right now.",
                details={"backend_error": backend_error},
                retryable=True,
            )

        payload = _extract_tavily_payload(search_text)
        normalized = _normalize_tavily_search_payload(payload, normalized_query, safe_max_results)
        results = normalized["results"]
        if not results:
            if search_text.strip() and not _looks_like_tavily_empty_results(search_text):
                logger.warning(
                    "Unexpected Tavily search response for query %s: %s",
                    normalized_query,
                    _trim_text(search_text, 240),
                )
                return ToolCallResult.failure(
                    tool_name="search_web",
                    source=ToolSourceType.BUILTIN,
                    action_risk="read",
                    code="web_search_response_invalid",
                    category=ToolErrorCategory.DEPENDENCY,
                    message="Web search backend returned an unexpected response format.",
                    details={"response_excerpt": _trim_text(search_text, 240)},
                )
            return json.dumps(
                {
                    "query": normalized_query,
                    "search_backend": "tavily",
                    "topic": topic,
                    "source_profile": str(source_profile or ""),
                    "citation_style": "No results were found.",
                    "summary_hint": normalized["answer"],
                    "sources": [],
                },
                ensure_ascii=False,
                indent=2,
            )

        sources: list[dict[str, Any]] = []
        failures: list[str] = []

        for index, result in enumerate(results[: min(_READ_TOP_K, len(results))], start=1):
            await self._emit_activity(
                activity_callback,
                "reading_sources",
                f"Reading source {index}: {result['title']}",
                {"url": result["url"], "title": result["title"]},
            )
            detailed, failure = await self._read_url_with_fallback(
                result["url"],
                title=result["title"],
                activity_callback=activity_callback,
            )
            if failure:
                failures.append(failure)

            merged = {
                "id": index,
                "title": result["title"],
                "url": result["url"],
                "snippet": result["snippet"],
                "published_date": result["published_date"],
                "reader": "search_result",
                "summary": result["snippet"],
            }
            if detailed:
                merged["title"] = detailed.get("title") or merged["title"]
                merged["url"] = detailed.get("url") or merged["url"]
                merged["reader"] = detailed.get("reader") or merged["reader"]
                merged["summary"] = detailed.get("summary") or merged["summary"]
            sources.append(merged)

        additional_results = [
            {
                "title": item["title"],
                "url": item["url"],
                "snippet": item["snippet"],
                "published_date": item["published_date"],
            }
            for item in results[len(sources) : safe_max_results]
        ]

        return json.dumps(
            {
                "query": normalized_query,
                "search_backend": "tavily",
                "topic": topic,
                "source_profile": str(source_profile or ""),
                "citation_style": "Answer first, then cite sources inline like [1], [2] using the source ids below.",
                "summary_hint": normalized["answer"],
                "sources": sources,
                "additional_results": additional_results,
                "partial_failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        )

    async def read_web_page(
        self,
        url: str,
        session_id: str = "",
        source=None,
        activity_callback: ActivityCallback | None = None,
        source_profile: str = "",
    ) -> str | ToolCallResult:
        del session_id, source

        normalized_url = str(url or "").strip()
        if not _looks_like_url(normalized_url):
            return ToolCallResult.failure(
                tool_name="read_web_page",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="web_url_required",
                category=ToolErrorCategory.VALIDATION,
                message="read_web_page requires a direct URL.",
            )

        await self._emit_activity(
            activity_callback,
            "reading_sources",
            f"Reading page: {normalized_url}",
            {"url": normalized_url},
        )
        detailed, failure = await self._read_url_with_fallback(
            normalized_url,
            activity_callback=activity_callback,
        )

        if detailed is None:
            if failure:
                return ToolCallResult.failure(
                    tool_name="read_web_page",
                    source=ToolSourceType.BUILTIN,
                    action_risk="read",
                    code="web_page_read_failed",
                    category=ToolErrorCategory.DEPENDENCY,
                    message="Could not read the page.",
                    details={"backend_error": failure},
                    retryable=True,
                )
            return ToolCallResult.failure(
                tool_name="read_web_page",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="web_page_read_failed",
                category=ToolErrorCategory.DEPENDENCY,
                message="Could not read the page.",
                retryable=True,
            )

        payload = {
            "source_profile": str(source_profile or ""),
            "citation_style": "If you use this page in the answer, cite it as [1].",
            "source": {
                "id": 1,
                "title": detailed.get("title") or normalized_url,
                "url": detailed.get("url") or normalized_url,
                "reader": detailed.get("reader") or "unknown",
                "summary": detailed.get("summary") or "",
            },
        }
        if failure:
            payload["partial_failures"] = [failure]

        return json.dumps(payload, ensure_ascii=False, indent=2)
