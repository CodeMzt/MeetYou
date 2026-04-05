"""
Shared non-streaming tool-enabled background agent loop.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("meetyou.background_agent")


class BackgroundAgentRunner:
    def __init__(self, adapter, tools_manager):
        self._adapter = adapter
        self._tools_manager = tools_manager

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
                }

            last_tool_names = [tc.name for tc in tool_calls]
            for tool_call in tool_calls:
                tool_args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
                if tool_call.name in {"manage_tasks", "manage_scheduled_tasks"}:
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
                    tool_result = f"Error: tool {tool_call.name} failed: {exc}"

                history.append(
                    {
                        "role": "tool",
                        "content": tool_result if isinstance(tool_result, str) else str(tool_result),
                        "tool_call_id": tool_call.id,
                    }
                )

        return {
            "status": "error",
            "content": "Error: background agent exceeded max tool rounds.",
            "tool_names": last_tool_names,
            "completed_task_keys": list(dict.fromkeys(completed_task_keys)),
            "manage_task_actions": manage_task_actions,
            "history": history,
        }
