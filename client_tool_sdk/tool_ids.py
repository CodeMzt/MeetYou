from __future__ import annotations

import re


def build_client_tool_prefix(client_id: str) -> str:
    normalized_client_id = str(client_id or "").strip()
    if not normalized_client_id:
        raise ValueError("client_id is required")
    return f"client.{normalized_client_id}"


def build_client_tool_id(client_id: str, tool_key: str) -> str:
    normalized_key = str(tool_key or "").strip().strip(".")
    if not normalized_key:
        return build_client_tool_prefix(client_id)
    return f"{build_client_tool_prefix(client_id)}.{normalized_key}"


def slug_tool_segment(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip())
    return cleaned.strip("_") or "item"


def build_mcp_tool_id(client_id: str, server_name: str, tool_name: str) -> str:
    return f"{build_client_tool_prefix(client_id)}.mcp.{slug_tool_segment(server_name)}.{slug_tool_segment(tool_name)}"
