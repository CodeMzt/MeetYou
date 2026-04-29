from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("meetyou.tools_manager")

_BUILTIN_FALLBACK_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "list_workspaces": {
        "type": "function",
        "function": {
            "name": "list_workspaces",
            "description": "List available workspaces and show which workspace is currently active.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_endpoints": {
                        "type": "boolean",
                        "description": "Include endpoint providers registered in each workspace.",
                        "default": False,
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Optional session id for resolving the active workspace.",
                        "default": "",
                    },
                },
                "required": [],
            },
            "metadata": {
                "tool_key": "workspace.list",
                "action_risk": "read",
            },
        },
    },
    "list_endpoint_tool_targets": {
        "type": "function",
        "function": {
            "name": "list_endpoint_tool_targets",
            "description": "List online Endpoint execution targets that can execute tools, optionally scoped to a workspace and tool key.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string", "description": "Optional workspace id.", "default": ""},
                    "tool_key": {"type": "string", "description": "Optional endpoint capability tool key, such as file.read or shell.exec.", "default": ""},
                    "include_tools": {"type": "boolean", "description": "Include each endpoint's capability list.", "default": True},
                },
                "required": [],
            },
            "metadata": {"action_risk": "read", "safe_parallel": True},
        },
    },
    "list_active_endpoints": {
        "type": "function",
        "function": {
            "name": "list_active_endpoints",
            "description": "List currently online Endpoint websocket connections, optionally scoped to a workspace or thread.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string", "description": "Optional workspace id.", "default": ""},
                    "thread_id": {"type": "string", "description": "Optional thread id.", "default": ""},
                    "include_tools": {"type": "boolean", "description": "Include each endpoint's capability list.", "default": True},
                },
                "required": [],
            },
            "metadata": {"action_risk": "read", "safe_parallel": True},
        },
    },
    "send_endpoint_message": {
        "type": "function",
        "function": {
            "name": "send_endpoint_message",
            "description": (
                "Send a realtime notice or dispatch an Endpoint tool call to a target Endpoint other than the "
                "normal current-session reply path. Do not use this to answer the originating user or to send "
                "progress updates to the same endpoint; use emit_progress_notice for progress and the final assistant "
                "answer for the actual reply. Use only when the user explicitly asks to notify or call a "
                "specific target Endpoint."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_type": {"type": "string", "enum": ["endpoint"], "description": "Target endpoint type."},
                    "target_id": {"type": "string", "description": "Target endpoint_id."},
                    "delivery_kind": {"type": "string", "enum": ["notice", "tool_call"], "default": "notice"},
                    "content": {"type": "string", "description": "Notice text when delivery_kind is notice.", "default": ""},
                    "tool_key": {"type": "string", "description": "Endpoint capability tool key for tool_call.", "default": ""},
                    "arguments": {"type": "object", "description": "Tool call arguments.", "default": {}},
                    "workspace_id": {"type": "string", "description": "Workspace id for tool target lookup.", "default": ""},
                    "session_id": {"type": "string", "description": "Session id for operation tracking.", "default": ""},
                    "timeout_seconds": {"type": "integer", "default": 120},
                    "confirmed": {"type": "boolean", "description": "Set true after explicit confirmation for risky tool calls.", "default": False},
                },
                "required": ["target_type", "target_id", "delivery_kind"],
            },
            "metadata": {"action_risk": "external_write", "safe_parallel": False},
        },
    },
    "list_delivery_targets": {
        "type": "function",
        "function": {
            "name": "list_delivery_targets",
            "description": (
                "List V4 delivery addresses inside endpoint providers, such as Feishu chats or WeChat private/group chats. "
                "Use actor_ref=me plus provider_type to check whether the current user has a bound default address."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "provider_type": {"type": "string", "description": "Optional provider filter, e.g. feishu or wechat.", "default": ""},
                    "actor_ref": {"type": "string", "enum": ["", "me"], "description": "Use me to resolve the current actor's bindings.", "default": ""},
                    "address_type": {"type": "string", "enum": ["", "direct", "group", "channel", "room", "inbox"], "default": ""},
                    "workspace_id": {"type": "string", "description": "Optional workspace id.", "default": ""},
                    "include_unavailable": {"type": "boolean", "default": False},
                },
                "required": [],
            },
            "metadata": {"action_risk": "read", "safe_parallel": True},
        },
    },
    "set_delivery_preference": {
        "type": "function",
        "function": {
            "name": "set_delivery_preference",
            "description": (
                "Bind the current actor ('me') to a provider-specific EndpointAddress, such as the user's default Feishu chat. "
                "Call this only after the user has confirmed which address should be used."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "provider_type": {"type": "string", "description": "Provider type, e.g. feishu or wechat."},
                    "address_id": {"type": "string", "description": "EndpointAddress id selected by the user."},
                    "actor_ref": {"type": "string", "enum": ["me"], "default": "me"},
                    "alias": {"type": "string", "description": "Alias for this binding. Default is me.", "default": "me"},
                    "verified": {"type": "boolean", "default": True},
                    "is_default": {"type": "boolean", "default": True},
                    "metadata": {"type": "object", "default": {}},
                },
                "required": ["provider_type", "address_id"],
            },
            "metadata": {"action_risk": "local_write", "safe_parallel": False},
        },
    },
    "send_delivery_message": {
        "type": "function",
        "function": {
            "name": "send_delivery_message",
            "description": (
                "Send a one-off message to a V4 delivery address or to actor_ref=me on a provider. "
                "This uses Delivery and EndpointAddress, not the endpoint-only send_endpoint_message path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Message text to deliver."},
                    "address_id": {"type": "string", "description": "Direct EndpointAddress id.", "default": ""},
                    "actor_ref": {"type": "string", "enum": ["", "me"], "default": ""},
                    "provider_type": {"type": "string", "description": "Provider type when actor_ref=me.", "default": ""},
                    "alias": {"type": "string", "default": "me"},
                    "message_type": {"type": "string", "enum": ["notice", "message"], "default": "notice"},
                    "offline_policy": {"type": "string", "enum": ["store_and_retry", "store_in_outbox", "queue_until_online", "drop"], "default": "store_and_retry"},
                    "workspace_id": {"type": "string", "default": ""},
                    "session_id": {"type": "string", "default": ""},
                },
                "required": ["content"],
            },
            "metadata": {"action_risk": "external_write", "safe_parallel": False},
        },
    },
    "emit_progress_notice": {
        "type": "function",
        "function": {
            "name": "emit_progress_notice",
            "description": (
                "Emit a brief assistant.progress_notice RunEvent for the current session while the current turn is "
                "still thinking or tool-calling. It is not the final assistant answer, does not create an Operation, "
                "and must not be used to answer the user. You must call this before any potentially time-consuming operation, "
                "including web/page reading, research, local file or workspace work, endpoint tool calls, "
                "endpoint messaging, or other slow I/O. For non-streaming external endpoints such as Feishu or "
                "WeChat/MeetWeChat, only use it for genuine progress notices; the final answer must be delivered as "
                "the persisted assistant Message. May be called multiple times."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "A short progress notice, ideally one sentence."}
                },
                "required": ["content"],
            },
            "metadata": {"action_risk": "local_write", "safe_parallel": False},
        },
    },
    "manage_heartbeat_settings": {
        "type": "function",
        "function": {
            "name": "manage_heartbeat_settings",
            "description": "Read or update Scheduler-owned system.heartbeat settings and idle proactive-poke settings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "update"],
                        "description": "Use get to inspect system.heartbeat plus idle settings, or update to change allowed fields.",
                    },
                    "updates": {
                        "type": "object",
                        "description": (
                            "Allowed keys: system_heartbeat_enabled, system_heartbeat_interval_seconds, "
                            "heartbeat_idle_poke_enabled, heartbeat_idle_poke_after_seconds, "
                            "heartbeat_idle_poke_cooldown_seconds, heartbeat_idle_context_compaction_enabled."
                        ),
                        "properties": {
                            "system_heartbeat_enabled": {"type": "boolean"},
                            "system_heartbeat_interval_seconds": {"type": "integer", "minimum": 1},
                            "heartbeat_idle_poke_enabled": {"type": "boolean"},
                            "heartbeat_idle_poke_after_seconds": {"type": "integer", "minimum": 1},
                            "heartbeat_idle_poke_cooldown_seconds": {"type": "integer", "minimum": 1},
                            "heartbeat_idle_context_compaction_enabled": {"type": "boolean"},
                        },
                        "additionalProperties": False,
                    },
                },
                "required": ["action"],
            },
            "metadata": {"action_risk": "local_write", "safe_parallel": False},
        },
    },
    "manage_scheduled_jobs": {
        "type": "function",
        "function": {
            "name": "manage_scheduled_jobs",
            "description": (
                "Advanced low-level V4 Scheduler maintenance for scheduled_jobs and system.heartbeat. "
                "Do not use this as the first choice for user reminders or recurring assistant work; use "
                "create_scheduled_workflow/manage_scheduled_workflows, or create_scheduled_delivery when the output is a message delivery."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "detail", "create", "update", "enable", "disable", "delete", "trigger"],
                        "description": "Scheduler job action.",
                    },
                    "job_id": {"type": "string", "description": "Stable Scheduler job id, for example system.heartbeat."},
                    "kind": {
                        "type": "string",
                        "enum": ["scheduled_workflow", "workflow", "user_task", "maintenance"],
                        "description": "Job kind for create. system.heartbeat is a built-in Scheduler preset and cannot be created here.",
                        "default": "scheduled_workflow",
                    },
                    "name": {"type": "string", "description": "Human-readable job name.", "default": ""},
                    "workspace_id": {"type": "string", "description": "Workspace public id when the job is workspace scoped.", "default": ""},
                    "singleton_key": {"type": "string", "description": "Optional singleton key.", "default": ""},
                    "enabled": {"type": "boolean", "description": "Enabled state for create/update."},
                    "trigger_type": {
                        "type": "string",
                        "enum": ["interval", "daily", "cron", "one_shot", "manual", "event"],
                        "default": "interval",
                    },
                    "trigger_config": {
                        "type": "object",
                        "description": "Structured trigger config. For system.heartbeat updates this may only contain type=interval and interval_seconds.",
                        "default": {},
                    },
                    "interval_seconds": {
                        "type": "integer",
                        "description": "Shortcut for trigger_config.interval_seconds on interval jobs.",
                        "minimum": 1,
                    },
                    "timezone": {"type": "string", "description": "IANA timezone name for ordinary jobs. Do not set this when updating system.heartbeat.", "default": "UTC"},
                    "action_ref": {
                        "type": "string",
                        "enum": ["core.workflow.scheduled_workflow", "core.workflow.assistant_turn", "core.workflow.noop", ""],
                        "description": "Core workflow/action reference for ordinary jobs. Use core.workflow.scheduled_workflow for new scheduled assistant work; omit this field when updating system.heartbeat.",
                        "default": "core.workflow.scheduled_workflow",
                    },
                    "run_template": {
                        "type": "object",
                        "description": "Assistant turn template for core.workflow.assistant_turn jobs.",
                        "properties": {
                            "prompt": {"type": "string", "description": "User-facing instruction for the scheduled assistant turn."},
                            "messages": {"type": "array", "description": "Optional full message list; overrides prompt when provided.", "items": {"type": "object"}},
                            "thread_id": {"type": "string", "description": "Existing Thread id for persisted output, or empty to create/reuse the job thread."},
                            "create_thread": {"type": "boolean", "description": "Create a Core-owned Thread when no thread_id/session_id is supplied.", "default": True},
                            "tool_bundle": {"type": "array", "items": {"type": "string"}, "description": "Optional allowlist from Scheduler job tools."},
                            "mcp_servers": {"type": "array", "items": {"type": "string"}, "description": "Optional Core-side MCP server ids."},
                            "preferred_tool_key": {"type": "string", "description": "Preferred EndpointCapability tool key for routed endpoint work."},
                            "preferred_target_endpoint_ids": {"type": "array", "items": {"type": "string"}},
                            "preferred_endpoint_provider_types": {"type": "array", "items": {"type": "string"}},
                            "tool_target_routing_policy": {"type": "string", "enum": ["balanced", "prefer_origin_endpoint", "strict_preferred_endpoint"], "default": "balanced"},
                            "max_rounds": {"type": "integer", "minimum": 1, "default": 6},
                        },
                        "default": {},
                    },
                    "execution_policy": {"type": "object", "description": "Run execution policy.", "default": {}},
                    "delivery_policy": {
                        "type": "object",
                        "description": "Delivery policy for produced messages and run events.",
                        "properties": {
                            "thread_id": {"type": "string", "description": "Thread subscription target for RunEvent fan-out."},
                            "session_id": {"type": "string", "description": "Existing session to attach output to."},
                            "targets": {
                                "type": "array",
                                "description": "Optional endpoint outbox targets for DeliveryService.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "endpoint_id": {"type": "string"},
                                        "message_type": {"type": "string", "enum": ["message", "notice", "run_event", "operation_update"], "default": "message"},
                                        "offline_policy": {"type": "string", "enum": ["store_and_retry", "store_in_outbox", "queue_until_online", "drop"], "default": "store_and_retry"},
                                    },
                                },
                            },
                        },
                        "default": {},
                    },
                    "concurrency_policy": {"type": "object", "description": "Concurrency policy, e.g. {\"mode\":\"skip_if_running\"}.", "default": {}},
                    "misfire_policy": {"type": "object", "description": "Misfire policy, e.g. {\"mode\":\"run_once\"}.", "default": {}},
                    "metadata": {"type": "object", "description": "Additional metadata.", "default": {}},
                },
                "required": ["action"],
            },
            "metadata": {"action_risk": "local_write", "safe_parallel": False},
        },
    },
    "create_scheduled_workflow": {
        "type": "function",
        "function": {
            "name": "create_scheduled_workflow",
            "description": (
                "Create a flexible V4 Scheduled Workflow. Scheduler only owns the trigger; the workflow can generate text, "
                "search, summarize, organize documents through endpoint tools, or produce other outputs. Message delivery is optional "
                "and is modeled as one output policy, not as the Scheduler's core behavior."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short workflow name."},
                    "schedule": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["daily", "interval", "cron", "one_shot"], "default": "daily"},
                            "time_of_day": {"type": "string", "description": "HH:MM for daily schedules. If the user says only morning, confirm 08:00 Asia/Shanghai first.", "default": "08:00"},
                            "interval_seconds": {"type": "integer", "minimum": 1},
                            "expression": {"type": "string", "description": "Five-field cron expression."},
                            "run_at": {"type": "string", "description": "ISO datetime for one_shot schedules."},
                            "timezone": {"type": "string", "default": "Asia/Shanghai"},
                        },
                        "required": ["type"],
                    },
                    "instruction": {"type": "string", "description": "What Core should do at each fire time."},
                    "timezone": {"type": "string", "default": "Asia/Shanghai"},
                    "workflow_type": {"type": "string", "enum": ["assistant_run", "tool_workflow", "external_workflow"], "default": "assistant_run"},
                    "mode": {"type": "string", "enum": ["general", "automation", "danxi"], "default": "automation"},
                    "tool_policy": {
                        "type": "object",
                        "description": "Optional execution-tool policy for the workflow.",
                        "properties": {
                            "tool_bundle": {"type": "array", "items": {"type": "string"}, "description": "Allowed tools for the scheduled Run."},
                            "mcp_servers": {"type": "array", "items": {"type": "string"}},
                            "preferred_tool_key": {"type": "string"},
                            "preferred_target_endpoint_ids": {"type": "array", "items": {"type": "string"}},
                            "preferred_endpoint_provider_types": {"type": "array", "items": {"type": "string"}},
                            "tool_target_routing_policy": {"type": "string", "enum": ["balanced", "prefer_origin_endpoint", "strict_preferred_endpoint"], "default": "balanced"},
                            "max_rounds": {"type": "integer", "minimum": 1, "default": 6},
                        },
                        "default": {},
                    },
                    "output_policy": {
                        "type": "object",
                        "description": "Optional outputs. By default the final assistant reply is persisted to a Core Thread only.",
                        "properties": {
                            "persist_message": {"type": "boolean", "description": "V4 assistant workflows must persist the final assistant Message; false is rejected.", "default": True},
                            "create_thread": {"type": "boolean", "description": "Create a Core Thread when no thread_id/session_id is supplied. false requires an existing thread_id or session_id.", "default": True},
                            "thread_id": {"type": "string"},
                            "session_id": {"type": "string"},
                            "output_kinds": {"type": "array", "items": {"type": "string"}, "default": ["assistant_message"]},
                            "delivery_targets": {
                                "type": "array",
                                "description": "Optional EndpointAddress/Actor delivery targets for generated assistant messages.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "address_id": {"type": "string"},
                                        "actor_ref": {"type": "string", "enum": ["me"]},
                                        "provider_type": {"type": "string"},
                                        "alias": {"type": "string", "default": "me"},
                                        "endpoint_id": {"type": "string"},
                                        "message_type": {"type": "string", "enum": ["message", "notice"], "default": "message"},
                                        "offline_policy": {"type": "string", "enum": ["store_and_retry", "store_in_outbox", "queue_until_online", "drop"], "default": "store_and_retry"},
                                    },
                                },
                            },
                            "delivery_policy": {"type": "object", "default": {}},
                        },
                        "default": {},
                    },
                    "workspace_id": {"type": "string", "default": "personal"},
                    "enabled": {"type": "boolean", "default": True},
                    "metadata": {"type": "object", "default": {}},
                },
                "required": ["name", "schedule", "instruction"],
            },
            "metadata": {"action_risk": "external_write", "safe_parallel": False},
        },
    },
    "manage_scheduled_workflows": {
        "type": "function",
        "function": {
            "name": "manage_scheduled_workflows",
            "description": "List, inspect, update, enable, disable, delete, or manually trigger V4 scheduled_workflow jobs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "detail", "update", "enable", "disable", "delete", "trigger"], "default": "list"},
                    "job_id": {"type": "string", "description": "Scheduled workflow job id."},
                    "enabled": {"type": "boolean"},
                    "schedule": {"type": "object", "description": "Replacement schedule config."},
                    "timezone": {"type": "string", "default": ""},
                    "instruction": {"type": "string", "default": ""},
                    "tool_policy": {"type": "object", "default": {}},
                    "output_policy": {"type": "object", "default": {}},
                    "workspace_id": {"type": "string", "default": "personal"},
                },
                "required": ["action"],
            },
            "metadata": {"action_risk": "local_write", "safe_parallel": False},
        },
    },
    "create_scheduled_delivery": {
        "type": "function",
        "function": {
            "name": "create_scheduled_delivery",
            "description": (
                "Convenience wrapper for a Scheduled Workflow whose output is message delivery. Use only when the user explicitly "
                "wants the scheduled result sent to Feishu/WeChat/email/etc.; otherwise use create_scheduled_workflow."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short job name."},
                    "schedule": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["daily", "interval", "cron", "one_shot"], "default": "daily"},
                            "time_of_day": {"type": "string", "description": "HH:MM for daily schedules. If the user says only morning, confirm 08:00 Asia/Shanghai first.", "default": "08:00"},
                            "interval_seconds": {"type": "integer", "minimum": 1},
                            "expression": {"type": "string", "description": "Five-field cron expression."},
                            "run_at": {"type": "string", "description": "ISO datetime for one_shot schedules."},
                            "timezone": {"type": "string", "default": "Asia/Shanghai"},
                        },
                        "required": ["type"],
                    },
                    "target": {
                        "type": "object",
                        "properties": {
                            "address_id": {"type": "string", "description": "EndpointAddress id."},
                            "actor_ref": {"type": "string", "enum": ["me"]},
                            "provider_type": {"type": "string", "description": "Provider type when actor_ref=me, e.g. feishu."},
                            "alias": {"type": "string", "default": "me"},
                        },
                    },
                    "instruction": {"type": "string", "description": "What the assistant should generate at each fire time."},
                    "timezone": {"type": "string", "default": "Asia/Shanghai"},
                    "generation_policy": {"type": "string", "enum": ["generate_at_fire_time"], "default": "generate_at_fire_time"},
                    "delivery_policy": {"type": "object", "default": {}},
                    "workspace_id": {"type": "string", "default": "personal"},
                    "enabled": {"type": "boolean", "default": True},
                    "metadata": {"type": "object", "default": {}},
                },
                "required": ["name", "schedule", "target", "instruction"],
            },
            "metadata": {"action_risk": "local_write", "safe_parallel": False},
        },
    },
    "manage_scheduled_deliveries": {
        "type": "function",
        "function": {
            "name": "manage_scheduled_deliveries",
            "description": "List, inspect, update, enable, disable, delete, or manually trigger delivery-flavored scheduled_workflow jobs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "detail", "update", "enable", "disable", "delete", "trigger"], "default": "list"},
                    "job_id": {"type": "string", "description": "Scheduled delivery job id."},
                    "enabled": {"type": "boolean"},
                    "schedule": {"type": "object", "description": "Replacement schedule config."},
                    "timezone": {"type": "string", "default": ""},
                    "instruction": {"type": "string", "default": ""},
                    "target": {"type": "object", "default": {}},
                    "delivery_policy": {"type": "object", "default": {}},
                    "workspace_id": {"type": "string", "default": "personal"},
                },
                "required": ["action"],
            },
            "metadata": {"action_risk": "local_write", "safe_parallel": False},
        },
    },
    "restart_core": {
        "type": "function",
        "function": {
            "name": "restart_core",
            "description": "Restart the Core Service after validating the admin password.",
            "parameters": {
                "type": "object",
                "properties": {
                    "password": {"type": "string", "description": "Core admin password."},
                    "reason": {"type": "string", "description": "Optional restart reason.", "default": ""},
                    "delay_seconds": {"type": "integer", "description": "Delay before graceful restart.", "default": 1},
                },
                "required": ["password"],
            },
            "metadata": {"action_risk": "destructive", "safe_parallel": False},
        },
    },
}


