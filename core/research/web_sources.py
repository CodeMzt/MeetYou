from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen


FetchWebSource = Callable[..., Any]

_MAX_FETCH_BYTES = 768 * 1024
_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style|noscript|svg)\b[^>]*>.*?</\1>")
_COMMENT_RE = re.compile(r"(?s)<!--.*?-->")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_TITLE_RE = re.compile(r"(?is)<title\b[^>]*>(.*?)</title>")


@dataclass(frozen=True, slots=True)
class WebSourceSeed:
    url: str
    title: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, *, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()
    return text[:limit]


def _normalize_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return raw


def _default_fetch(url: str, *, timeout: float = 8.0) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "text/html, text/plain, application/xhtml+xml;q=0.9, */*;q=0.5",
            "User-Agent": "MeetYouResearch/0.1 (+https://github.com/CodeMzt/MeetYou)",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(_MAX_FETCH_BYTES + 1)[:_MAX_FETCH_BYTES]
        return {
            "url": response.geturl() or url,
            "content_type": response.headers.get("content-type", ""),
            "content": raw.decode("utf-8", errors="replace"),
        }


def _fetch(fetcher: FetchWebSource | None, url: str, *, timeout: float) -> Any:
    active_fetcher = fetcher or _default_fetch
    try:
        return active_fetcher(url, timeout=timeout)
    except TypeError:
        return active_fetcher(url)


def _html_title(raw: str) -> str:
    match = _TITLE_RE.search(raw or "")
    return _clean_text(match.group(1), limit=240) if match else ""


def _html_text(raw: str) -> str:
    without_blocks = _SCRIPT_STYLE_RE.sub(" ", str(raw or ""))
    without_comments = _COMMENT_RE.sub(" ", without_blocks)
    without_tags = _TAG_RE.sub(" ", without_comments)
    return _clean_text(without_tags)


def _payload_to_text(payload: Any, *, requested_url: str, seed_title: str) -> tuple[str, str, str, str]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, dict):
        final_url = _normalize_url(payload.get("url")) or requested_url
        title = _clean_text(payload.get("title") or seed_title, limit=240)
        content_type = _clean_text(payload.get("content_type") or payload.get("mime_type") or "", limit=120)
        raw_text = payload.get("text") or payload.get("content") or payload.get("summary") or payload.get("snippet") or payload.get("html") or ""
        raw = str(raw_text or "")
    else:
        final_url = requested_url
        title = _clean_text(seed_title, limit=240)
        content_type = ""
        raw = str(payload or "")

    looks_html = "html" in content_type.lower() or bool(re.search(r"(?is)<html\b|<body\b|<p\b|<title\b", raw))
    if looks_html:
        title = title or _html_title(raw)
        text = _html_text(raw)
    else:
        text = _clean_text(raw)
    return final_url, title, content_type, text


class WebSourceRegistry:
    """Read-only direct web-page adapter for V5 research gathering."""

    SUPPORTED_ADAPTER = "web"

    @staticmethod
    def normalize_url_entries(entries: Any) -> list[WebSourceSeed]:
        if entries is None:
            return []
        if isinstance(entries, (str, bytes)):
            entries = [entries]
        if not isinstance(entries, (list, tuple)):
            return []
        seeds: list[WebSourceSeed] = []
        for item in entries:
            if isinstance(item, dict):
                url = _normalize_url(item.get("url") or item.get("href"))
                title = _clean_text(item.get("title") or item.get("name") or "", limit=240)
            else:
                url = _normalize_url(item)
                title = ""
            if url:
                seeds.append(WebSourceSeed(url=url, title=title))
        return seeds

    @classmethod
    def fetch_evidence(
        cls,
        entries: Any,
        *,
        fetcher: FetchWebSource | None = None,
        timeout: float = 8.0,
        source_id_start: int = 1,
        limit: int = 5,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        evidence: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        next_source_id = int(source_id_start or 1)
        seeds = cls.normalize_url_entries(entries)[: max(0, int(limit or 0))]
        for seed in seeds:
            try:
                final_url, title, content_type, text = _payload_to_text(
                    _fetch(fetcher, seed.url, timeout=timeout),
                    requested_url=seed.url,
                    seed_title=seed.title,
                )
                if not text:
                    raise ValueError("page contained no readable text")
                evidence.append(
                    {
                        "source_id": str(next_source_id),
                        "source_type": "web_page",
                        "adapter": cls.SUPPORTED_ADAPTER,
                        "title": title or final_url,
                        "url": final_url,
                        "snippet": text,
                        "content_type": content_type,
                        "reader": "core.web_source.v1",
                        "verification_status": "fetched",
                        "prompt_injection_mitigation": "html script/style/svg/noscript blocks removed before excerpting",
                        "fetched_at": _now_iso(),
                    }
                )
                next_source_id += 1
            except Exception as exc:  # noqa: BLE001 - one bad page should not fail the whole research run.
                errors.append(
                    {
                        "adapter": cls.SUPPORTED_ADAPTER,
                        "url": seed.url,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
        return evidence, errors
