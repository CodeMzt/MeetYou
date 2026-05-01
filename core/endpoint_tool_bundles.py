"""Shared tool bundles for external endpoint adapters."""

from typing import Any

from core.assistant_modes import get_default_assistant_capability_tools


ENDPOINT_ALWAYS_AVAILABLE_TOOLS = ("emit_progress_notice",)

_EXTERNAL_ENDPOINT_DENIED_TOOLS = {
    "exec_sys_cmd",
    "send_endpoint_message",
}

_EXTERNAL_ENDPOINT_BASELINE_TOOLS = [
    "ask_human",
    "get_current_system_time",
    "list_skills",
    "load_skill",
    "create_skill",
    "manage_skill",
    "list_workspaces",
    "switch_workspace",
    "list_active_endpoints",
    "list_endpoint_tool_targets",
    "list_delivery_targets",
    "set_delivery_preference",
    "send_delivery_message",
    "create_scheduled_workflow",
    "manage_scheduled_workflows",
    "create_scheduled_delivery",
    "manage_scheduled_deliveries",
    "emit_progress_notice",
    "restart_core",
    "search_knowledge",
    "search_memory",
    "search_web",
    "read_web_page",
    "remember_knowledge",
    "manage_memories",
    "summarize_text",
    "organize_notes",
    "extract_action_items",
]


def _unique_allowed_tools(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        tool_name = str(item or "").strip()
        if not tool_name or tool_name in _EXTERNAL_ENDPOINT_DENIED_TOOLS or tool_name in seen:
            continue
        seen.add(tool_name)
        result.append(tool_name)
    return result


def _build_external_endpoint_basic_tool_bundle() -> list[str]:
    return _unique_allowed_tools(
        [
            *_EXTERNAL_ENDPOINT_BASELINE_TOOLS,
            *get_default_assistant_capability_tools(include_basic=True),
        ]
    )


EXTERNAL_ENDPOINT_BASIC_TOOL_BUNDLE = _build_external_endpoint_basic_tool_bundle()


def ensure_endpoint_always_available_tools(metadata: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(metadata or {})
    allowed_tool_bundle = normalized.get("allowed_tool_bundle")
    if not isinstance(allowed_tool_bundle, list):
        return normalized
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in allowed_tool_bundle:
        tool_name = str(item or "").strip()
        if not tool_name or tool_name in seen:
            continue
        seen.add(tool_name)
        cleaned.append(tool_name)
    for tool_name in ENDPOINT_ALWAYS_AVAILABLE_TOOLS:
        if tool_name not in seen:
            cleaned.append(tool_name)
            seen.add(tool_name)
    normalized["allowed_tool_bundle"] = cleaned
    return normalized

