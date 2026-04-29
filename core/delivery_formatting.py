from __future__ import annotations

import copy
import re
from typing import Any


_TEXT_FIELD_KEYS = {"content", "text", "delta"}
_MARKDOWN_FALSE_PROVIDER_TYPES = {"feishu", "wechat", "meetwechat", "wechatbot"}


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _metadata_supports_markdown(metadata: dict[str, Any], *, provider_type: str = "", default: bool = True) -> bool:
    if "supports_markdown" in metadata:
        return _coerce_bool(metadata.get("supports_markdown"), default=default)
    provider = metadata.get("provider")
    if isinstance(provider, dict) and "supports_markdown" in provider:
        return _coerce_bool(provider.get("supports_markdown"), default=default)
    normalized_provider = str(provider_type or metadata.get("provider_type") or "").strip().lower()
    if normalized_provider in _MARKDOWN_FALSE_PROVIDER_TYPES:
        return False
    return default


def delivery_target_supports_markdown(target_endpoint=None, target_address=None) -> bool:
    endpoint_meta = dict(getattr(target_endpoint, "meta", {}) or {})
    endpoint_provider_type = str(getattr(target_endpoint, "provider_type", "") or "")
    endpoint_default = _metadata_supports_markdown(endpoint_meta, provider_type=endpoint_provider_type, default=True)
    if target_address is None:
        return endpoint_default

    address_meta = dict(getattr(target_address, "meta", {}) or {})
    address_provider_type = str(getattr(target_address, "provider_type", "") or endpoint_provider_type)
    return _metadata_supports_markdown(address_meta, provider_type=address_provider_type, default=endpoint_default)


def markdown_to_plain_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return ""

    text = re.sub(r"```[ \t]*(\w+)?\n([\s\S]*?)```", lambda match: match.group(2).strip("\n"), text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", lambda match: match.group(1).strip(), text)

    def _link(match: re.Match) -> str:
        label = match.group(1).strip()
        url = match.group(2).strip()
        if not label:
            return url
        if label == url:
            return label
        return f"{label} ({url})"

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    text = re.sub(r"~~(.*?)~~", r"\1", text)
    text = re.sub(r"^\s*[-:| ]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def format_delivery_payload_for_endpoint(payload: dict[str, Any], *, supports_markdown: bool) -> dict[str, Any]:
    formatted = copy.deepcopy(dict(payload or {}))
    if supports_markdown:
        return formatted
    return _plain_text_fields(formatted)


def _plain_text_fields(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in _TEXT_FIELD_KEYS and isinstance(item, str):
                result[key] = markdown_to_plain_text(item)
            else:
                result[key] = _plain_text_fields(item)
        return result
    if isinstance(value, list):
        return [_plain_text_fields(item) for item in value]
    return value
