"""
Shared non-streaming tool-enabled background agent loop.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.background_jobs import failure_payload
from core.runtime_context import bind_event_context, reset_event_context
from core.tool_runtime import ToolCallResult, ToolErrorCategory, ToolSourceType, normalize_tool_result

logger = logging.getLogger("meetyou.background_agent")


class BackgroundAgentRunner:
    def __init__(self, adapter, tools_manager):
        self._adapter = adapter
        self._tools_manager = tools_manager

    @staticmethod
    def _should_keep_tool_reasoning_field(adapter_options: dict[str, Any] | None) -> bool:
        return (adapter_options or {}).get("thinking") is not False

    async def run(
        self,
        *,
        session,
        api_url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        session_id: str = "",
        source=None,
        route_context: dict[str, Any] | None = None,
        max_rounds: int = 6,
        adapter_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        history = [dict(message) for message in messages]
        adapter_options = dict(adapter_options or {})
        last_content = ""
        last_tool_names: list[str] = []
        completed_task_keys: list[str] = []
        manage_task_actions: list[dict[str, Any]] = []

        for _ in range(max_rounds):
            result = await self._adapter.chat(
                session,
                api_url,
                api_key,
                model,
                history,
                tools=tools or [],
                **adapter_options,
            )

            last_content = str(result.get("content") or "").strip()
            tool_calls = list(result.get("tool_calls") or [])
            assistant_message: dict[str, Any] = {"role": "assistant", "content": last_content or None}
            if tool_calls:
                reasoning_content = str(result.get("reasoning_content") or "").strip()
                if reasoning_content or self._should_keep_tool_reasoning_field(adapter_options):
                    assistant_message["reasoning_content"] = reasoning_content
                assistant_message["tool_calls"] = [
                    {
                        "type": "function",
                        "id": tc.id,
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments_str,
                        },
                    }
                    for tc in tool_calls
                ]
            history.append(assistant_message)

            if not tool_calls:
                return {
                    "status": "ok",
                    "content": last_content,
                    "tool_names": last_tool_names,
                    "completed_task_keys": list(dict.fromkeys(completed_task_keys)),
                    "manage_task_actions": manage_task_actions,
                    "history": history,
                    "result": {
                        "round_count": len(history),
                        "tool_call_count": len(last_tool_names),
                    },
                }

            last_tool_names = [tc.name for tc in tool_calls]
            for tool_call in tool_calls:
                tool_args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
                if tool_call.name == "manage_tasks":
                    action = str(tool_args.get("action") or "").strip().lower()
                    task_key = str(tool_args.get("task_key") or "").strip()
                    manage_task_actions.append(
                        {
                            "action": action,
                            "task_key": task_key,
                            "arguments": json.loads(json.dumps(tool_args, ensure_ascii=False, default=str)),
                        }
                    )
                    if action == "complete" and task_key:
                        completed_task_keys.append(task_key)
                tool_context = bind_event_context(tool_call_id=tool_call.id)
                try:
                    try:
                        tool_result = await self._tools_manager.call_tool(
                            tool_call.name,
                            tool_args,
                            session_id=session_id,
                            source=source,
                            route_context=route_context or {},
                        )
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.error("Background tool call failed: %s", exc)
                        tool_result = ToolCallResult.failure(
                            tool_name=tool_call.name,
                            source=ToolSourceType.UNKNOWN,
                            action_risk="read",
                            code="tool_dispatch_failed",
                            category=ToolErrorCategory.EXECUTION,
                            message="Tool dispatch failed before producing a result.",
                            details={
                                "tool_name": tool_call.name,
                                "exception_type": type(exc).__name__,
                                "exception_message": str(exc),
                            },
                        )
                        return {
                            "status": "error",
                            "content": tool_result.as_message_content(),
                            "tool_names": last_tool_names,
                            "completed_task_keys": list(dict.fromkeys(completed_task_keys)),
                            "manage_task_actions": manage_task_actions,
                            "history": history,
                            "error": failure_payload(
                                category="retryable",
                                code="background_tool_failed",
                                message=tool_result.error.message if tool_result.error is not None else "",
                                details={"tool_name": tool_call.name},
                            ),
                        }
                finally:
                    reset_event_context(tool_context)

                normalized_result = normalize_tool_result(
                    tool_result,
                    tool_name=tool_call.name,
                    source=ToolSourceType.UNKNOWN,
                    action_risk="read",
                )
                history.append(
                    {
                        "role": "tool",
                        "content": normalized_result.as_message_content(),
                        "tool_call_id": tool_call.id,
                    }
                )

        return {
            "status": "error",
            "content": "Background agent exceeded max tool rounds.",
            "tool_names": last_tool_names,
            "completed_task_keys": list(dict.fromkeys(completed_task_keys)),
            "manage_task_actions": manage_task_actions,
            "history": history,
            "error": failure_payload(
                category="non_retryable",
                retryable=False,
                code="background_agent_max_rounds_exceeded",
                message="Background agent exceeded max tool rounds.",
            ),
        }
