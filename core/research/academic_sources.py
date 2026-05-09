from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from xml.etree import ElementTree


FetchAcademicSource = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class AcademicAdapterQuery:
    adapter: str
    query_url: str
    source_type: str = "academic_index"

    def to_dict(self) -> dict[str, str]:
        return {
            "adapter": self.adapter,
            "query_url": self.query_url,
            "source_type": self.source_type,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, *, limit: int = 600) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _strip_html(value: Any) -> str:
    return re.sub(r"<[^>]+>", " ", str(value or ""))


def _default_fetch(url: str, *, timeout: float = 8.0) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/json, application/atom+xml, text/xml;q=0.9, */*;q=0.8",
            "User-Agent": "MeetYouResearch/0.1 (+https://github.com/CodeMzt/MeetYou)",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _fetch(fetcher: FetchAcademicSource | None, url: str, *, timeout: float) -> Any:
    active_fetcher = fetcher or _default_fetch
    try:
        return active_fetcher(url, timeout=timeout)
    except TypeError:
        return active_fetcher(url)


def _json_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return json.loads(str(raw or "{}"))


def _authors_from_names(values: list[Any]) -> list[str]:
    result: list[str] = []
    for item in values:
        if isinstance(item, str):
            name = _clean_text(item, limit=120)
        elif isinstance(item, dict):
            name = _clean_text(item.get("name") or item.get("display_name") or "", limit=120)
        else:
            name = ""
        if name:
            result.append(name)
    return result[:8]


def _reconstruct_openalex_abstract(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    words: list[tuple[int, str]] = []
    for word, positions in value.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            try:
                words.append((int(position), str(word)))
            except (TypeError, ValueError):
                continue
    return " ".join(word for _, word in sorted(words))


def _parse_arxiv(raw: Any, *, limit: int) -> list[dict[str, Any]]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    root = ElementTree.fromstring(str(raw or ""))
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    records: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns)[:limit]:
        title = _clean_text(entry.findtext("atom:title", default="", namespaces=ns), limit=240)
        url = _clean_text(entry.findtext("atom:id", default="", namespaces=ns), limit=400)
        authors = [
            _clean_text(author.findtext("atom:name", default="", namespaces=ns), limit=120)
            for author in entry.findall("atom:author", ns)
        ]
        summary = _clean_text(entry.findtext("atom:summary", default="", namespaces=ns))
        if title or url:
            records.append(
                {
                    "title": title or url,
                    "url": url,
                    "snippet": summary,
                    "authors": [item for item in authors if item][:8],
                    "published_at": _clean_text(entry.findtext("atom:published", default="", namespaces=ns), limit=80),
                }
            )
    return records


def _parse_openalex(raw: Any, *, limit: int) -> list[dict[str, Any]]:
    payload = _json_payload(raw)
    records: list[dict[str, Any]] = []
    for item in list(payload.get("results") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        authors = []
        for authorship in item.get("authorships") or []:
            if isinstance(authorship, dict):
                author = authorship.get("author") or {}
                if isinstance(author, dict):
                    authors.append(author.get("display_name") or "")
        location = item.get("primary_location") or {}
        source = location.get("source") if isinstance(location, dict) else {}
        venue = source.get("display_name") if isinstance(source, dict) else ""
        abstract = item.get("abstract") or _reconstruct_openalex_abstract(item.get("abstract_inverted_index"))
        title = _clean_text(item.get("title") or item.get("display_name") or item.get("id"), limit=240)
        url = _clean_text(item.get("doi") or item.get("id") or "", limit=400)
        if title or url:
            records.append(
                {
                    "title": title or url,
                    "url": url,
                    "snippet": _clean_text(abstract),
                    "authors": _authors_from_names(authors),
                    "year": item.get("publication_year"),
                    "venue": _clean_text(venue, limit=160),
                }
            )
    return records


def _parse_crossref(raw: Any, *, limit: int) -> list[dict[str, Any]]:
    payload = _json_payload(raw)
    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    records: list[dict[str, Any]] = []
    for item in list(message.get("items") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        title_values = item.get("title") if isinstance(item.get("title"), list) else []
        title = _clean_text(title_values[0] if title_values else item.get("DOI") or "", limit=240)
        doi = _clean_text(item.get("DOI") or "", limit=240)
        authors = []
        for author in item.get("author") or []:
            if isinstance(author, dict):
                authors.append(" ".join(part for part in [author.get("given"), author.get("family")] if part))
        date_parts = ((item.get("published-print") or item.get("published-online") or {}).get("date-parts") or [[]])
        year = date_parts[0][0] if date_parts and date_parts[0] else None
        if title or doi:
            records.append(
                {
                    "title": title or doi,
                    "url": f"https://doi.org/{doi}" if doi else _clean_text(item.get("URL") or "", limit=400),
                    "snippet": _clean_text(_strip_html(item.get("abstract") or "")),
                    "authors": _authors_from_names(authors),
                    "year": year,
                    "venue": _clean_text((item.get("container-title") or [""])[0], limit=160),
                }
            )
    return records


def _parse_semantic_scholar(raw: Any, *, limit: int) -> list[dict[str, Any]]:
    payload = _json_payload(raw)
    records: list[dict[str, Any]] = []
    for item in list(payload.get("data") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title") or item.get("paperId") or "", limit=240)
        authors = [author.get("name") for author in item.get("authors") or [] if isinstance(author, dict)]
        url = _clean_text(item.get("url") or "", limit=400)
        external = item.get("externalIds") if isinstance(item.get("externalIds"), dict) else {}
        if not url and external.get("DOI"):
            url = f"https://doi.org/{external['DOI']}"
        if title or url:
            records.append(
                {
                    "title": title or url,
                    "url": url,
                    "snippet": _clean_text(item.get("abstract") or ""),
                    "authors": _authors_from_names(authors),
                    "year": item.get("year"),
                    "venue": _clean_text(item.get("venue") or "", limit=160),
                }
            )
    return records


class AcademicSourceRegistry:
    """Read-only academic source adapter registry for V5 research planning and gathering."""

    DEFAULT_ADAPTERS = ("arxiv", "openalex", "crossref", "semantic_scholar")
    SUPPORTED_ADAPTERS = frozenset(DEFAULT_ADAPTERS)

    @staticmethod
    def normalize_adapter(adapter: str) -> str:
        normalized = str(adapter or "").strip().lower()
        if normalized == "semanticscholar":
            return "semantic_scholar"
        return normalized

    @classmethod
    def build_queries(
        cls,
        query: str,
        *,
        adapters: list[str] | tuple[str, ...] | None = None,
        limit: int = 10,
    ) -> list[AcademicAdapterQuery]:
        normalized = str(query or "").strip()
        if not normalized:
            return []
        safe_query = quote_plus(normalized)
        bounded_limit = max(1, min(int(limit or 10), 50))
        selected_adapters = cls.DEFAULT_ADAPTERS if adapters is None else adapters
        if isinstance(selected_adapters, str):
            selected_adapters = [selected_adapters]
        selected = [cls.normalize_adapter(item) for item in selected_adapters]
        result: list[AcademicAdapterQuery] = []
        for adapter in selected:
            if adapter == "arxiv":
                result.append(
                    AcademicAdapterQuery(
                        adapter="arxiv",
                        query_url=f"https://export.arxiv.org/api/query?search_query=all:{safe_query}&start=0&max_results={bounded_limit}",
                    )
                )
            elif adapter == "openalex":
                result.append(
                    AcademicAdapterQuery(
                        adapter="openalex",
                        query_url=f"https://api.openalex.org/works?search={safe_query}&per-page={bounded_limit}",
                    )
                )
            elif adapter == "crossref":
                result.append(
                    AcademicAdapterQuery(
                        adapter="crossref",
                        query_url=f"https://api.crossref.org/works?query={safe_query}&rows={bounded_limit}",
                    )
                )
            elif adapter == "semantic_scholar":
                result.append(
                    AcademicAdapterQuery(
                        adapter="semantic_scholar",
                        query_url=f"https://api.semanticscholar.org/graph/v1/paper/search?query={safe_query}&limit={bounded_limit}&fields=title,authors,year,venue,url,externalIds,abstract",
                    )
                )
        return result

    @classmethod
    def parse_results(cls, adapter: str, raw: Any, *, limit: int = 10) -> list[dict[str, Any]]:
        normalized = cls.normalize_adapter(adapter)
        bounded_limit = max(1, min(int(limit or 10), 50))
        if normalized == "arxiv":
            return _parse_arxiv(raw, limit=bounded_limit)
        if normalized == "openalex":
            return _parse_openalex(raw, limit=bounded_limit)
        if normalized == "crossref":
            return _parse_crossref(raw, limit=bounded_limit)
        if normalized == "semantic_scholar":
            return _parse_semantic_scholar(raw, limit=bounded_limit)
        return []

    @classmethod
    def fetch_evidence(
        cls,
        query: str,
        *,
        adapters: list[str] | tuple[str, ...] | None = None,
        limit: int = 10,
        fetcher: FetchAcademicSource | None = None,
        timeout: float = 8.0,
        source_id_start: int = 1,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        evidence: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        next_source_id = int(source_id_start or 1)
        queries = cls.build_queries(query, adapters=adapters, limit=limit)
        for query_info in queries:
            try:
                raw = _fetch(fetcher, query_info.query_url, timeout=timeout)
                for record in cls.parse_results(query_info.adapter, raw, limit=limit):
                    evidence.append(
                        {
                            "source_id": str(next_source_id),
                            "source_type": query_info.source_type,
                            "adapter": query_info.adapter,
                            "title": record.get("title") or f"{query_info.adapter} source {next_source_id}",
                            "url": record.get("url") or query_info.query_url,
                            "snippet": record.get("snippet") or "",
                            "authors": record.get("authors") or [],
                            "year": record.get("year"),
                            "venue": record.get("venue") or "",
                            "query_url": query_info.query_url,
                            "verification_status": "fetched",
                            "fetched_at": _now_iso(),
                        }
                    )
                    next_source_id += 1
            except Exception as exc:  # noqa: BLE001 - adapter failures are isolated evidence-gathering results.
                errors.append(
                    {
                        "adapter": query_info.adapter,
                        "url": query_info.query_url,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
        return evidence, errors

    @classmethod
    def search_payload(cls, query: str, *, adapters: list[str] | None = None, limit: int = 10) -> dict[str, Any]:
        queries = [item.to_dict() for item in cls.build_queries(query, adapters=adapters, limit=limit)]
        return {
            "schema": "meetyou.academic_search.v1",
            "query": str(query or "").strip(),
            "status": "planned_queries",
            "adapters": queries,
            "evidence_ledger": [
                {
                    "source_id": str(index + 1),
                    "source_type": item["source_type"],
                    "adapter": item["adapter"],
                    "url": item["query_url"],
                    "verification_status": "query_url",
                }
                for index, item in enumerate(queries)
            ],
        }
