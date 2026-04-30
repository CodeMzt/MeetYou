"""
High-level web search tools built on top of Tavily MCP and Playwright MCP.
"""

from __future__ import annotations

import json
import logging
import re
import time
import asyncio
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from core.tool_runtime.models import ToolCallResult, ToolErrorCategory, ToolSourceType
from tools.search_providers import (
    SearchProvider,
    SearchProviderResponse,
    SearchRequest,
    SearchResult,
    canonicalize_url,
    normalize_domain,
    utc_timestamp,
)

logger = logging.getLogger("meetyou.web_search")

ActivityCallback = Callable[[str, str, dict[str, Any] | None], Awaitable[None]]

_DEFAULT_SEARCH_RESULTS = 5
_MAX_SEARCH_RESULTS = 8
_READ_TOP_K = 3
_FAST_READ_TOP_K = 1
_BALANCED_READ_TOP_K = 2
_SNIPPET_LIMIT = 280
_SUMMARY_LIMIT = 1200
_DEFAULT_MCP_TIMEOUT_SECONDS = 10
_DEFAULT_BROWSER_TIMEOUT_SECONDS = 30
_SEARCH_CACHE_TTL_SECONDS = 300
_EXTRACT_CACHE_TTL_SECONDS = 600
_CACHE_MAX_ITEMS = 128
_TAVILY_SEARCH_TOOL_CANDIDATES = ("tavily-search", "tavily_search")
_TAVILY_EXTRACT_TOOL_CANDIDATES = ("tavily-extract", "tavily_extract")

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
_DEEP_SEARCH_HINTS = (
    "research",
    "source",
    "sources",
    "evidence",
    "verify",
    "investigate",
    "\u7814\u7a76",
    "\u8bc1\u636e",
    "\u6838\u5b9e",
    "\u67e5\u8bc1",
)


def _bounded_int(value: Any, *, default: int, minimum: int = 1, maximum: int = _MAX_SEARCH_RESULTS) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))


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


def _normalize_tool_name(value: str) -> str:
    return re.sub(r"[-_\s]+", "_", str(value or "").strip().lower())


def _guess_tavily_topic(query: str) -> str:
    lowered = (query or "").lower()
    if any(hint in lowered for hint in _NEWS_HINTS):
        return "news"
    return "general"


def _normalize_quality(value: str, *, query: str, source_profile: str = "") -> str:
    requested = str(value or "adaptive").strip().lower()
    if requested in {"fast", "balanced", "deep"}:
        return requested
    lowered = f"{query or ''} {source_profile or ''}".lower()
    if "research" in lowered or any(hint in lowered for hint in _DEEP_SEARCH_HINTS):
        return "deep"
    if any(hint in lowered for hint in _NEWS_HINTS):
        return "deep"
    return "balanced"


def _search_depth_for_quality(quality: str) -> str:
    return "advanced" if quality == "deep" else "basic"


def _read_top_k_for_quality(quality: str, max_results: int) -> int:
    if quality == "fast":
        return min(_FAST_READ_TOP_K, max_results)
    if quality == "deep":
        return min(_READ_TOP_K, max_results)
    return min(_BALANCED_READ_TOP_K, max_results)


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


def _numeric_score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _primary_domain_hint(domain: str, source_profile: str = "") -> bool:
    normalized = normalize_domain(domain)
    if not normalized:
        return False
    official_domains = {
        "github.com",
        "docs.python.org",
        "developer.mozilla.org",
        "w3.org",
        "whatwg.org",
        "ietf.org",
        "sec.gov",
        "edgar.sec.gov",
        "federalreserve.gov",
        "fred.stlouisfed.org",
        "worldbank.org",
        "who.int",
        "fda.gov",
        "pubmed.ncbi.nlm.nih.gov",
        "arxiv.org",
        "doi.org",
        "crossref.org",
        "nvd.nist.gov",
        "cisa.gov",
    }
    if normalized in official_domains or any(normalized.endswith(f".{item}") for item in official_domains):
        return True
    if source_profile == "policy_cn" and (normalized == "gov.cn" or normalized.endswith(".gov.cn")):
        return True
    return False


