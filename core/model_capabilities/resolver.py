from __future__ import annotations

import fnmatch
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.persistence import atomic_write_json

logger = logging.getLogger("meetyou.model_capabilities")

_DEFAULT_CONTEXT_LIMIT = 8192
_DEFAULT_MAX_OUTPUT_TOKENS = 4096


@dataclass
class ModelCapability:
    provider: str
    model: str
    context_window: int
    max_output_tokens: int
    source: str
    source_url: str = ""
    source_checked_at: str = ""
    confidence: str = "low"
    notes: str = ""
    diagnostic: str = ""
    requires_manual_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "context_window": int(self.context_window),
            "max_output_tokens": int(self.max_output_tokens),
            "source": self.source,
            "source_url": self.source_url,
            "source_checked_at": self.source_checked_at,
            "confidence": self.confidence,
            "notes": self.notes,
            "diagnostic": self.diagnostic,
            "requires_manual_confirmation": bool(self.requires_manual_confirmation),
        }


class ModelCapabilityResolver:
    def __init__(
        self,
        *,
        registry_path: str = "core/model_capabilities/default_registry.json",
        cache_path: str = "user/runtime/model_capabilities_cache.json",
        cache_ttl_seconds: int = 24 * 60 * 60,
    ) -> None:
        self._registry_path = Path(registry_path)
        self._cache_path = Path(cache_path)
        self._cache_ttl_seconds = max(int(cache_ttl_seconds or 0), 60)
        self._registry = self._load_registry()
        self._cache = self._load_cache()

    def _load_registry(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._registry_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning("Model capability registry missing: %s", self._registry_path)
            return {"entries": []}
        except Exception as exc:
            logger.warning("Failed to load model capability registry: %s", exc)
            return {"entries": []}
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return {"entries": []}
        return payload

    def _load_cache(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"entries": {}}
        except Exception:
            return {"entries": {}}
        if not isinstance(payload, dict):
            return {"entries": {}}
        payload.setdefault("entries", {})
        if not isinstance(payload["entries"], dict):
            payload["entries"] = {}
        return payload

    def _cache_key(self, provider: str, model: str) -> str:
        return f"{provider.strip().lower()}::{model.strip().lower()}"

    def _save_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(str(self._cache_path), self._cache)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _cache_entry_is_fresh(self, payload: dict[str, Any]) -> bool:
        checked_at = str(payload.get("checked_at") or "").strip()
        if not checked_at:
            return False
        try:
            ts = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return datetime.now(timezone.utc) - ts <= timedelta(seconds=self._cache_ttl_seconds)

    def _lookup_registry(self, provider: str, model: str) -> ModelCapability | None:
        provider_norm = str(provider or "").strip().lower()
        model_norm = str(model or "").strip().lower()
        for item in self._registry.get("entries", []):
            if not isinstance(item, dict):
                continue
            item_provider = str(item.get("provider") or "").strip().lower()
            if item_provider and provider_norm and item_provider != provider_norm:
                continue
            patterns = [str(pattern or "").strip().lower() for pattern in item.get("model_patterns", [])]
            if patterns and not any(fnmatch.fnmatch(model_norm, pattern) for pattern in patterns):
                continue
            context_window = int(item.get("context_window", 0) or 0)
            max_output_tokens = int(item.get("max_output_tokens", 0) or 0)
            if context_window <= 0:
                continue
            return ModelCapability(
                provider=provider_norm or item_provider,
                model=model,
                context_window=context_window,
                max_output_tokens=max(max_output_tokens, 1),
                source="registry",
                source_url=str(item.get("source_url") or ""),
                source_checked_at=str(item.get("source_checked_at") or ""),
                confidence=str(item.get("confidence") or "medium"),
                notes=str(item.get("notes") or ""),
            )
        return None

    def resolve(self, provider: str, model: str) -> ModelCapability:
        key = self._cache_key(provider, model)
        cache_entry = self._cache.get("entries", {}).get(key)
        if isinstance(cache_entry, dict) and self._cache_entry_is_fresh(cache_entry):
            capability = cache_entry.get("capability") or {}
            if capability.get("context_window"):
                return ModelCapability(
                    provider=provider,
                    model=model,
                    context_window=int(capability.get("context_window") or 0),
                    max_output_tokens=int(capability.get("max_output_tokens") or _DEFAULT_MAX_OUTPUT_TOKENS),
                    source="cache",
                    source_url=str(capability.get("source_url") or ""),
                    source_checked_at=str(cache_entry.get("checked_at") or ""),
                    confidence=str(capability.get("confidence") or "high"),
                    notes=str(capability.get("notes") or ""),
                    diagnostic=str(capability.get("diagnostic") or ""),
                )

        registry_capability = self._lookup_registry(provider, model)
        if registry_capability is not None:
            return registry_capability

        diagnostic = f"Unknown model capability for provider={provider} model={model}; using default fallback context={_DEFAULT_CONTEXT_LIMIT}."
        logger.warning(diagnostic)
        return ModelCapability(
            provider=provider,
            model=model,
            context_window=_DEFAULT_CONTEXT_LIMIT,
            max_output_tokens=_DEFAULT_MAX_OUTPUT_TOKENS,
            source="fallback",
            confidence="low",
            diagnostic=diagnostic,
            requires_manual_confirmation=True,
        )

    async def refresh_model_capabilities(
        self,
        *,
        provider: str,
        model: str,
        api_url: str = "",
        api_key: str = "",
        session=None,
    ) -> dict[str, Any]:
        old = self.resolve(provider, model)
        refreshed = await self._fetch_provider_capability(
            provider=provider,
            model=model,
            api_url=api_url,
            api_key=api_key,
            session=session,
        )
        if refreshed is None:
            refreshed = self._lookup_registry(provider, model)

        if refreshed is None:
            refreshed = ModelCapability(
                provider=provider,
                model=model,
                context_window=_DEFAULT_CONTEXT_LIMIT,
                max_output_tokens=_DEFAULT_MAX_OUTPUT_TOKENS,
                source="fallback",
                confidence="low",
                diagnostic="refresh_failed_no_authoritative_source",
                requires_manual_confirmation=True,
            )

        key = self._cache_key(provider, model)
        self._cache.setdefault("entries", {})[key] = {
            "checked_at": self._now_iso(),
            "capability": refreshed.to_dict(),
        }
        self._save_cache()
        return {
            "provider": provider,
            "model": model,
            "source": refreshed.source,
            "old": old.to_dict(),
            "new": refreshed.to_dict(),
            "trusted": refreshed.confidence in {"high", "medium"},
            "requires_manual_confirmation": bool(refreshed.requires_manual_confirmation),
        }

    async def _fetch_provider_capability(self, *, provider: str, model: str, api_url: str, api_key: str, session=None) -> ModelCapability | None:
        provider_norm = str(provider or "").strip().lower()
        if provider_norm in {"deepseek", "openai"}:
            return None
        if provider_norm == "ollama":
            return await self._fetch_ollama(model=model, api_url=api_url, session=session)
        if provider_norm == "gemini":
            return await self._fetch_gemini(model=model, api_url=api_url, api_key=api_key, session=session)
        if provider_norm == "anthropic":
            return await self._fetch_anthropic(model=model, api_url=api_url, api_key=api_key, session=session)
        return None

    async def _fetch_gemini(self, *, model: str, api_url: str, api_key: str, session=None) -> ModelCapability | None:
        if session is None:
            return None
        base_url = str(api_url or "https://generativelanguage.googleapis.com/v1beta").split("/models/")[0].rstrip("/")
        url = f"{base_url}/models/{model}"
        params = {"key": api_key} if api_key else None
        try:
            async with session.get(url, params=params) as resp:
                if resp.status >= 400:
                    return None
                data = await resp.json()
        except Exception:
            return None
        input_limit = int(data.get("inputTokenLimit", 0) or 0)
        output_limit = int(data.get("outputTokenLimit", 0) or 0)
        if input_limit <= 0:
            return None
        return ModelCapability(
            provider="gemini",
            model=model,
            context_window=input_limit,
            max_output_tokens=max(output_limit, 1),
            source="provider_api",
            source_url=url,
            source_checked_at=self._now_iso(),
            confidence="high",
        )

    async def _fetch_anthropic(self, *, model: str, api_url: str, api_key: str, session=None) -> ModelCapability | None:
        if session is None:
            return None
        base = str(api_url or "https://api.anthropic.com/v1/messages")
        parsed = urlparse(base)
        root = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://api.anthropic.com"
        url = f"{root}/v1/models/{model}"
        headers = {"anthropic-version": "2023-06-01"}
        if api_key:
            headers["x-api-key"] = api_key
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status >= 400:
                    return None
                data = await resp.json()
        except Exception:
            return None
        input_limit = int(data.get("max_input_tokens", 0) or 0)
        output_limit = int(data.get("max_output_tokens", data.get("max_tokens", 0)) or 0)
        capabilities = data.get("capabilities") or {}
        if output_limit <= 0 and isinstance(capabilities, dict):
            output_limit = int(capabilities.get("max_output_tokens", 0) or 0)
        if input_limit <= 0:
            return None
        return ModelCapability(
            provider="anthropic",
            model=model,
            context_window=input_limit,
            max_output_tokens=max(output_limit, 1),
            source="provider_api",
            source_url=url,
            source_checked_at=self._now_iso(),
            confidence="high",
        )

    async def _fetch_ollama(self, *, model: str, api_url: str, session=None) -> ModelCapability | None:
        if session is None:
            return None
        base = str(api_url or "http://127.0.0.1:11434/api/chat")
        root = base.split("/api/")[0].rstrip("/")
        show_url = f"{root}/api/show"
        try:
            async with session.post(show_url, json={"name": model}) as resp:
                if resp.status >= 400:
                    return None
                data = await resp.json()
        except Exception:
            return None
        limit = 0
        for key, value in (data.get("model_info") or {}).items():
            if "context_length" in str(key):
                limit = int(value or 0)
                break
        if limit <= 0:
            params = str(data.get("parameters") or "")
            for line in params.splitlines():
                if "num_ctx" in line:
                    try:
                        limit = int(line.split()[-1])
                    except Exception:
                        limit = 0
                    break
        if limit <= 0:
            return None
        return ModelCapability(
            provider="ollama",
            model=model,
            context_window=limit,
            max_output_tokens=_DEFAULT_MAX_OUTPUT_TOKENS,
            source="provider_api",
            source_url=show_url,
            source_checked_at=self._now_iso(),
            confidence="high",
        )


_DEFAULT_RESOLVER: ModelCapabilityResolver | None = None


def get_model_capability_resolver() -> ModelCapabilityResolver:
    global _DEFAULT_RESOLVER
    if _DEFAULT_RESOLVER is None:
        ttl_seconds = int(os.environ.get("MEETYOU_MODEL_CAPABILITY_CACHE_TTL_SECONDS", "86400") or 86400)
        cache_path = os.environ.get("MEETYOU_MODEL_CAPABILITY_CACHE_PATH", "user/runtime/model_capabilities_cache.json")
        _DEFAULT_RESOLVER = ModelCapabilityResolver(cache_path=cache_path, cache_ttl_seconds=ttl_seconds)
    return _DEFAULT_RESOLVER
