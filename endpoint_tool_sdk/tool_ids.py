from __future__ import annotations

import re


def build_endpoint_tool_prefix(endpoint_id: str) -> str:
    normalized_endpoint_id = str(endpoint_id or "").strip()
    if not normalized_endpoint_id:
        raise ValueError("endpoint_id is required")
    return f"endpoint.{normalized_endpoint_id}"


def build_endpoint_tool_id(endpoint_id: str, tool_key: str) -> str:
    normalized_key = str(tool_key or "").strip().strip(".")
    if not normalized_key:
        return build_endpoint_tool_prefix(endpoint_id)
    return f"{build_endpoint_tool_prefix(endpoint_id)}.{normalized_key}"


def slug_tool_segment(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip())
    return cleaned.strip("_") or "item"


def build_endpoint_mcp_tool_id(endpoint_id: str, server_name: str, tool_name: str) -> str:
    return (
        f"{build_endpoint_tool_prefix(endpoint_id)}."
        f"mcp.{slug_tool_segment(server_name)}.{slug_tool_segment(tool_name)}"
    )


__all__ = [
    "build_endpoint_mcp_tool_id",
    "build_endpoint_tool_id",
    "build_endpoint_tool_prefix",
    "slug_tool_segment",
]