def _tool_name(tool: dict[str, Any] | None) -> str:
    if not isinstance(tool, dict):
        return ""
    function = tool.get("function")
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "").strip()


def _deduplicate_tools(
    tools: list[dict[str, Any]] | None,
    *,
    source_label: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    deduplicated: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    for tool in tools or []:
        name = _tool_name(tool)
        if not name:
            deduplicated.append(tool)
            continue
        if name in seen:
            duplicates.append(name)
            continue
        seen.add(name)
        deduplicated.append(tool)
    if duplicates:
        logger.warning(
            "Duplicate tool schemas ignored in %s: %s",
            source_label,
            ", ".join(sorted(set(duplicates))),
        )
    return deduplicated, duplicates


class ToolRegistry:
    def __init__(self, mcp_manager, *, supported_funcs: dict[str, Any] | None = None):
        self.tools_schema_dict: dict[str, Any] = {}
        self._mcp_manager = mcp_manager
        self.supported_funcs: dict[str, Any] = dict(supported_funcs or {})

    async def init_tools(self, tools_schema_path: str, mcp_servers: dict[str, Any]) -> None:
        with open(tools_schema_path, "r", encoding="utf-8") as handle:
            self.tools_schema_dict = json.load(handle)
        for key in ("common_tools", "chain_tools", "memory_tools", "background_tools", "web_tools"):
            tools, _ = _deduplicate_tools(
                self.tools_schema_dict.get(key, []),
                source_label=f"tools schema section [{key}]",
            )
            self.tools_schema_dict[key] = tools
        self._inject_builtin_fallback_tool_schemas()
        self._patch_builtin_tool_schemas()

        await self._mcp_manager.init_mcp_servers(mcp_servers)
        self.tools_schema_dict["mcp_tools"] = []
        seen_mcp_tool_names: set[str] = set()
        for server_name in getattr(self._mcp_manager, "mcp_servers_list", []):
            tools, _ = _deduplicate_tools(
                self._mcp_manager.mcp_tools.get(server_name, []),
                source_label=f"MCP server [{server_name}]",
            )
            for tool in tools:
                tool_name = _tool_name(tool)
                if tool_name and tool_name in seen_mcp_tool_names:
                    logger.warning(
                        "Duplicate MCP tool schema ignored across servers: %s (server=%s)",
                        tool_name,
                        server_name,
                    )
                    continue
                if tool_name:
                    seen_mcp_tool_names.add(tool_name)
                self.tools_schema_dict["mcp_tools"].append(tool)

        logger.info(
            "Tools initialized: built-in=%s, mcp=%s",
            len(self.supported_funcs),
            len(self.tools_schema_dict.get("mcp_tools", [])),
        )

    def _inject_builtin_fallback_tool_schemas(self) -> None:
        visible_sections = ("common_tools", "chain_tools", "memory_tools", "background_tools", "web_tools")
        known_names = {
            _tool_name(tool)
            for section in visible_sections
            for tool in self.tools_schema_dict.get(section, [])
            if _tool_name(tool)
        }
        common_tools = self.tools_schema_dict.setdefault("common_tools", [])
        for tool_name, schema in _BUILTIN_FALLBACK_TOOL_SCHEMAS.items():
            if tool_name not in self.supported_funcs or tool_name in known_names:
                continue
            common_tools.append(schema)
            known_names.add(tool_name)

    def _patch_builtin_tool_schemas(self) -> None:
        for tool in self.tools_schema_dict.get("common_tools", []):
            function = tool.get("function") if isinstance(tool, dict) else None
            if not isinstance(function, dict):
                continue
            fallback = _BUILTIN_FALLBACK_TOOL_SCHEMAS.get(str(function.get("name") or ""))
            if not isinstance(fallback, dict):
                continue
            fallback_function = fallback.get("function")
            if not isinstance(fallback_function, dict):
                continue
            for key in ("description", "parameters", "metadata"):
                if key in fallback_function:
                    function[key] = fallback_function[key]
        for tool in self.tools_schema_dict.get("chain_tools", []):
            function = tool.get("function") if isinstance(tool, dict) else None
            if not isinstance(function, dict):
                continue
            fallback = _BUILTIN_FALLBACK_TOOL_SCHEMAS.get(str(function.get("name") or ""))
            if not isinstance(fallback, dict):
                continue
            fallback_function = fallback.get("function")
            if not isinstance(fallback_function, dict):
                continue
            for key in ("description", "parameters", "metadata"):
                if key in fallback_function:
                    function[key] = fallback_function[key]

    def has_builtin(self, tool_name: str) -> bool:
        return tool_name in self.supported_funcs

    def get_builtin(self, tool_name: str):
        return self.supported_funcs.get(tool_name)

    def has_mcp(self, tool_name: str) -> bool:
        return tool_name in getattr(self._mcp_manager, "tool_map", {})

    def get_mcp_server(self, tool_name: str) -> str:
        return str(getattr(self._mcp_manager, "tool_map", {}).get(tool_name, ""))

    def get_tool_capability_metadata(self, tool_name: str) -> dict[str, Any]:
        normalized_tool_name = str(tool_name or "").strip()
        metadata: dict[str, Any] = {
            "tool_name": normalized_tool_name,
            "source": "unknown",
            "schema_metadata": {},
        }
        if self.has_builtin(normalized_tool_name):
            metadata["source"] = "builtin"
        elif self.has_mcp(normalized_tool_name):
            metadata["source"] = "mcp"
            metadata["mcp_server"] = self.get_mcp_server(normalized_tool_name)

        schema = self._tool_schema_by_name(
            normalized_tool_name,
            sections=("common_tools", "chain_tools", "memory_tools", "background_tools", "web_tools", "mcp_tools"),
        )
        if isinstance(schema, dict):
            function_schema = schema.get("function", {})
            if isinstance(function_schema, dict):
                schema_metadata = function_schema.get("metadata")
                if isinstance(schema_metadata, dict):
                    metadata["schema_metadata"] = dict(schema_metadata)
        return metadata

    def _iter_llm_visible_tools(self, *, allowed_tool_names: set[str] | None = None) -> list[dict]:
        tools: list[dict] = []
        seen: set[str] = set()
        for key in ("common_tools", "chain_tools"):
            for tool in self.tools_schema_dict.get(key, []):
                tool_name = tool.get("function", {}).get("name", "")
                if tool_name in seen:
                    continue
                seen.add(tool_name)
                tools.append(tool)
        if allowed_tool_names:
            for key in ("memory_tools", "web_tools"):
                for tool in self.tools_schema_dict.get(key, []):
                    tool_name = tool.get("function", {}).get("name", "")
                    if tool_name not in allowed_tool_names or tool_name in seen:
                        continue
                    seen.add(tool_name)
                    tools.append(tool)
        return tools

    def _tool_schema_by_name(self, tool_name: str, sections: tuple[str, ...] | None = None) -> dict | None:
        keys = sections or ("common_tools", "chain_tools", "memory_tools", "background_tools")
        for key in keys:
            for tool in self.tools_schema_dict.get(key, []):
                function = tool.get("function", {})
                if function.get("name") == tool_name:
                    return tool
        return None

    def get_all_tools(
        self,
        route_context: dict[str, Any] | None = None,
        *,
        should_expose_mcp_tool,
    ) -> list[dict]:
        route_context = route_context or {}
        allowed_tool_names = {
            str(item).strip()
            for item in route_context.get("tool_bundle", [])
            if str(item).strip()
        }
        allowed_mcp_servers = {
            str(item).strip()
            for item in route_context.get("mcp_servers", [])
            if str(item).strip()
        }

        visible_tools: list[dict] = []
        for tool in self._iter_llm_visible_tools(allowed_tool_names=allowed_tool_names):
            function = tool.get("function", {})
            tool_name = function.get("name", "")
            if tool_name not in self.supported_funcs:
                continue
            if allowed_tool_names and tool_name not in allowed_tool_names:
                continue
            visible_tools.append(tool)

        visible_tool_names = {
            str(tool.get("function", {}).get("name", "")).strip()
            for tool in visible_tools
            if str(tool.get("function", {}).get("name", "")).strip()
        }
        for tool in self.tools_schema_dict.get("mcp_tools", []):
            function = tool.get("function", {})
            tool_name = function.get("name", "")
            server_name = self.get_mcp_server(tool_name)
            if tool_name in visible_tool_names:
                continue
            if not should_expose_mcp_tool(tool_name, server_name):
                continue
            if allowed_mcp_servers and server_name not in allowed_mcp_servers and tool_name not in allowed_tool_names:
                continue
            visible_tools.append(tool)
            if tool_name:
                visible_tool_names.add(tool_name)
        return visible_tools

    def get_heartbeat_tools(self) -> list[dict]:
        allowlist = (
            "get_background_status",
            "get_current_system_time",
            "get_sys_vitals",
        )
        return [
            tool
            for name in allowlist
            if (tool := self._tool_schema_by_name(name, sections=("background_tools", "common_tools", "memory_tools"))) is not None
        ]

    def get_scheduled_job_tools(self) -> list[dict]:
        allowlist = (
            "research_topic",
            "track_source_updates",
            "manage_scheduled_jobs",
            "get_current_system_time",
            "emit_progress_notice",
            "search_knowledge",
            "search_memory",
            "search_web",
            "read_web_page",
            "remember_knowledge",
            "summarize_text",
            "organize_notes",
            "extract_action_items",
            "analyze_workspace",
            "read_local_documents",
            "write_local_document",
            "rewrite_local_document",
            "compile_report",
        )
        return [
            tool
            for name in allowlist
            if (tool := self._tool_schema_by_name(name, sections=("chain_tools", "common_tools", "memory_tools", "web_tools"))) is not None
        ]

