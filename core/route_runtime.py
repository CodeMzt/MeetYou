from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RouteRuntime:
    requested_mode: str
    current_mode: str
    route_reason: str
    source_profile: str
    tool_bundle: list[str]
    mcp_servers: list[str]
    prompt_bundle: str
    active_skills: list[str] | None = None
    loaded_skills: list[str] | None = None
    confidence: str = ""
    should_preload_context: bool = False
    prefer_live_web: bool = False
    signals: list[str] | None = None
    adapter_name: str = ""
    used_keyword_fallback: bool = False
    authorization_policy: dict[str, Any] | None = None
    capability_set: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_mode": self.requested_mode,
            "current_mode": self.current_mode,
            "route_reason": self.route_reason,
            "source_profile": self.source_profile,
            "tool_bundle": list(self.tool_bundle),
            "mcp_servers": list(self.mcp_servers),
            "prompt_bundle": self.prompt_bundle,
            "active_skills": list(self.active_skills or []),
            "loaded_skills": list(self.loaded_skills or []),
            "confidence": self.confidence,
            "should_preload_context": bool(self.should_preload_context),
            "prefer_live_web": bool(self.prefer_live_web),
            "signals": list(self.signals or []),
            "adapter_name": self.adapter_name,
            "used_keyword_fallback": bool(self.used_keyword_fallback),
            "authorization_policy": dict(self.authorization_policy or {}),
            "capability_set": dict(self.capability_set or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "RouteRuntime":
        payload = payload or {}
        return cls(
            requested_mode=str(payload.get("requested_mode") or "").strip(),
            current_mode=str(payload.get("current_mode") or "").strip(),
            route_reason=str(payload.get("route_reason") or "").strip(),
            source_profile=str(payload.get("source_profile") or "").strip(),
            tool_bundle=[str(item).strip() for item in payload.get("tool_bundle", []) if str(item).strip()],
            mcp_servers=[str(item).strip() for item in payload.get("mcp_servers", []) if str(item).strip()],
            prompt_bundle=str(payload.get("prompt_bundle") or "").strip(),
            active_skills=[str(item).strip() for item in payload.get("active_skills", []) if str(item).strip()],
            loaded_skills=[str(item).strip() for item in payload.get("loaded_skills", []) if str(item).strip()],
            confidence=str(payload.get("confidence") or "").strip(),
            should_preload_context=bool(payload.get("should_preload_context", False)),
            prefer_live_web=bool(payload.get("prefer_live_web", False)),
            signals=[str(item).strip() for item in payload.get("signals", []) if str(item).strip()],
            adapter_name=str(payload.get("adapter_name") or "").strip(),
            used_keyword_fallback=bool(payload.get("used_keyword_fallback", False)),
            authorization_policy=dict(payload.get("authorization_policy") or {}),
            capability_set=dict(payload.get("capability_set") or {}),
        )
