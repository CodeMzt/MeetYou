"""
Source catalog loading, validation, and context-limit resolution.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import aiohttp
except ImportError:  # pragma: no cover - optional dependency
    aiohttp = None

from adapters.base import MODEL_CONTEXT_LIMITS

logger = logging.getLogger("meetyou.source_catalog")


class _FallbackProbeSession:
    async def close(self):
        return None

DEFAULT_SOURCE_CATALOG_PATH = "user/source_catalog.json"
VALID_CONNECTOR_TYPES = {
    "github_releases",
    "sec_edgar",
    "fred",
    "world_bank",
    "pubmed_eutils",
    "crossref_rest",
    "openfda",
    "nvd_api",
    "cisa_kev",
    "generic_json_api",
    "rss_atom_feed",
    "whitelist_page_reader",
}
FALLBACK_SOURCE_PROFILES = {
    "workspace_local": {
        "label": "Workspace / Local Knowledge",
        "description": "Prefer local files, memory, and private workspace knowledge.",
        "preferred_source_ids": [],
        "official_only": False,
        "default_freshness": "workspace",
        "primary_domains": [],
    },
    "study_materials": {
        "label": "Study Materials",
        "description": "Prefer local learning materials and explicit references from the user.",
        "preferred_source_ids": [],
        "official_only": False,
        "default_freshness": "coursework",
        "primary_domains": [],
    },
    "tech_updates": {
        "label": "Tech Updates",
        "description": "Official releases, changelogs, standards, and vendor updates.",
        "preferred_source_ids": [],
        "official_only": True,
        "default_freshness": "high",
        "primary_domains": [],
        "match_any": [
            "latest",
            "release",
            "changelog",
            "framework",
            "model",
            "sdk",
            "api",
            "版本",
            "更新",
            "发布",
            "模型",
            "框架",
        ],
    },
    "policy_cn": {
        "label": "Policy China",
        "description": "Chinese government policy, regulation, and statistics.",
        "preferred_source_ids": [],
        "official_only": True,
        "default_freshness": "high",
        "primary_domains": [],
        "match_any": [
            "gov.cn",
            "政策",
            "法规",
            "统计",
            "国务院",
            "国家统计局",
        ],
    },
    "policy_global": {
        "label": "Policy Global",
        "description": "Government and regulator sources outside China.",
        "preferred_source_ids": [],
        "official_only": True,
        "default_freshness": "high",
        "primary_domains": [],
        "match_any": [
            "policy",
            "regulation",
            "government",
            "fda",
            "sec",
            "who",
            "law",
        ],
    },
    "finance_macro": {
        "label": "Finance / Macro",
        "description": "Official filings, macro indicators, and financial disclosures.",
        "preferred_source_ids": [],
        "official_only": True,
        "default_freshness": "high",
        "primary_domains": [],
        "match_any": [
            "finance",
            "earnings",
            "filing",
            "inflation",
            "gdp",
            "stock",
            "macro",
            "财报",
            "股价",
            "宏观",
            "经济",
        ],
    },
    "academic_biomed": {
        "label": "Academic / Biomed",
        "description": "Papers, PubMed, DOI records, and biomedical literature.",
        "preferred_source_ids": [],
        "official_only": True,
        "default_freshness": "medium",
        "primary_domains": [],
        "match_any": [
            "paper",
            "doi",
            "pubmed",
            "study",
            "journal",
            "trial",
            "论文",
            "文献",
            "医学",
            "研究",
        ],
    },
    "cyber_threat": {
        "label": "Cyber Threat",
        "description": "Official vulnerability and exploit advisories.",
        "preferred_source_ids": [],
        "official_only": True,
        "default_freshness": "high",
        "primary_domains": [],
        "match_any": [
            "cve",
            "vulnerability",
            "exploit",
            "kev",
            "漏洞",
            "安全",
            "威胁",
        ],
    },
}


def _fallback_context_limit(model_name: str) -> int:
    normalized = str(model_name or "").strip()
    if normalized in MODEL_CONTEXT_LIMITS:
        return int(MODEL_CONTEXT_LIMITS[normalized])
    for key, limit in MODEL_CONTEXT_LIMITS.items():
        if normalized.startswith(key):
            return int(limit)
    return 8192


def _normalize_domain(value: str) -> str:
    domain = str(value or "").strip().lower()
    if not domain:
        return ""
    if domain.startswith("http://") or domain.startswith("https://"):
        parsed = urlparse(domain)
        domain = parsed.netloc.lower()
    return domain[4:] if domain.startswith("www.") else domain


def _match_any_pattern(value: str, patterns: list[str] | tuple[str, ...]) -> bool:
    normalized = str(value or "").strip().lower()
    for pattern in patterns:
        current = str(pattern or "").strip().lower()
        if not current:
            continue
        if any(token in current for token in ("*", "?")):
            if fnmatch.fnmatch(normalized, current):
                return True
            continue
        if normalized == current or normalized.startswith(current):
            return True
    return False


@dataclass
class SourceCatalogStatus:
    available: bool
    path: str
    error: str = ""
    version: str = ""
    profile_count: int = 0
    source_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "path": self.path,
            "error": self.error,
            "version": self.version,
            "profile_count": self.profile_count,
            "source_count": self.source_count,
        }


@dataclass
class ContextLimitInfo:
    context_limit_tokens: int
    context_limit_source: str
    context_limit_model: str
    context_limit_confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_limit_tokens": int(self.context_limit_tokens),
            "context_limit_source": self.context_limit_source,
            "context_limit_model": self.context_limit_model,
            "context_limit_confidence": self.context_limit_confidence,
        }


class SourceCatalogManager:
    def __init__(self, config_manager):
        self._config = config_manager

    def get_catalog_path(self) -> str:
        raw = str(self._config.get("source_catalog_path") or DEFAULT_SOURCE_CATALOG_PATH).strip()
        return raw or DEFAULT_SOURCE_CATALOG_PATH

    def _fallback_catalog(self) -> dict[str, Any]:
        return {
            "version": "fallback",
            "default_source_profiles": FALLBACK_SOURCE_PROFILES,
            "context_limits": [],
            "sources": [],
        }

    def _load_catalog(self) -> tuple[dict[str, Any], SourceCatalogStatus]:
        path = Path(self.get_catalog_path())
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._fallback_catalog(), SourceCatalogStatus(
                available=False,
                path=str(path),
                error="source_catalog_not_found",
            )
        except json.JSONDecodeError as exc:
            return self._fallback_catalog(), SourceCatalogStatus(
                available=False,
                path=str(path),
                error=f"source_catalog_invalid_json: {exc}",
            )

        if not isinstance(payload, dict):
            return self._fallback_catalog(), SourceCatalogStatus(
                available=False,
                path=str(path),
                error="source_catalog_root_must_be_object",
            )

        version = str(payload.get("version") or "")
        profiles = payload.get("default_source_profiles")
        context_limits = payload.get("context_limits")
        sources = payload.get("sources")
        if not isinstance(profiles, dict) or not isinstance(context_limits, list) or not isinstance(sources, list):
            return self._fallback_catalog(), SourceCatalogStatus(
                available=False,
                path=str(path),
                error="source_catalog_missing_required_sections",
            )

        normalized_sources: list[dict[str, Any]] = []
        for item in sources:
            if not isinstance(item, dict):
                continue
            connector_type = str(item.get("connector_type") or "").strip()
            if connector_type and connector_type not in VALID_CONNECTOR_TYPES:
                logger.warning("Ignoring source catalog entry with unknown connector type: %s", connector_type)
                continue
            normalized_sources.append(item)

        normalized_catalog = {
            "version": version or "1",
            "default_source_profiles": {**FALLBACK_SOURCE_PROFILES, **profiles},
            "context_limits": [item for item in context_limits if isinstance(item, dict)],
            "sources": normalized_sources,
        }
        return normalized_catalog, SourceCatalogStatus(
            available=True,
            path=str(path),
            version=normalized_catalog["version"],
            profile_count=len(normalized_catalog["default_source_profiles"]),
            source_count=len(normalized_sources),
        )

    def get_catalog_status(self) -> dict[str, Any]:
        _, status = self._load_catalog()
        return status.to_dict()

    def get_source_profiles(self) -> dict[str, Any]:
        catalog, _ = self._load_catalog()
        return dict(catalog.get("default_source_profiles") or {})

    def get_source_profile(self, profile_name: str) -> dict[str, Any]:
        profiles = self.get_source_profiles()
        normalized = str(profile_name or "").strip() or "workspace_local"
        resolved_name = normalized
        payload = profiles.get(normalized)
        if payload is None:
            if "tech_updates" in profiles:
                resolved_name = "tech_updates"
                payload = profiles.get("tech_updates")
            else:
                resolved_name = "workspace_local"
                payload = profiles.get("workspace_local") or {}
        return {"name": resolved_name, **(payload or {})}

    def get_sources(
        self,
        profile_name: str = "",
        *,
        official_only: bool | None = None,
        only_enabled: bool = True,
    ) -> list[dict[str, Any]]:
        catalog, _ = self._load_catalog()
        profile = self.get_source_profile(profile_name)
        preferred_ids = [str(item).strip() for item in profile.get("preferred_source_ids", []) if str(item).strip()]
        profile_ids = set(preferred_ids)
        preferred_order = {source_id: index for index, source_id in enumerate(preferred_ids)}
        requested_profile = str(profile_name or "").strip()
        effective_official_only = profile.get("official_only") if official_only is None else official_only

        selected: list[dict[str, Any]] = []
        for item in catalog.get("sources", []):
            if only_enabled and not bool(item.get("enabled", False)):
                continue
            item_profiles = {str(value).strip() for value in item.get("profiles", []) if str(value).strip()}
            if requested_profile and requested_profile not in item_profiles and str(item.get("id") or "") not in profile_ids:
                continue
            if effective_official_only and not bool(item.get("primary_source", False)):
                continue
            selected.append(dict(item))

        selected.sort(
            key=lambda item: (
                0 if str(item.get("id") or "") in preferred_order else 1,
                preferred_order.get(str(item.get("id") or ""), len(preferred_order)),
                -int(item.get("priority", 0) or 0),
                str(item.get("label") or item.get("id") or ""),
            )
        )
        return selected

    def get_source_by_id(self, source_id: str) -> dict[str, Any] | None:
        catalog, _ = self._load_catalog()
        normalized = str(source_id or "").strip()
        for item in catalog.get("sources", []):
            if str(item.get("id") or "").strip() == normalized:
                return dict(item)
        return None

    def classify_research_profile(self, text: str) -> str:
        lowered = str(text or "").lower()
        profiles = self.get_source_profiles()
        for profile_name, profile in profiles.items():
            if profile_name in {"workspace_local", "study_materials"}:
                continue
            match_any = [str(item).lower() for item in profile.get("match_any", []) if str(item).strip()]
            if match_any and any(token in lowered for token in match_any):
                return str(profile_name)
        if any("\u4e00" <= char <= "\u9fff" for char in str(text or "")) and "policy_cn" in profiles:
            if any(token in lowered for token in ("政策", "法规", "统计", "gov.cn", "国务院")):
                return "policy_cn"
        return "tech_updates" if "tech_updates" in profiles else "workspace_local"

    def is_primary_source(self, url: str, profile_name: str = "") -> bool:
        parsed = urlparse(str(url or "").strip())
        domain = _normalize_domain(parsed.netloc)
        if not domain:
            return False

        profile = self.get_source_profile(profile_name)
        primary_domains = {_normalize_domain(item) for item in profile.get("primary_domains", [])}
        for source in self.get_sources(profile_name):
            if not bool(source.get("primary_source", False)):
                continue
            primary_domains.add(_normalize_domain(source.get("domain") or ""))
            for item in source.get("domain_patterns", []) or []:
                primary_domains.add(_normalize_domain(item))

        return any(
            domain == item or domain.endswith(f".{item}")
            for item in primary_domains
            if item
        )

    def _match_context_limit_entry(
        self,
        provider_name: str,
        api_url: str,
        model_name: str,
    ) -> dict[str, Any] | None:
        catalog, _ = self._load_catalog()
        provider = str(provider_name or "").strip().lower()
        host = _normalize_domain(urlparse(str(api_url or "").strip()).netloc)
        model = str(model_name or "").strip()

        for entry in catalog.get("context_limits", []):
            entry_provider = str(entry.get("provider") or "").strip().lower()
            host_patterns = [str(item).strip().lower() for item in entry.get("host_patterns", []) if str(item).strip()]
            model_patterns = [str(item).strip() for item in entry.get("model_patterns", []) if str(item).strip()]
            if entry_provider and entry_provider != provider:
                continue
            if host_patterns and not _match_any_pattern(host, host_patterns):
                continue
            if model_patterns and not _match_any_pattern(model, model_patterns):
                continue
            return dict(entry)
        return None

    async def _probe_context_limit(self, probe_callable, api_url: str, model_name: str) -> int | None:
        if not callable(probe_callable):
            return None
        if aiohttp is not None:
            async with aiohttp.ClientSession() as session:
                return await probe_callable(session, api_url, model_name)
        session = _FallbackProbeSession()
        try:
            return await probe_callable(session, api_url, model_name)
        finally:
            await session.close()

    async def resolve_context_limit(
        self,
        *,
        provider_name: str,
        api_url: str,
        model_name: str,
        adapter,
    ) -> ContextLimitInfo:
        matched_entry = self._match_context_limit_entry(provider_name, api_url, model_name)
        probe_callable = getattr(adapter, "query_model_context_limit", None)
        if matched_entry and matched_entry.get("probe") and callable(probe_callable):
            try:
                probed = await self._probe_context_limit(probe_callable, api_url, model_name)
                if probed:
                    return ContextLimitInfo(
                        context_limit_tokens=int(probed),
                        context_limit_source="provider_probe",
                        context_limit_model=str(model_name or ""),
                        context_limit_confidence="high",
                    )
            except Exception as exc:
                logger.info("Context limit probe failed for %s/%s: %s", provider_name, model_name, exc)

        if matched_entry:
            return ContextLimitInfo(
                context_limit_tokens=int(matched_entry.get("context_limit_tokens", 0) or 0),
                context_limit_source=str(matched_entry.get("source") or "official_registry"),
                context_limit_model=str(model_name or ""),
            context_limit_confidence=str(matched_entry.get("confidence") or "medium"),
        )

        if callable(probe_callable):
            try:
                probed = await self._probe_context_limit(probe_callable, api_url, model_name)
                if probed:
                    return ContextLimitInfo(
                        context_limit_tokens=int(probed),
                        context_limit_source="provider_probe",
                        context_limit_model=str(model_name or ""),
                        context_limit_confidence="high",
                    )
            except Exception as exc:
                logger.info("Context limit probe failed for %s/%s: %s", provider_name, model_name, exc)

        return ContextLimitInfo(
            context_limit_tokens=_fallback_context_limit(model_name),
            context_limit_source="fallback",
            context_limit_model=str(model_name or ""),
            context_limit_confidence="low",
        )

    def resolve_auth_entries(self, source_config: dict[str, Any]) -> list[dict[str, Any]]:
        auth_config = source_config.get("auth") or []
        entries = [auth_config] if isinstance(auth_config, dict) else list(auth_config)
        resolved: list[dict[str, Any]] = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            env_key = str(item.get("env") or "").strip()
            config_key = str(item.get("config_key") or "").strip()
            value = ""
            if env_key:
                value = os.environ.get(env_key, "")
            if not value and config_key:
                value = str(self._config.get(config_key) or "")
            resolved.append({**item, "value": value})
        return resolved
