from __future__ import annotations

from typing import Any

PUBLIC_MODE_GENERAL = "general"
PUBLIC_MODE_RESEARCH = "research"
PUBLIC_MODE_DOCUMENTS = "documents"
PUBLIC_MODE_STUDY = "study"
PUBLIC_MODE_AUTOMATION = "automation"
PUBLIC_MODE_DANXI = "danxi"

PUBLIC_ASSISTANT_MODES = (
    PUBLIC_MODE_GENERAL,
    PUBLIC_MODE_RESEARCH,
    PUBLIC_MODE_DOCUMENTS,
    PUBLIC_MODE_STUDY,
    PUBLIC_MODE_AUTOMATION,
    PUBLIC_MODE_DANXI,
)

# Transitional mapping while the legacy assistant-mode runtime is still in place.
_LEGACY_TO_PUBLIC_MODE = {
    "normal": PUBLIC_MODE_GENERAL,
    "auto": PUBLIC_MODE_GENERAL,
    "office": PUBLIC_MODE_AUTOMATION,
}

_PUBLIC_TO_INTERNAL_MODE = {
    PUBLIC_MODE_GENERAL: "auto",
    PUBLIC_MODE_RESEARCH: "research",
    PUBLIC_MODE_DOCUMENTS: "documents",
    PUBLIC_MODE_STUDY: "study",
    PUBLIC_MODE_AUTOMATION: "office",
    PUBLIC_MODE_DANXI: "danxi",
}

_INTERNAL_ASSISTANT_MODES = {
    "auto",
    "normal",
    "research",
    "documents",
    "study",
    "office",
    "danxi",
}

EXECUTION_TARGET_CORE_ONLY = "core_only"
EXECUTION_TARGET_CORE_LOCAL = "core.local"
EXECUTION_TARGET_SPECIFIC_ENDPOINT = "specific_endpoint"
EXECUTION_TARGET_WORKSPACE_ANY_ENDPOINT = "workspace_any_endpoint"
EXECUTION_TARGET_PREFER_ENDPOINT_FALLBACK_CORE = "prefer_endpoint_fallback_core"

EXECUTION_TARGETS = (
    EXECUTION_TARGET_CORE_ONLY,
    EXECUTION_TARGET_CORE_LOCAL,
    EXECUTION_TARGET_SPECIFIC_ENDPOINT,
    EXECUTION_TARGET_WORKSPACE_ANY_ENDPOINT,
    EXECUTION_TARGET_PREFER_ENDPOINT_FALLBACK_CORE,
)

# TODO(v4-cutover): remove after the old HTTP client route module is replaced by Thread/Run/Delivery routes.
EXECUTION_TARGET_SPECIFIC_CLIENT = EXECUTION_TARGET_SPECIFIC_ENDPOINT
EXECUTION_TARGET_WORKSPACE_ANY_CLIENT = EXECUTION_TARGET_WORKSPACE_ANY_ENDPOINT
EXECUTION_TARGET_PREFER_CLIENT_FALLBACK_CORE = EXECUTION_TARGET_PREFER_ENDPOINT_FALLBACK_CORE

_EXECUTION_TARGET_ALIASES = {
    "assistant": EXECUTION_TARGET_CORE_LOCAL,
    "core": EXECUTION_TARGET_CORE_LOCAL,
    "core_only": EXECUTION_TARGET_CORE_LOCAL,
    "desktop": EXECUTION_TARGET_SPECIFIC_ENDPOINT,
}


def to_public_assistant_mode(value: Any, *, fallback: str = PUBLIC_MODE_GENERAL) -> str:
    normalized = str(value or "").strip().lower()
    normalized = _LEGACY_TO_PUBLIC_MODE.get(normalized, normalized)
    if normalized in PUBLIC_ASSISTANT_MODES:
        return normalized
    return fallback


def to_internal_assistant_mode(value: Any, *, fallback: str = "auto") -> str:
    fallback_normalized = str(fallback or "").strip().lower()
    if not fallback_normalized:
        fallback_internal = ""
    elif fallback_normalized in _INTERNAL_ASSISTANT_MODES:
        fallback_internal = fallback_normalized
    else:
        fallback_internal = _PUBLIC_TO_INTERNAL_MODE[to_public_assistant_mode(fallback, fallback=PUBLIC_MODE_GENERAL)]
    normalized = str(value or "").strip().lower()
    if not normalized:
        return fallback_internal
    if normalized in _INTERNAL_ASSISTANT_MODES:
        return normalized
    public_mode = _LEGACY_TO_PUBLIC_MODE.get(normalized, normalized)
    if public_mode in PUBLIC_ASSISTANT_MODES:
        return _PUBLIC_TO_INTERNAL_MODE.get(public_mode, fallback_internal)
    return fallback_internal


def normalize_execution_target(value: Any, *, fallback: str = EXECUTION_TARGET_CORE_ONLY) -> str:
    normalized = str(value or "").strip().lower()
    normalized = _EXECUTION_TARGET_ALIASES.get(normalized, normalized)
    if normalized in EXECUTION_TARGETS:
        return normalized
    return fallback


def requires_specific_endpoint(value: Any) -> bool:
    return normalize_execution_target(value) == EXECUTION_TARGET_SPECIFIC_ENDPOINT


def requires_specific_client(value: Any) -> bool:
    return requires_specific_endpoint(value)
