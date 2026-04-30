"""
Provider-neutral search models for Core web research.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlparse, urlunparse

ActivityCallback = Callable[[str, str, dict[str, Any] | None], Awaitable[None]]


@dataclass(frozen=True)
class SearchRequest:
    query: str
    max_results: int
    quality: str
    source_profile: str = ""
    official_only: bool | None = None
    freshness: str = ""
    search_depth: str = "basic"
    topic: str = "general"
    activity_callback: ActivityCallback | None = None


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    published_at: str = ""
    score: Any = None
    provider: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    rank_score: float = 0.0


@dataclass
class SearchProviderResponse:
    provider: str
    query: str
    answer: str = ""
    results: list[SearchResult] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


class SearchProvider(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def unavailable_result(self) -> Any: ...

    async def search(self, request: SearchRequest) -> SearchProviderResponse | Any: ...


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_domain(url_or_domain: str) -> str:
    raw = str(url_or_domain or "").strip().lower()
    if raw.startswith("http://") or raw.startswith("https://"):
        raw = urlparse(raw).netloc.lower()
    if "@" in raw:
        raw = raw.rsplit("@", 1)[-1]
    if ":" in raw:
        raw = raw.split(":", 1)[0]
    return raw[4:] if raw.startswith("www.") else raw


def canonicalize_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return str(url or "").strip()
    netloc = normalize_domain(parsed.netloc)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))
