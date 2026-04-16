from __future__ import annotations

import re


def build_agent_capability_prefix(agent_id: str) -> str:
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise ValueError("agent_id is required")
    return f"agent.{normalized_agent_id}"


def build_agent_capability_id(agent_id: str, capability_key: str) -> str:
    normalized_key = str(capability_key or "").strip().strip(".")
    if not normalized_key:
        return build_agent_capability_prefix(agent_id)
    return f"{build_agent_capability_prefix(agent_id)}.{normalized_key}"


def slug_capability_segment(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip())
    return cleaned.strip("_") or "item"


def build_mcp_capability_id(agent_id: str, server_name: str, tool_name: str) -> str:
    return f"{build_agent_capability_prefix(agent_id)}.mcp.{slug_capability_segment(server_name)}.{slug_capability_segment(tool_name)}"
