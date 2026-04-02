"""
Config-driven authoritative source connectors for research workflows.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

try:
    import aiohttp
except ImportError:  # pragma: no cover - optional dependency
    aiohttp = None

ActivityCallback = Callable[[str, str, dict[str, Any] | None], Awaitable[None]]

logger = logging.getLogger("meetyou.authoritative_sources")


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _trim_text(value: Any, limit: int = 600) -> str:
    normalized = _normalize_text(value)
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _normalize_domain(url_or_domain: str) -> str:
    raw = str(url_or_domain or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        raw = urlparse(raw).netloc
    raw = raw.lower()
    return raw[4:] if raw.startswith("www.") else raw


def _json_path_get(payload: Any, path: str) -> Any:
    current = payload
    for part in [item for item in str(path or "").split(".") if item]:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _parse_date(value: Any) -> datetime | None:
    raw = _normalize_text(value)
    if not raw:
        return None
    candidates = [
        raw,
        raw.replace("Z", "+00:00"),
        raw.split("T")[0],
        raw.split(" ")[0],
    ]
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


class AuthoritativeSourceRegistry:
    def __init__(self, mode_manager, web_tools):
        self._mode_manager = mode_manager
        self._web_tools = web_tools
        self._connector_map = {
            "github_releases": self._search_github_releases,
            "sec_edgar": self._search_sec_edgar,
            "fred": self._search_fred,
            "world_bank": self._search_world_bank,
            "pubmed_eutils": self._search_pubmed_eutils,
            "crossref_rest": self._search_crossref_rest,
            "openfda": self._search_openfda,
            "nvd_api": self._search_nvd_api,
            "cisa_kev": self._search_cisa_kev,
            "generic_json_api": self._search_generic_json_api,
            "whitelist_page_reader": self._search_whitelist_page_reader,
        }

    @property
    def supported_connector_types(self) -> set[str]:
        return set(self._connector_map)

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

    def _resolve_auth(self, source_config: dict[str, Any]) -> list[dict[str, Any]]:
        resolver = getattr(self._mode_manager, "resolve_source_auth_entries", None)
        if callable(resolver):
            return list(resolver(source_config))
        return []

    def _apply_auth(
        self,
        source_config: dict[str, Any],
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        params = dict(params or {})
        headers = dict(headers or {})
        for item in self._resolve_auth(source_config):
            value = str(item.get("value") or "").strip()
            if not value:
                continue
            auth_type = str(item.get("type") or "").strip().lower()
            if auth_type in {"query", "query_api_key", "query_contact"}:
                params[str(item.get("param") or "token")] = value
            elif auth_type == "header_bearer":
                headers[str(item.get("header") or "Authorization")] = f"Bearer {value}"
            elif auth_type == "header":
                headers[str(item.get("header") or "Authorization")] = value
        return params, headers

    async def _get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if aiohttp is None:
            return await asyncio.to_thread(self._urllib_get_json, url, params=params, headers=headers)
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, headers=headers) as response:
                response.raise_for_status()
                return await response.json(content_type=None)

    async def _get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        if aiohttp is None:
            return await asyncio.to_thread(self._urllib_get_text, url, params=params, headers=headers)
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, headers=headers) as response:
                response.raise_for_status()
                return await response.text()

    @staticmethod
    def _build_url(url: str, params: dict[str, Any] | None = None) -> str:
        if not params:
            return url
        return f"{url}?{urlencode(params, doseq=True)}"

    def _urllib_get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        request = Request(self._build_url(url, params=params), headers=dict(headers or {}))
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8")

    def _urllib_get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return json.loads(self._urllib_get_text(url, params=params, headers=headers))

    def _annotate_results(self, source_config: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        annotated: list[dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            annotated.append(
                {
                    "title": _normalize_text(item.get("title")),
                    "url": _normalize_text(item.get("url")),
                    "summary": _trim_text(item.get("summary") or item.get("snippet"), 720),
                    "snippet": _trim_text(item.get("snippet") or item.get("summary"), 320),
                    "published_date": _normalize_text(item.get("published_date")),
                    "reader": _normalize_text(item.get("reader") or source_config.get("connector_type")),
                    "source_type": _normalize_text(item.get("source_type") or source_config.get("connector_type")),
                    "catalog_source_id": _normalize_text(source_config.get("id")),
                    "catalog_source_label": _normalize_text(source_config.get("label")),
                    "catalog_source_domain": _normalize_text(source_config.get("domain")),
                    "connector_type": _normalize_text(source_config.get("connector_type")),
                    "credible_level": _normalize_text(source_config.get("credibility") or "primary"),
                    "freshness": _normalize_text(source_config.get("freshness") or ""),
                }
            )
        return annotated

    async def search(
        self,
        query: str,
        *,
        source_profile: str,
        limit: int = 5,
        official_only: bool | None = None,
        activity_callback: ActivityCallback | None = None,
    ) -> dict[str, Any]:
        status_getter = getattr(self._mode_manager, "get_source_catalog_status", None)
        status = status_getter() if callable(status_getter) else {"available": False, "error": "catalog_manager_unavailable"}
        profile_getter = getattr(self._mode_manager, "get_source_profile", None)
        profile = profile_getter(source_profile) if callable(profile_getter) else {"name": source_profile}
        source_getter = getattr(self._mode_manager, "get_sources_for_profile", None)
        sources = (
            source_getter(source_profile, official_only=official_only)
            if callable(source_getter)
            else []
        )

        if not status.get("available"):
            return {
                "catalog_status": status,
                "catalog_unavailable": True,
                "source_profile": source_profile,
                "sources": [],
                "partial_failures": [status.get("error") or "catalog_unavailable"],
            }

        collected: list[dict[str, Any]] = []
        failures: list[str] = []
        for source_config in sources:
            if len(collected) >= max(1, int(limit or 5)):
                break
            connector_type = str(source_config.get("connector_type") or "").strip()
            connector = self._connector_map.get(connector_type)
            if connector is None:
                failures.append(f"unsupported_connector:{connector_type}")
                continue

            await self._emit_activity(
                activity_callback,
                "searching_web",
                f"Searching authoritative source: {source_config.get('label') or connector_type}",
                {
                    "source_id": source_config.get("id"),
                    "connector_type": connector_type,
                    "activity_kind": "tool_chain",
                },
            )
            try:
                results = await connector(source_config, query, limit=max(1, int(limit or 5)))
                collected.extend(self._annotate_results(source_config, results))
            except Exception as exc:
                logger.warning("Authoritative source %s failed: %s", source_config.get("id"), exc)
                failures.append(f"{source_config.get('id')}: {exc}")

        for index, item in enumerate(collected[: max(1, int(limit or 5))], start=1):
            item["id"] = index

        return {
            "catalog_status": status,
            "catalog_unavailable": False,
            "source_profile": source_profile,
            "profile": profile,
            "sources": collected[: max(1, int(limit or 5))],
            "partial_failures": failures,
        }

    async def track_updates(
        self,
        *,
        source_profile: str,
        watchlist: list[str] | str | None = None,
        since: str = "",
        limit: int = 8,
        activity_callback: ActivityCallback | None = None,
    ) -> dict[str, Any]:
        watch_items = [watchlist] if isinstance(watchlist, str) else list(watchlist or [])
        watch_items = [_normalize_text(item) for item in watch_items if _normalize_text(item)]
        if not watch_items:
            watch_items = [source_profile]

        updates: list[dict[str, Any]] = []
        failures: list[str] = []
        catalog_status: dict[str, Any] = {"available": False, "error": "catalog_unavailable"}
        since_dt = _parse_date(since)
        for item in watch_items:
            payload = await self.search(
                item,
                source_profile=source_profile,
                limit=limit,
                activity_callback=activity_callback,
            )
            catalog_status = payload.get("catalog_status") or catalog_status
            updates.extend(payload.get("sources", []))
            failures.extend(payload.get("partial_failures", []))
            if len(updates) >= max(1, int(limit or 8)):
                break

        if since_dt is not None:
            filtered_updates: list[dict[str, Any]] = []
            for item in updates:
                published_dt = _parse_date(item.get("published_date"))
                if published_dt is None or published_dt >= since_dt:
                    filtered_updates.append(item)
            updates = filtered_updates

        updates.sort(
            key=lambda item: _parse_date(item.get("published_date")) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        return {
            "catalog_status": catalog_status,
            "catalog_unavailable": not bool(catalog_status.get("available")),
            "source_profile": source_profile,
            "watchlist": watch_items,
            "since": _normalize_text(since),
            "updates": updates[: max(1, int(limit or 8))],
            "partial_failures": failures,
        }

    async def _search_whitelist_page_reader(self, source_config: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
        domain = _normalize_text(source_config.get("domain"))
        request_defaults = source_config.get("request_defaults") or {}
        site_query = _normalize_text(request_defaults.get("site_query")) or domain
        search_query = f"site:{site_query} {query}".strip()
        raw = await self._web_tools.search_web(
            search_query,
            max_results=max(3, min(limit, 5)),
            source_profile=(source_config.get("profiles") or [""])[0],
        )
        payload = json.loads(raw)
        normalized_domain = _normalize_domain(domain)
        results: list[dict[str, Any]] = []
        for item in payload.get("sources", []):
            url_domain = _normalize_domain(item.get("url") or "")
            if normalized_domain and not (url_domain == normalized_domain or url_domain.endswith(f".{normalized_domain}")):
                continue
            results.append(
                {
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "summary": item.get("summary") or item.get("snippet"),
                    "snippet": item.get("snippet") or item.get("summary"),
                    "published_date": item.get("published_date"),
                    "reader": item.get("reader") or "whitelist_page_reader",
                }
            )
        return results[:limit]

    async def _search_github_releases(self, source_config: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
        request_defaults = dict(source_config.get("request_defaults") or {})
        request_defaults.setdefault("site_query", "github.com")
        return await self._search_whitelist_page_reader({**source_config, "request_defaults": request_defaults}, f"{query} releases", limit)

    async def _search_sec_edgar(self, source_config: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
        request_defaults = dict(source_config.get("request_defaults") or {})
        request_defaults.setdefault("site_query", "sec.gov")
        return await self._search_whitelist_page_reader({**source_config, "request_defaults": request_defaults}, f"{query} edgar filing", limit)

    async def _search_world_bank(self, source_config: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
        request_defaults = dict(source_config.get("request_defaults") or {})
        request_defaults.setdefault("site_query", "worldbank.org")
        return await self._search_whitelist_page_reader({**source_config, "request_defaults": request_defaults}, query, limit)

    async def _search_pubmed_eutils(self, source_config: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
        base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        params, headers = self._apply_auth(
            source_config,
            params={
                "db": "pubmed",
                "term": query,
                "retmax": max(1, min(limit, 5)),
                "retmode": "json",
                "sort": "relevance",
            },
        )
        search_payload = await self._get_json(f"{base_url}/esearch.fcgi", params=params, headers=headers)
        id_list = [str(item) for item in (((search_payload or {}).get("esearchresult") or {}).get("idlist") or []) if str(item).strip()]
        if not id_list:
            return []

        summary_params, summary_headers = self._apply_auth(
            source_config,
            params={
                "db": "pubmed",
                "id": ",".join(id_list[:limit]),
                "retmode": "json",
            },
        )
        summary_payload = await self._get_json(f"{base_url}/esummary.fcgi", params=summary_params, headers=summary_headers)
        result_section = (summary_payload or {}).get("result") or {}

        results: list[dict[str, Any]] = []
        for pubmed_id in id_list[:limit]:
            item = result_section.get(pubmed_id) or {}
            results.append(
                {
                    "title": item.get("title") or f"PubMed {pubmed_id}",
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pubmed_id}/",
                    "summary": ", ".join(item.get("authors", [{}])[0].get("name", "") for _ in [0]).strip(", "),
                    "snippet": item.get("fulljournalname") or item.get("source"),
                    "published_date": item.get("pubdate") or "",
                    "reader": "pubmed_eutils",
                }
            )
        return results

    async def _search_crossref_rest(self, source_config: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
        params, headers = self._apply_auth(
            source_config,
            params={
                "query.bibliographic": query,
                "rows": max(1, min(limit, 5)),
                "sort": "relevance",
            },
        )
        payload = await self._get_json("https://api.crossref.org/works", params=params, headers=headers)
        items = (((payload or {}).get("message") or {}).get("items") or [])[:limit]
        results: list[dict[str, Any]] = []
        for item in items:
            title_list = item.get("title") or []
            doi = _normalize_text(item.get("DOI"))
            results.append(
                {
                    "title": title_list[0] if title_list else doi or "Crossref work",
                    "url": f"https://doi.org/{doi}" if doi else "",
                    "summary": _trim_text(" ".join(item.get("container-title") or []), 240),
                    "snippet": _trim_text(" ".join(item.get("author", [{}])[0].get("family", "") for _ in [0]), 120),
                    "published_date": "-".join(str(part) for part in ((item.get("issued") or {}).get("date-parts") or [[None]])[0] if part),
                    "reader": "crossref_rest",
                }
            )
        return results

    async def _search_fred(self, source_config: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
        params, headers = self._apply_auth(
            source_config,
            params={
                "search_text": query,
                "file_type": "json",
                "limit": max(1, min(limit, 5)),
                "sort_order": "desc",
            },
        )
        payload = await self._get_json(
            "https://api.stlouisfed.org/fred/series/search",
            params=params,
            headers=headers,
        )
        results: list[dict[str, Any]] = []
        for item in (payload or {}).get("seriess", [])[:limit]:
            series_id = _normalize_text(item.get("id"))
            results.append(
                {
                    "title": item.get("title") or series_id,
                    "url": f"https://fred.stlouisfed.org/series/{series_id}" if series_id else "https://fred.stlouisfed.org/",
                    "summary": item.get("notes") or "",
                    "snippet": item.get("frequency_short") or item.get("units_short"),
                    "published_date": item.get("last_updated") or "",
                    "reader": "fred",
                }
            )
        return results

    async def _search_openfda(self, source_config: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
        params, headers = self._apply_auth(
            source_config,
            params={
                "search": query,
                "limit": max(1, min(limit, 5)),
            },
        )
        try:
            payload = await self._get_json(
                "https://api.fda.gov/drug/label.json",
                params=params,
                headers=headers,
            )
        except Exception:
            return await self._search_whitelist_page_reader(source_config, f"openfda {query}", limit)

        results: list[dict[str, Any]] = []
        for item in (payload or {}).get("results", [])[:limit]:
            openfda = item.get("openfda") or {}
            set_id = _normalize_text(item.get("set_id"))
            brand_name = ", ".join(openfda.get("brand_name") or [])
            results.append(
                {
                    "title": brand_name or set_id or "openFDA label",
                    "url": f"https://api.fda.gov/drug/label.json?search=set_id:{set_id}" if set_id else "https://open.fda.gov/apis/",
                    "summary": " ".join((item.get("indications_and_usage") or [])[:1]),
                    "snippet": ", ".join(openfda.get("manufacturer_name") or []),
                    "published_date": _normalize_text(item.get("effective_time")),
                    "reader": "openfda",
                }
            )
        return results

    async def _search_nvd_api(self, source_config: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
        params, headers = self._apply_auth(
            source_config,
            params={
                "keywordSearch": query,
                "resultsPerPage": max(1, min(limit, 5)),
            },
        )
        payload = await self._get_json("https://services.nvd.nist.gov/rest/json/cves/2.0", params=params, headers=headers)
        results: list[dict[str, Any]] = []
        for item in (payload or {}).get("vulnerabilities", [])[:limit]:
            cve = (item.get("cve") or {})
            cve_id = _normalize_text(cve.get("id"))
            descriptions = cve.get("descriptions") or []
            description = next((entry.get("value") for entry in descriptions if entry.get("lang") == "en"), "")
            published = _normalize_text(cve.get("published"))
            results.append(
                {
                    "title": cve_id or "NVD CVE",
                    "url": f"https://nvd.nist.gov/vuln/detail/{cve_id}" if cve_id else "https://nvd.nist.gov/",
                    "summary": description,
                    "snippet": description,
                    "published_date": published,
                    "reader": "nvd_api",
                }
            )
        return results

    async def _search_cisa_kev(self, source_config: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
        request_defaults = source_config.get("request_defaults") or {}
        endpoint = _normalize_text(request_defaults.get("endpoint")) or "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
        payload = await self._get_json(endpoint)
        keyword = _normalize_text(query).lower()
        results: list[dict[str, Any]] = []
        for item in (payload or {}).get("vulnerabilities", []):
            haystack = " ".join(
                [
                    _normalize_text(item.get("cveID")),
                    _normalize_text(item.get("vendorProject")),
                    _normalize_text(item.get("product")),
                    _normalize_text(item.get("vulnerabilityName")),
                    _normalize_text(item.get("shortDescription")),
                ]
            ).lower()
            if keyword and keyword not in haystack:
                continue
            cve_id = _normalize_text(item.get("cveID"))
            results.append(
                {
                    "title": cve_id or "CISA KEV",
                    "url": f"https://www.cisa.gov/known-exploited-vulnerabilities-catalog?search_api_fulltext={cve_id}" if cve_id else "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
                    "summary": item.get("shortDescription") or "",
                    "snippet": item.get("vulnerabilityName") or item.get("product") or "",
                    "published_date": _normalize_text(item.get("dateAdded")),
                    "reader": "cisa_kev",
                }
            )
            if len(results) >= limit:
                break
        return results

    async def _search_generic_json_api(self, source_config: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
        request_defaults = source_config.get("request_defaults") or {}
        endpoint = _normalize_text(request_defaults.get("endpoint"))
        if not endpoint:
            return []

        params = dict(request_defaults.get("params") or {})
        query_param = _normalize_text(request_defaults.get("query_param")) or "query"
        params[query_param] = query
        params.setdefault("limit", max(1, min(limit, 5)))
        params, headers = self._apply_auth(source_config, params=params)
        payload = await self._get_json(endpoint, params=params, headers=headers)
        result_path = _normalize_text(request_defaults.get("result_path")) or "results"
        items = _json_path_get(payload, result_path) or []

        title_field = _normalize_text(request_defaults.get("title_field")) or "title"
        url_field = _normalize_text(request_defaults.get("url_field")) or "url"
        summary_field = _normalize_text(request_defaults.get("summary_field")) or "summary"
        date_field = _normalize_text(request_defaults.get("date_field")) or "published_at"

        results: list[dict[str, Any]] = []
        for item in list(items)[:limit]:
            if not isinstance(item, dict):
                continue
            results.append(
                {
                    "title": _json_path_get(item, title_field),
                    "url": _json_path_get(item, url_field),
                    "summary": _json_path_get(item, summary_field),
                    "snippet": _json_path_get(item, summary_field),
                    "published_date": _json_path_get(item, date_field),
                    "reader": "generic_json_api",
                }
            )
        return results