def _result_rank_score(result: SearchResult, *, source_profile: str = "", official_only: bool | None = None) -> float:
    domain = normalize_domain(result.url)
    score = _numeric_score(result.score)
    if _primary_domain_hint(domain, source_profile):
        score += 2.0
    if bool(official_only) and _primary_domain_hint(domain, source_profile):
        score += 1.0
    if result.published_at:
        score += 0.15
    if result.snippet:
        score += 0.05
    return score


def _evidence_from_source(source: dict[str, Any]) -> dict[str, Any]:
    source_id = source.get("source_id") or source.get("id")
    title = _trim_text(str(source.get("title") or source.get("url") or ""), 180)
    return {
        "source_id": source_id,
        "title": title,
        "url": str(source.get("url") or ""),
        "canonical_url": str(source.get("canonical_url") or ""),
        "domain": str(source.get("domain") or ""),
        "provider": str(source.get("provider") or ""),
        "published_at": str(source.get("published_at") or source.get("published_date") or ""),
        "retrieved_at": str(source.get("retrieved_at") or ""),
        "source_profile": str(source.get("source_profile") or ""),
        "is_primary_source": bool(source.get("is_primary_source", False)),
        "credibility": str(source.get("credibility") or ""),
        "rank_score": source.get("rank_score", 0.0),
        "excerpt": _trim_text(source.get("summary") or source.get("snippet"), 320),
        "verification_status": str(source.get("verification_status") or ""),
        "citation": f"[{source_id}] {title}".strip(),
    }


