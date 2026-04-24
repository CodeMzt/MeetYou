from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path
from typing import Any

from core.tool_runtime.models import (
    ToolCallResult,
    ToolExecutionCapability,
    ToolErrorCategory,
    ToolSourceType,
    normalize_tool_result,
)
from core.tool_runtime.policy import get_mcp_timeout_seconds

logger = logging.getLogger("meetyou.tools_manager")

_SERIAL_ONLY_TOOLS = {
    "ask_human",
    "save_memory",
    "remember_knowledge",
    "manage_memories",
    "manage_tasks",
    "manage_scheduled_tasks",
    "danxi_create_post",
    "danxi_reply_post",
    "danxi_edit_reply",
    "danxi_delete_reply",
    "danxi_delete_post",
}
_LOCAL_AGENT_READ_TOOLS = {"analyze_workspace", "read_local_documents"}
_LOCAL_AGENT_WRITE_TOOLS = {"write_local_document", "rewrite_local_document"}


class ToolExecutor:
    def __init__(self, registry, permission_policy, risk_classifier, mcp_manager, authorization_gateway=None):
        self._registry = registry
        self._permission_policy = permission_policy
        self._risk_classifier = risk_classifier
        self._mcp_manager = mcp_manager
        self._authorization_gateway = authorization_gateway
        self._execution_observer = None

    def set_execution_observer(self, observer) -> None:
        self._execution_observer = observer

    def get_tool_execution_capability(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
    ) -> ToolExecutionCapability:
        normalized_tool_name = str(tool_name or "").strip()
        action_risk = self._risk_classifier.get_tool_action_risk(normalized_tool_name)
        source = ToolSourceType.UNKNOWN.value
        if self._registry.has_builtin(normalized_tool_name):
            source = ToolSourceType.BUILTIN.value
        elif self._registry.has_mcp(normalized_tool_name):
            source = ToolSourceType.MCP.value
        args = dict(tool_args or {})

        mutates_state = action_risk != "read"
        requires_order = mutates_state
        safe_parallel = action_risk == "read"
        requires_approval = normalized_tool_name in {"exec_sys_cmd"} or normalized_tool_name in _SERIAL_ONLY_TOOLS
        parallel_group = f"{source}:default"
        resource_key = f"{source}:{normalized_tool_name}"
        max_concurrency: int | None = 1 if not safe_parallel else None

        if normalized_tool_name in _SERIAL_ONLY_TOOLS:
            safe_parallel = False
            requires_order = True
            mutates_state = True
            requires_approval = True
            parallel_group = "safety:serial"
            max_concurrency = 1

        if action_risk in {"local_write", "external_write", "destructive"}:
            safe_parallel = False
            requires_order = True
            mutates_state = True
            parallel_group = f"{source}:mutating"
            max_concurrency = 1

        if normalized_tool_name in _LOCAL_AGENT_READ_TOOLS | _LOCAL_AGENT_WRITE_TOOLS:
            path_key = self._extract_local_path_key(normalized_tool_name, args)
            parallel_group = "agent_local_file"
            if path_key:
                resource_key = f"agent_local:{path_key}"
                safe_parallel = normalized_tool_name in _LOCAL_AGENT_READ_TOOLS and action_risk == "read"
                requires_order = not safe_parallel
                max_concurrency = 2 if safe_parallel else 1
            else:
                safe_parallel = False
                requires_order = True
                max_concurrency = 1
                resource_key = f"agent_local:{normalized_tool_name}:unknown_path"

        return ToolExecutionCapability(
            tool_name=normalized_tool_name,
            source=source,
            action_risk=action_risk,
            safe_parallel=safe_parallel and not requires_approval,
            parallel_group=parallel_group,
            resource_key=resource_key,
            mutates_state=mutates_state,
            requires_order=requires_order or requires_approval,
            max_concurrency=max_concurrency,
            requires_approval=requires_approval,
        )

    async def execute(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None,
        *,
        session_id: str = "",
        source=None,
        tool_activity_callback=None,
        route_context: dict[str, Any] | None = None,
    ) -> ToolCallResult:
        action_risk = self._risk_classifier.get_tool_action_risk(tool_name)
        route_context = route_context or {}

        if tool_args is None:
            normalized_tool_args: dict[str, Any] = {}
        elif isinstance(tool_args, dict):
            normalized_tool_args = dict(tool_args)
        else:
            result = ToolCallResult.failure(
                tool_name=tool_name,
                source=ToolSourceType.UNKNOWN,
                action_risk=action_risk,
                code="tool_arguments_invalid",
                category=ToolErrorCategory.VALIDATION,
                message="Tool arguments must be a JSON object.",
                details={
                    "tool_name": tool_name,
                    "provided_type": type(tool_args).__name__,
                },
            )
            self._notify_execution_observer(tool_name, None, result)
            return result

        authorization_decision = None
        if self._authorization_gateway is not None:
            authorization_decision = self._authorization_gateway.decide(
                tool_name,
                normalized_tool_args,
                route_context=route_context,
            )
            if not authorization_decision.allowed:
                result = ToolCallResult.failure(
                    tool_name=tool_name,
                    source=ToolSourceType.UNKNOWN,
                    action_risk=action_risk,
                    code=authorization_decision.reason_code or "tool_not_allowed",
                    category=ToolErrorCategory.PERMISSION,
                    message=authorization_decision.reason_message or "Tool call was denied by the authorization gateway.",
                    details=dict(authorization_decision.details),
                    metadata={"authorization": authorization_decision.to_dict()},
                )
                self._notify_execution_observer(tool_name, normalized_tool_args, result)
                return result

        if self._registry.has_builtin(tool_name):
            result = await self._execute_builtin(
                tool_name,
                normalized_tool_args,
                action_risk=action_risk,
                session_id=session_id,
                source=source,
                tool_activity_callback=tool_activity_callback,
                route_context=route_context,
            )
            self._attach_authorization_metadata(result, authorization_decision)
            self._notify_execution_observer(tool_name, normalized_tool_args, result)
            return result

        if self._registry.has_mcp(tool_name):
            result = await self._execute_mcp(
                tool_name,
                normalized_tool_args,
                action_risk=action_risk,
            )
            self._attach_authorization_metadata(result, authorization_decision)
            self._notify_execution_observer(tool_name, normalized_tool_args, result)
            return result

        result = ToolCallResult.failure(
            tool_name=tool_name,
            source=ToolSourceType.UNKNOWN,
            action_risk=action_risk,
            code="tool_not_found",
            category=ToolErrorCategory.NOT_FOUND,
            message="Requested tool is not registered.",
            details={"tool_name": tool_name},
        )
        self._attach_authorization_metadata(result, authorization_decision)
        self._notify_execution_observer(tool_name, normalized_tool_args, result)
        return result

    @staticmethod
    def _normalize_path_key(path_value: Any) -> str:
        path_text = str(path_value or "").strip()
        if not path_text:
            return ""
        try:
            return str(Path(path_text).expanduser().resolve()).lower()
        except Exception:
            return path_text.lower()

    def _extract_local_path_key(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        if tool_name in {"write_local_document", "rewrite_local_document", "analyze_workspace"}:
            return self._normalize_path_key(tool_args.get("path"))
        if tool_name == "read_local_documents":
            paths = tool_args.get("paths")
            if isinstance(paths, str):
                return self._normalize_path_key(paths)
            if isinstance(paths, list) and len(paths) == 1:
                return self._normalize_path_key(paths[0])
            return ""
        return ""

    async def _execute_builtin(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        action_risk: str,
        session_id: str,
        source,
        tool_activity_callback,
        route_context: dict[str, Any],
    ) -> ToolCallResult:
        func = self._registry.get_builtin(tool_name)
        try:
            call_kwargs = dict(tool_args)
            signature = inspect.signature(func)
            if "session_id" in signature.parameters:
                call_kwargs["session_id"] = session_id
            if "source" in signature.parameters:
                call_kwargs["source"] = source
            if "activity_callback" in signature.parameters:
                call_kwargs["activity_callback"] = tool_activity_callback
            if "route_context" in signature.parameters:
                call_kwargs["route_context"] = route_context

            raw_result = func(**call_kwargs)
            if inspect.isawaitable(raw_result):
                raw_result = await raw_result
            return normalize_tool_result(
                raw_result,
                tool_name=tool_name,
                source=ToolSourceType.BUILTIN,
                action_risk=action_risk,
            )
        except TypeError as exc:
            return ToolCallResult.failure(
                tool_name=tool_name,
                source=ToolSourceType.BUILTIN,
                action_risk=action_risk,
                code="tool_argument_mismatch",
                category=ToolErrorCategory.VALIDATION,
                message="Tool arguments did not match the expected signature.",
                details={
                    "tool_name": tool_name,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )
        except Exception as exc:
            logger.exception("Built-in tool %s failed", tool_name)
            error_code = getattr(exc, "tool_error_code", "tool_builtin_failed")
            error_message = getattr(exc, "tool_error_message", "Built-in tool execution failed.")
            error_details = dict(getattr(exc, "tool_error_details", {}) or {})
            error_retryable = bool(getattr(exc, "tool_error_retryable", False))
            return ToolCallResult.failure(
                tool_name=tool_name,
                source=ToolSourceType.BUILTIN,
                action_risk=action_risk,
                code=error_code,
                category=ToolErrorCategory.EXECUTION,
                message=error_message,
                retryable=error_retryable,
                details={
                    "tool_name": tool_name,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    **error_details,
                },
            )

    async def _execute_mcp(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        action_risk: str,
    ) -> ToolCallResult:
        server_name = self._registry.get_mcp_server(tool_name)
        timeout_seconds = get_mcp_timeout_seconds(tool_name)
        metadata = {
            "server_name": server_name,
            "timeout_seconds": timeout_seconds,
        }
        try:
            result = await asyncio.wait_for(
                self._mcp_manager.call_mcp_tool(tool_name, tool_args),
                timeout=timeout_seconds,
            )
            raw_output = self._extract_mcp_output(result)
            if raw_output is None or raw_output == "":
                return ToolCallResult.failure(
                    tool_name=tool_name,
                    source=ToolSourceType.MCP,
                    action_risk=action_risk,
                    code="mcp_empty_result",
                    category=ToolErrorCategory.DEPENDENCY,
                    message="MCP tool returned no usable content.",
                    details={
                        "tool_name": tool_name,
                        "server_name": server_name,
                    },
                    metadata=metadata,
                )
            return normalize_tool_result(
                raw_output,
                tool_name=tool_name,
                source=ToolSourceType.MCP,
                action_risk=action_risk,
                metadata=metadata,
            )
        except asyncio.TimeoutError:
            return ToolCallResult.failure(
                tool_name=tool_name,
                source=ToolSourceType.MCP,
                action_risk=action_risk,
                code="tool_timeout",
                category=ToolErrorCategory.TIMEOUT,
                message="Tool execution timed out.",
                retryable=True,
                details={
                    "tool_name": tool_name,
                    "server_name": server_name,
                    "timeout_seconds": timeout_seconds,
                },
                metadata=metadata,
            )
        except Exception as exc:
            logger.exception("MCP tool %s failed", tool_name)
            return ToolCallResult.failure(
                tool_name=tool_name,
                source=ToolSourceType.MCP,
                action_risk=action_risk,
                code="mcp_tool_failed",
                category=ToolErrorCategory.DEPENDENCY,
                message="MCP tool execution failed.",
                retryable=True,
                details={
                    "tool_name": tool_name,
                    "server_name": server_name,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
                metadata=metadata,
            )

    @staticmethod
    def _extract_mcp_output(result: Any) -> Any:
        content = getattr(result, "content", None)
        if content:
            text_chunks = [
                item.text
                for item in content
                if getattr(item, "type", "") == "text" and str(getattr(item, "text", "")).strip()
            ]
            if text_chunks:
                return "\n".join(text_chunks)
            normalized_items: list[Any] = []
            for item in content:
                if isinstance(item, dict):
                    normalized_items.append(item)
                elif hasattr(item, "model_dump"):
                    normalized_items.append(item.model_dump(mode="json"))
                else:
                    normalized_items.append(str(item))
            if normalized_items:
                return normalized_items
        structured_content = getattr(result, "structuredContent", None)
        if structured_content is not None:
            return structured_content
        if isinstance(result, (dict, list, str)):
            return result
        return None

    def _notify_execution_observer(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None,
        result: ToolCallResult,
    ) -> None:
        if self._execution_observer is None:
            return
        try:
            self._execution_observer(tool_name, result, tool_args=tool_args)
        except Exception:
            logger.debug("Tool execution observer failed for %s", tool_name, exc_info=True)

    @staticmethod
    def _attach_authorization_metadata(result: ToolCallResult, authorization_decision) -> None:
        if authorization_decision is None:
            return
        metadata = dict(result.metadata or {})
        metadata["authorization"] = authorization_decision.to_dict()
        result.metadata = metadata
