from __future__ import annotations

import fnmatch
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None

logger = logging.getLogger("meetyou.model_capabilities")

DEFAULT_CONTEXT_LIMIT = 8192
DEFAULT_OUTPUT_LIMIT = 4096


@dataclass
class ModelCapability:
    provider: str
    model_pattern: str
    context_window: int
    max_output_tokens: int
    source: str
    source_url: str
    source_checked_at: str
    confidence: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model_pattern": self.model_pattern,
            "context_window": int(self.context_window),
            "max_output_tokens": int(self.max_output_tokens),
            "source": self.source,
            "source_url": self.source_url,
            "source_checked_at": self.source_checked_at,
            "confidence": self.confidence,
            "notes": self.notes,
        }


class ModelCapabilityResolver:
    def __init__(
        self,
        *,
        registry_path: str = "core/model_capabilities/default_registry.json",
        cache_path: str = "user/model_capabilities_cache.json",
        cache_ttl_seconds: int = 24 * 3600,
    ) -> None:
        self._registry_path = Path(registry_path)
        self._cache_path = Path(cache_path)
        self._cache_ttl_seconds = max(int(cache_ttl_seconds or 0), 60)
        self._registry_entries = self._load_registry_entries()
        self._cache: dict[str, Any] = self._load_cache()

    def _load_registry_entries(self) -> list[ModelCapability]:
        if not self._registry_path.exists():
            return []
        payload = json.loads(self._registry_path.read_text(encoding="utf-8"))
        entries: list[ModelCapability] = []
        for item in payload.get("entries", []):
            entries.append(
                ModelCapability(
                    provider=str(item.get("provider") or "").strip().lower(),
                    model_pattern=str(item.get("model_pattern") or "").strip(),
                    context_window=int(item.get("context_window") or DEFAULT_CONTEXT_LIMIT),
                    max_output_tokens=int(item.get("max_output_tokens") or DEFAULT_OUTPUT_LIMIT),
                    source=str(item.get("source") or "registry"),
                    source_url=str(item.get("source_url") or ""),
                    source_checked_at=str(item.get("source_checked_at") or ""),
                    confidence=str(item.get("confidence") or "medium"),
                    notes=str(item.get("notes") or ""),
                )
            )
        return entries

    def _load_cache(self) -> dict[str, Any]:
        if not self._cache_path.exists():
            return {"updated_at": "", "entries": {}}
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {"updated_at": "", "entries": {}}
        if not isinstance(payload, dict):
            return {"updated_at": "", "entries": {}}
        payload.setdefault("entries", {})
        return payload

    def _persist_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _normalize_provider(provider: str) -> str:
        return str(provider or "").strip().lower()

    @staticmethod
    def _normalize_model(model: str) -> str:
        normalized = str(model or "").strip().lower()
        if normalized in {"deepseek-chat", "deepseek-reasoner"}:
            return "deepseek-v4-flash"
        return normalized

    @staticmethod
    def _cache_key(provider: str, model: str) -> str:
        return f"{provider}:{model}"

    def _cache_get(self, provider: str, model: str) -> ModelCapability | None:
        key = self._cache_key(provider, model)
        entry = (self._cache.get("entries") or {}).get(key)
        if not isinstance(entry, dict):
            return None
        expires_at = str(entry.get("expires_at") or "")
        if expires_at:
            try:
                if datetime.now(timezone.utc) >= datetime.fromisoformat(expires_at):
                    return None
            except Exception:
                return None
        return ModelCapability(
            provider=provider,
            model_pattern=model,
            context_window=int(entry.get("context_window") or DEFAULT_CONTEXT_LIMIT),
            max_output_tokens=int(entry.get("max_output_tokens") or DEFAULT_OUTPUT_LIMIT),
            source=str(entry.get("source") or "cache"),
            source_url=str(entry.get("source_url") or ""),
            source_checked_at=str(entry.get("source_checked_at") or ""),
            confidence=str(entry.get("confidence") or "medium"),
            notes=str(entry.get("notes") or ""),
        )

    def _cache_put(self, capability: ModelCapability) -> None:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self._cache_ttl_seconds)
        key = self._cache_key(capability.provider, capability.model_pattern)
        entries = self._cache.setdefault("entries", {})
        entries[key] = {
            **capability.to_dict(),
            "expires_at": expires.isoformat(),
        }
        self._cache["updated_at"] = now.isoformat()
        self._persist_cache()

    def _match_registry(self, provider: str, model: str) -> ModelCapability | None:
        for entry in self._registry_entries:
            if entry.provider != provider:
                continue
            if fnmatch.fnmatch(model, entry.model_pattern.lower()):
                return ModelCapability(
                    provider=provider,
                    model_pattern=model,
                    context_window=entry.context_window,
                    max_output_tokens=entry.max_output_tokens,
                    source="registry",
                    source_url=entry.source_url,
                    source_checked_at=entry.source_checked_at,
                    confidence=entry.confidence,
                    notes=entry.notes,
                )
        return None

    def resolve(
        self,
        *,
        provider: str,
        model: str,
        allow_network: bool = False,
    ) -> tuple[ModelCapability, dict[str, Any]]:
        p = self._normalize_provider(provider)
        m = self._normalize_model(model)
        cache_hit = self._cache_get(p, m)
        if cache_hit is not None:
            return cache_hit, {"source": "cache", "diagnostic": "cache_hit", "confidence": cache_hit.confidence}

        from_registry = self._match_registry(p, m)
        if from_registry is not None:
            return from_registry, {"source": "registry", "diagnostic": "registry_match", "confidence": from_registry.confidence}

        warning = f"Unknown model capability provider={p} model={m}; using conservative fallback={DEFAULT_CONTEXT_LIMIT}."
        logger.warning(warning)
        fallback = ModelCapability(
            provider=p,
            model_pattern=m,
            context_window=DEFAULT_CONTEXT_LIMIT,
            max_output_tokens=DEFAULT_OUTPUT_LIMIT,
            source="fallback_default",
            source_url="",
            source_checked_at=datetime.now(timezone.utc).isoformat(),
            confidence="low",
            notes="unknown_model_requires_manual_confirmation",
        )
        if allow_network and p in {"gemini", "anthropic", "ollama", "deepseek", "openai"}:
            return fallback, {"source": "fallback_default", "diagnostic": warning, "confidence": "low"}
        return fallback, {"source": "fallback_default", "diagnostic": warning, "confidence": "low"}

    async def refresh_model_capabilities(
        self,
        *,
        provider: str,
        model: str,
        api_base_url: str = "",
        api_key: str = "",
        fetcher=None,
    ) -> dict[str, Any]:
        p = self._normalize_provider(provider)
        m = self._normalize_model(model)
        old_capability, _ = self.resolve(provider=p, model=m, allow_network=False)

        refreshed: ModelCapability | None = None
        source = ""
        if p == "gemini":
            refreshed = await self._refresh_gemini(model=m, api_base_url=api_base_url, api_key=api_key, fetcher=fetcher)
            source = "gemini_models_api"
        elif p == "anthropic":
            refreshed = await self._refresh_anthropic(model=m, api_base_url=api_base_url, api_key=api_key, fetcher=fetcher)
            source = "anthropic_models_api"
        elif p == "ollama":
            refreshed = await self._refresh_ollama(model=m, api_base_url=api_base_url, fetcher=fetcher)
            source = "ollama_show"
        elif p == "deepseek":
            refreshed = await self._refresh_deepseek_docs(model=m, fetcher=fetcher)
            source = "deepseek_docs"
        elif p == "openai":
            refreshed = self._match_registry(p, m)
            source = "openai_registry"

        if refreshed is None:
            refreshed = old_capability
            trusted = False
            manual = True
        else:
            refreshed.provider = p
            refreshed.model_pattern = m
            self._cache_put(refreshed)
            trusted = refreshed.confidence in {"high", "medium"}
            manual = refreshed.confidence == "low"

        return {
            "provider": p,
            "model": m,
            "source": source or "fallback_default",
            "old": old_capability.to_dict(),
            "new": refreshed.to_dict(),
            "is_trusted": trusted,
            "needs_manual_confirmation": manual,
        }

    async def _request_json(self, *, method: str, url: str, headers: dict[str, str] | None = None, fetcher=None) -> dict[str, Any]:
        if fetcher is not None:
            return await fetcher(method=method, url=url, headers=headers or {})
        if aiohttp is None:
            return {}
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(method, url, headers=headers or {}) as response:
                if response.status >= 400:
                    return {}
                return await response.json()

    async def _refresh_gemini(self, *, model: str, api_base_url: str, api_key: str, fetcher=None) -> ModelCapability | None:
        base = str(api_base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        if "/models/" in base:
            base = base.split("/models/", 1)[0]
        url = f"{base}/models/{model}?key={api_key}" if api_key else f"{base}/models/{model}"
        payload = await self._request_json(method="GET", url=url, fetcher=fetcher)
        context = int(payload.get("inputTokenLimit") or 0)
        output = int(payload.get("outputTokenLimit") or 0)
        if context <= 0:
            return None
        return ModelCapability(
            provider="gemini",
            model_pattern=model,
            context_window=context,
            max_output_tokens=max(output, DEFAULT_OUTPUT_LIMIT),
            source="gemini_models_api",
            source_url=url,
            source_checked_at=datetime.now(timezone.utc).isoformat(),
            confidence="high",
            notes="models.get",
        )

    async def _refresh_anthropic(self, *, model: str, api_base_url: str, api_key: str, fetcher=None) -> ModelCapability | None:
        base = str(api_base_url or "https://api.anthropic.com/v1").rstrip("/")
        if base.endswith("/messages"):
            base = base.rsplit("/", 1)[0]
        url = f"{base}/models/{model}"
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"} if api_key else {"anthropic-version": "2023-06-01"}
        payload = await self._request_json(method="GET", url=url, headers=headers, fetcher=fetcher)
        context = int(payload.get("max_input_tokens") or payload.get("context_window") or 0)
        output = int(payload.get("max_output_tokens") or payload.get("max_tokens") or 0)
        if context <= 0:
            return None
        return ModelCapability(
            provider="anthropic",
            model_pattern=model,
            context_window=context,
            max_output_tokens=max(output, DEFAULT_OUTPUT_LIMIT),
            source="anthropic_models_api",
            source_url=url,
            source_checked_at=datetime.now(timezone.utc).isoformat(),
            confidence="medium",
            notes="models.get",
        )

    async def _refresh_ollama(self, *, model: str, api_base_url: str, fetcher=None) -> ModelCapability | None:
        base = str(api_base_url or "http://localhost:11434/api/chat").rstrip("/")
        if "/api/" in base:
            base = base.split("/api/", 1)[0]
        url = f"{base}/api/show"
        payload = await self._request_json(method="POST", url=f"{url}?name={model}", fetcher=fetcher)
        info = payload.get("model_info") or {}
        context = 0
        for key, value in info.items():
            if "context_length" in str(key):
                context = int(value or 0)
                break
        if context <= 0:
            parameters = str(payload.get("parameters") or "")
            match = re.search(r"num_ctx\s+(\d+)", parameters)
            if match:
                context = int(match.group(1))
        if context <= 0:
            return None
        return ModelCapability(
            provider="ollama",
            model_pattern=model,
            context_window=context,
            max_output_tokens=DEFAULT_OUTPUT_LIMIT,
            source="ollama_show",
            source_url=url,
            source_checked_at=datetime.now(timezone.utc).isoformat(),
            confidence="medium",
            notes="model_info",
        )

    async def _refresh_deepseek_docs(self, *, model: str, fetcher=None) -> ModelCapability | None:
        canonical = "deepseek-v4-flash" if model in {"deepseek-chat", "deepseek-reasoner"} else model
        url = "https://api-docs.deepseek.com/"
        context = 1_000_000 if canonical in {"deepseek-v4-flash", "deepseek-v4-pro"} else 0
        output = 384_000 if canonical in {"deepseek-v4-flash", "deepseek-v4-pro"} else 0
        confidence = "medium"
        if fetcher is not None:
            payload = await fetcher(method="GET", url=url, headers={})
            text = str(payload.get("text") or "")
            if "1M" in text and "384K" in text:
                confidence = "high"
        if context <= 0:
            return None
        return ModelCapability(
            provider="deepseek",
            model_pattern=model,
            context_window=context,
            max_output_tokens=output,
            source="deepseek_docs",
            source_url=url,
            source_checked_at=datetime.now(timezone.utc).isoformat(),
            confidence=confidence,
            notes="deepseek /models lacks token limits; docs fallback",
        )


_RESOLVER: ModelCapabilityResolver | None = None


def get_model_capability_resolver() -> ModelCapabilityResolver:
    global _RESOLVER
    if _RESOLVER is None:
        _RESOLVER = ModelCapabilityResolver()
    return _RESOLVER