class TavilySearchProvider:
    name = "tavily"

    def __init__(self, owner: "WebSearchTools"):
        self._owner = owner

    def is_available(self) -> bool:
        return self._owner.has_tavily_search()

    def unavailable_result(self) -> ToolCallResult:
        return self._owner._tavily_unavailable_result()

    async def search(self, request: SearchRequest) -> SearchProviderResponse | ToolCallResult:
        search_tool_name = self._owner._resolve_tavily_search_tool_name()
        if not search_tool_name:
            return self.unavailable_result()

        try:
            search_started_at = time.perf_counter()
            search_args = {
                "query": request.query,
                "max_results": request.max_results,
                "search_depth": request.search_depth,
                "topic": request.topic,
                "include_raw_content": False,
                "include_images": False,
            }
            cache_key = (
                "search",
                search_tool_name,
                request.query.lower(),
                request.max_results,
                request.search_depth,
                request.topic,
            )
            search_text = self._owner._get_cached(cache_key, _SEARCH_CACHE_TTL_SECONDS)
            was_cached = search_text is not None
            if search_text is None:
                search_text = await self._owner._call_mcp_text(search_tool_name, search_args)
                self._owner._set_cached(cache_key, search_text)
            logger.debug(
                "Web search provider completed provider=%s query=%r depth=%s elapsed_ms=%s cached=%s",
                self.name,
                request.query,
                request.search_depth,
                int((time.perf_counter() - search_started_at) * 1000),
                was_cached,
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
        normalized = _normalize_tavily_search_payload(payload, request.query, request.max_results)
        results = [
            SearchResult(
                title=item["title"],
                url=item["url"],
                snippet=item.get("snippet", ""),
                published_at=item.get("published_date", ""),
                score=item.get("score"),
                provider=self.name,
                raw=dict(item),
            )
            for item in normalized["results"]
        ]
        if not results and search_text.strip() and not _looks_like_tavily_empty_results(search_text):
            logger.warning(
                "Unexpected Tavily search response for query %s: %s",
                request.query,
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
        return SearchProviderResponse(
            provider=self.name,
            query=request.query,
            answer=normalized["answer"],
            results=results,
            diagnostics={
                "topic": request.topic,
                "search_depth": request.search_depth,
                "cached": was_cached,
                "tool_name": search_tool_name,
            },
        )


class SearchOrchestrator:
    def __init__(self, owner: "WebSearchTools", providers: list[SearchProvider]):
        self._owner = owner
        self._providers = list(providers)

    def _fuse_results(self, responses: list[SearchProviderResponse], request: SearchRequest) -> list[SearchResult]:
        by_url: dict[str, SearchResult] = {}
        for response in responses:
            for result in response.results:
                canonical = canonicalize_url(result.url)
                if not canonical:
                    continue
                result.provider = result.provider or response.provider
                result.rank_score = _result_rank_score(
                    result,
                    source_profile=request.source_profile,
                    official_only=request.official_only,
                )
                existing = by_url.get(canonical)
                if existing is None or result.rank_score > existing.rank_score:
                    by_url[canonical] = result
                elif existing and not existing.snippet and result.snippet:
                    existing.snippet = result.snippet
        ordered = list(by_url.values())
        ordered.sort(key=lambda item: (item.rank_score, _numeric_score(item.score)), reverse=True)
        return ordered[: request.max_results]

    def _source_payload_from_result(
        self,
        index: int,
        result: SearchResult,
        request: SearchRequest,
        *,
        detailed: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = str((detailed or {}).get("url") or result.url)
        title = str((detailed or {}).get("title") or result.title or url)
        summary = str((detailed or {}).get("summary") or result.snippet or "")
        reader = str((detailed or {}).get("reader") or "search_result")
        domain = normalize_domain(url)
        is_primary = _primary_domain_hint(domain, request.source_profile)
        if request.official_only is True and not is_primary:
            credibility = "unverified_official_candidate"
        else:
            credibility = "primary" if is_primary else "secondary"
        verification_status = "read" if detailed and detailed.get("summary") else "search_result_only"
        return {
            "id": index,
            "source_id": index,
            "title": title,
            "url": url,
            "canonical_url": canonicalize_url(url),
            "domain": domain,
            "snippet": result.snippet,
            "published_date": result.published_at,
            "published_at": result.published_at,
            "retrieved_at": utc_timestamp(),
            "reader": reader,
            "provider": result.provider,
            "summary": summary,
            "excerpt": _trim_text(summary, 320),
            "source_profile": request.source_profile,
            "is_primary_source": is_primary,
            "credibility": credibility,
            "rank_score": round(float(result.rank_score or 0.0), 4),
            "verification_status": verification_status,
        }

    async def search(self, request: SearchRequest) -> str | ToolCallResult:
        responses: list[SearchProviderResponse] = []
        provider_failures: list[str] = []
        last_failure: ToolCallResult | None = None

        for provider in self._providers:
            if not provider.is_available():
                unavailable = provider.unavailable_result()
                if isinstance(unavailable, ToolCallResult):
                    last_failure = unavailable
                    provider_failures.append(_trim_text(unavailable.error.message if unavailable.error else provider.name, 240))
                continue
            provider_response = await provider.search(request)
            if isinstance(provider_response, ToolCallResult):
                last_failure = provider_response
                provider_failures.append(_trim_text(provider_response.error.message if provider_response.error else provider.name, 240))
                continue
            responses.append(provider_response)
            if request.quality == "fast":
                break

        if not responses:
            return last_failure or ToolCallResult.failure(
                tool_name="search_web",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="web_search_unavailable",
                category=ToolErrorCategory.DEPENDENCY,
                message="Web search is unavailable because no search provider is configured.",
            )

        results = self._fuse_results(responses, request)
        provider_backends = [response.provider for response in responses]
        summary_hint = next((response.answer for response in responses if response.answer), "")

        if not results:
            return json.dumps(
                {
                    "query": request.query,
                    "search_backend": provider_backends[0] if len(provider_backends) == 1 else "multi_provider",
                    "provider_backends": provider_backends,
                    "topic": request.topic,
                    "quality": request.quality,
                    "search_depth": request.search_depth,
                    "source_profile": request.source_profile,
                    "official_only": request.official_only,
                    "freshness": request.freshness,
                    "citation_style": "No results were found.",
                    "summary_hint": summary_hint,
                    "sources": [],
                    "evidence_ledger": [],
                    "provider_failures": provider_failures,
                },
                ensure_ascii=False,
                indent=2,
            )

        read_top_k = _read_top_k_for_quality(request.quality, request.max_results)
        source_candidates = results[:read_top_k]
        sources: list[dict[str, Any]] = []
        failures: list[str] = list(provider_failures)

        if source_candidates:
            await self._owner._emit_activity(
                request.activity_callback,
                "reading_sources",
                f"Reading {len(source_candidates)} source(s)",
                {"count": len(source_candidates)},
            )

        async def read_source(index: int, result: SearchResult) -> tuple[int, dict[str, Any], str | None]:
            detailed, failure = await self._owner._read_url_with_fallback(
                result.url,
                title=result.title,
                activity_callback=request.activity_callback,
                allow_playwright=index == 1,
                extract_timeout_seconds=self._owner._extract_timeout_seconds,
            )
            return index, self._source_payload_from_result(index, result, request, detailed=detailed), failure

        if source_candidates:
            read_results = await asyncio.gather(
                *(read_source(index, result) for index, result in enumerate(source_candidates, start=1)),
                return_exceptions=True,
            )
            for item in sorted(
                (entry for entry in read_results if not isinstance(entry, Exception)),
                key=lambda entry: entry[0],
            ):
                _, merged, failure = item
                if failure:
                    failures.append(failure)
                sources.append(merged)
            for item in read_results:
                if isinstance(item, Exception):
                    failures.append(f"Source read failed: {item}")

        additional_results = [
            {
                "title": item.title,
                "url": item.url,
                "canonical_url": canonicalize_url(item.url),
                "domain": normalize_domain(item.url),
                "snippet": item.snippet,
                "published_date": item.published_at,
                "published_at": item.published_at,
                "provider": item.provider,
                "rank_score": round(float(item.rank_score or 0.0), 4),
                "verification_status": "search_result_only",
            }
            for item in results[read_top_k : request.max_results]
        ]
        evidence_ledger = [_evidence_from_source(source) for source in sources]

        return json.dumps(
            {
                "query": request.query,
                "search_backend": provider_backends[0] if len(provider_backends) == 1 else "multi_provider",
                "provider_backends": provider_backends,
                "provider_diagnostics": [response.diagnostics for response in responses],
                "topic": request.topic,
                "quality": request.quality,
                "search_depth": request.search_depth,
                "source_profile": request.source_profile,
                "official_only": request.official_only,
                "freshness": request.freshness,
                "citation_style": "Answer first, then cite only evidence_ledger source ids inline like [1], [2].",
                "summary_hint": summary_hint,
                "sources": sources,
                "evidence_ledger": evidence_ledger,
                "evidence": evidence_ledger,
                "additional_results": additional_results,
                "partial_failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        )


class WebSearchTools:
    def __init__(self, mcp_manager, config=None):
        self._mcp_manager = mcp_manager
        self._cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._playwright_lock = asyncio.Lock()
        self._parallel_reads = _bounded_int(
            getattr(config, "get", lambda key, default=None: default)("web_search_parallel_reads", 3) if config is not None else 3,
            default=3,
            minimum=1,
            maximum=6,
        )
        self._extract_timeout_seconds = _bounded_int(
            getattr(config, "get", lambda key, default=None: default)("web_search_extract_timeout_seconds", _DEFAULT_MCP_TIMEOUT_SECONDS) if config is not None else _DEFAULT_MCP_TIMEOUT_SECONDS,
            default=_DEFAULT_MCP_TIMEOUT_SECONDS,
            minimum=1,
            maximum=30,
        )
        self._default_quality = str(
            getattr(config, "get", lambda key, default=None: default)("web_search_quality", "fast") if config is not None else "fast"
        ).strip() or "fast"
        self._extract_semaphore = asyncio.Semaphore(self._parallel_reads)
        self._search_providers: list[SearchProvider] = [TavilySearchProvider(self)]
        self._search_orchestrator = SearchOrchestrator(self, self._search_providers)

    def _get_cached(self, key: tuple[Any, ...], ttl_seconds: int) -> Any | None:
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is None:
            return None
        stored_at, value = cached
        if now - stored_at > ttl_seconds:
            self._cache.pop(key, None)
            return None
        return value

    def _set_cached(self, key: tuple[Any, ...], value: Any) -> None:
        if len(self._cache) >= _CACHE_MAX_ITEMS:
            oldest_key = min(self._cache, key=lambda item: self._cache[item][0])
            self._cache.pop(oldest_key, None)
        self._cache[key] = (time.monotonic(), value)

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
        resolved_search_tool = self._resolve_tavily_search_tool_name()
        details: dict[str, Any] = {}

        if diagnostic:
            details["tavily_diagnostic"] = diagnostic

        if status == "enabled" and not resolved_search_tool:
            available_tool_names = [
                str(item).strip()
                for item in diagnostic.get("tool_names", [])
                if str(item).strip()
            ]
            if available_tool_names:
                details["available_tool_names"] = available_tool_names
            return ToolCallResult.failure(
                tool_name="search_web",
                source=ToolSourceType.BUILTIN,
                action_risk="read",
                code="web_search_unavailable",
                category=ToolErrorCategory.DEPENDENCY,
                message=(
                    "Web search is unavailable because Tavily MCP initialized, "
                    "but it did not expose a supported search tool."
                ),
                details=details or None,
            )

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
        return self._resolve_tavily_search_tool_name() is not None

    def has_tavily_extract(self) -> bool:
        return self._resolve_tavily_extract_tool_name() is not None

    def has_playwright(self) -> bool:
        return "browser_navigate" in self._mcp_manager.tool_map and "browser_snapshot" in self._mcp_manager.tool_map

    def _get_server_tool_names(self, server_name: str) -> list[str]:
        tool_map = getattr(self._mcp_manager, "tool_map", {}) or {}
        return [
            str(tool_name).strip()
            for tool_name, mapped_server in tool_map.items()
            if str(tool_name).strip() and str(mapped_server or "").strip() == server_name
        ]

    def _resolve_server_tool_name(
        self,
        server_name: str,
        *,
        exact_candidates: tuple[str, ...],
        keyword: str,
    ) -> str | None:
        tool_names = self._get_server_tool_names(server_name)
        if not tool_names:
            return None
        candidate_map = {
            _normalize_tool_name(candidate): candidate
            for candidate in exact_candidates
            if str(candidate).strip()
        }
        for tool_name in tool_names:
            if _normalize_tool_name(tool_name) in candidate_map:
                return tool_name
        normalized_keyword = _normalize_tool_name(keyword)
        for tool_name in tool_names:
            if normalized_keyword in _normalize_tool_name(tool_name):
                return tool_name
        return None

    def _resolve_tavily_search_tool_name(self) -> str | None:
        return self._resolve_server_tool_name(
            "tavily_web",
            exact_candidates=_TAVILY_SEARCH_TOOL_CANDIDATES,
            keyword="search",
        )

    def _resolve_tavily_extract_tool_name(self) -> str | None:
        return self._resolve_server_tool_name(
            "tavily_web",
            exact_candidates=_TAVILY_EXTRACT_TOOL_CANDIDATES,
            keyword="extract",
        )

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

    async def _call_mcp_text(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        timeout_seconds: int = _DEFAULT_MCP_TIMEOUT_SECONDS,
    ) -> str:
        result = await asyncio.wait_for(
            self._mcp_manager.call_mcp_tool(tool_name, tool_args),
            timeout=max(int(timeout_seconds or _DEFAULT_MCP_TIMEOUT_SECONDS), 1),
        )
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
        allow_playwright: bool = True,
        extract_timeout_seconds: int = _DEFAULT_MCP_TIMEOUT_SECONDS,
    ) -> tuple[dict[str, Any] | None, str | None]:
        extract_error: str | None = None

        if self.has_tavily_extract():
            extract_tool_name = self._resolve_tavily_extract_tool_name()
            try:
                if not extract_tool_name:
                    raise RuntimeError("Tavily extract tool is unavailable")
                cache_key = ("extract", extract_tool_name, url)
                text = self._get_cached(cache_key, _EXTRACT_CACHE_TTL_SECONDS)
                if text is None:
                    async with self._extract_semaphore:
                        text = await self._call_mcp_text(
                            extract_tool_name,
                            {"urls": [url]},
                            timeout_seconds=extract_timeout_seconds,
                        )
                    self._set_cached(cache_key, text)
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

        if allow_playwright and self.has_playwright():
            try:
                async with self._playwright_lock:
                    await self._emit_activity(
                        activity_callback,
                        "browsing_page",
                        f"Opening page: {title or url}",
                        {"url": url},
                    )
                    await self._call_mcp_text(
                        "browser_navigate",
                        {"url": url},
                        timeout_seconds=_DEFAULT_BROWSER_TIMEOUT_SECONDS,
                    )
                    snapshot_text = await self._call_mcp_text(
                        "browser_snapshot",
                        {},
                        timeout_seconds=_DEFAULT_BROWSER_TIMEOUT_SECONDS,
                    )
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
        quality: str = "",
        official_only: bool | None = None,
        freshness: str = "",
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

        safe_max_results = _bounded_int(max_results, default=_DEFAULT_SEARCH_RESULTS)
        resolved_quality = _normalize_quality(quality or self._default_quality, query=normalized_query, source_profile=source_profile)
        search_depth = _search_depth_for_quality(resolved_quality)
        topic = _guess_tavily_topic(normalized_query)

        await self._emit_activity(
            activity_callback,
            "searching",
            f"Searching the web for: {normalized_query}",
            {"query": normalized_query},
        )

        request = SearchRequest(
            query=normalized_query,
            max_results=safe_max_results,
            quality=resolved_quality,
            source_profile=str(source_profile or ""),
            official_only=official_only,
            freshness=str(freshness or ""),
            search_depth=search_depth,
            topic=topic,
            activity_callback=activity_callback,
        )
        return await self._search_orchestrator.search(request)

    async def read_web_page(
        self,
        url: str,
        session_id: str = "",
        source=None,
        activity_callback: ActivityCallback | None = None,
        source_profile: str = "",
        freshness: str = "",
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

        source_payload = {
            "id": 1,
            "source_id": 1,
            "title": detailed.get("title") or normalized_url,
            "url": detailed.get("url") or normalized_url,
            "canonical_url": canonicalize_url(detailed.get("url") or normalized_url),
            "domain": normalize_domain(detailed.get("url") or normalized_url),
            "reader": detailed.get("reader") or "unknown",
            "provider": str(detailed.get("reader") or "unknown").split("_", 1)[0],
            "summary": detailed.get("summary") or "",
            "excerpt": _trim_text(detailed.get("summary") or "", 320),
            "published_date": "",
            "published_at": "",
            "retrieved_at": utc_timestamp(),
            "source_profile": str(source_profile or ""),
            "freshness": str(freshness or ""),
            "is_primary_source": _primary_domain_hint(detailed.get("url") or normalized_url, str(source_profile or "")),
            "credibility": "primary" if _primary_domain_hint(detailed.get("url") or normalized_url, str(source_profile or "")) else "secondary",
            "rank_score": 0.0,
            "verification_status": "read",
        }
        payload = {
            "source_profile": str(source_profile or ""),
            "freshness": str(freshness or ""),
            "citation_style": "If you use this page in the answer, cite it as [1].",
            "source": source_payload,
            "evidence_ledger": [_evidence_from_source(source_payload)],
            "evidence": [_evidence_from_source(source_payload)],
        }
        if failure:
            payload["partial_failures"] = [failure]

        return json.dumps(payload, ensure_ascii=False, indent=2)
