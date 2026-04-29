from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import uuid4

from endpoint_tool_sdk.protocol import ENDPOINT_TOOL_ARGUMENTS_PURPOSE
from core.credential_transport import CredentialTransportError, protect_sensitive_arguments


class ToolRouterError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.retryable = retryable


@dataclass(slots=True)
class ExecutionTarget:
    target_id: str
    target_type: str
    endpoint: Any | None = None
    endpoint_capability: Any | None = None
    offline_policy: str = "fail_fast"


class CoreToolExecutor:
    def __init__(self):
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}

    def register(self, tool_key: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        self._handlers[str(tool_key or "").strip()] = handler

    def has_tool(self, tool_key: str) -> bool:
        return str(tool_key or "").strip() in self._handlers

    async def execute(self, *, tool_key: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get(str(tool_key or "").strip())
        if handler is None:
            raise ToolRouterError("core_tool_not_found", f"Core tool is not registered: {tool_key}")
        result = handler(dict(arguments or {}))
        if asyncio.iscoroutine(result):
            result = await result
        if getattr(result, "ok", None) is False:
            error = getattr(result, "error", None)
            raise ToolRouterError(
                str(getattr(error, "code", "") or "core_tool_failed"),
                str(getattr(error, "message", "") or f"Core tool failed: {tool_key}"),
                details=dict(getattr(error, "details", {}) or {}),
                retryable=bool(getattr(error, "retryable", False)),
            )
        if getattr(result, "ok", None) is True and hasattr(result, "content"):
            content = getattr(result, "content", None)
            data = getattr(content, "data", None)
            if isinstance(data, dict):
                return dict(data)
            if data is not None:
                return {"result": data}
            text = str(getattr(content, "text", "") or "").strip()
            return {"content": text} if text else {}
        return dict(result or {})


class ToolRouterService:
    def __init__(
        self,
        *,
        actor_service,
        workspace_service,
        endpoint_service,
        endpoint_capability_service,
        session_service,
        thread_service,
        operation_service,
        operation_call_service,
    ):
        self._actor_service = actor_service
        self._workspace_service = workspace_service
        self._endpoint_service = endpoint_service
        self._endpoint_capability_service = endpoint_capability_service
        self._session_service = session_service
        self._thread_service = thread_service
        self._operation_service = operation_service
        self._operation_call_service = operation_call_service
        self._core_executor = CoreToolExecutor()
        self._endpoint_transport: Callable[..., Awaitable[bool]] | None = None
        self._external_transport: Callable[..., Awaitable[dict[str, Any]]] | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    def set_endpoint_transport(self, transport: Callable[..., Awaitable[bool]] | None) -> None:
        self._endpoint_transport = transport

    def set_external_transport(self, transport: Callable[..., Awaitable[dict[str, Any]]] | None) -> None:
        self._external_transport = transport

    def register_core_tool(self, tool_key: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        self._core_executor.register(tool_key, handler)

    async def dispatch_workspace_tool(self, **kwargs) -> dict[str, Any]:
        return await self.dispatch_tool_call(**kwargs)

    async def dispatch_tool_call(self, **kwargs) -> dict[str, Any]:
        session_id = str(kwargs.get("session_id") or "").strip()
        workspace_id = str(kwargs.get("workspace_id") or "").strip()
        thread_row_id = kwargs.get("thread_row_id")
        if session_id:
            session_row = self._session_service.get_by_session_id(session_id)
            if session_row is not None:
                thread_row_id = getattr(session_row, "thread_id", None)
                workspace = self._workspace_service.get_by_id(getattr(session_row, "active_workspace_id", None))
                if workspace is None:
                    thread = self._thread_service.get_by_id(thread_row_id)
                    workspace = self._workspace_service.get_by_id(getattr(thread, "workspace_id", None)) if thread is not None else None
                workspace_id = getattr(workspace, "workspace_id", "") or workspace_id
        if not workspace_id:
            raise ToolRouterError("workspace_required", "ToolRouter dispatch requires workspace_id or session_id")
        endpoint_id = str(
            kwargs.get("endpoint_id")
            or kwargs.get("target_endpoint_id")
            or kwargs.get("target_id")
            or ""
        ).strip()
        return await self.route_tool_call(
            tool_key=str(kwargs.get("tool_key") or "").strip(),
            arguments=kwargs.get("arguments") if isinstance(kwargs.get("arguments"), dict) else {},
            workspace_id=workspace_id,
            thread_row_id=thread_row_id,
            requested_by_actor_id=kwargs.get("requested_by_actor_id"),
            requested_by_run_id=kwargs.get("requested_by_run_id"),
            endpoint_id=endpoint_id,
            title=str(kwargs.get("title") or ""),
            timeout_seconds=int(kwargs.get("timeout_seconds") or 120),
            confirmed=bool(kwargs.get("confirmed", False)),
            offline_policy=str(kwargs.get("offline_policy") or "fail_fast"),
            return_operation=bool(kwargs.get("return_operation", False)),
        )

    def resolve_execution_target(
        self,
        *,
        tool_key: str,
        workspace_id: str = "",
        execution_target: dict[str, Any] | None = None,
        endpoint_id: str = "",
        offline_policy: str = "fail_fast",
    ) -> ExecutionTarget:
        normalized_tool_key = str(tool_key or "").strip()
        requested = dict(execution_target or {})
        requested_endpoint_id = str(endpoint_id or requested.get("endpoint_id") or requested.get("execution_target_id") or "").strip()
        if requested_endpoint_id:
            endpoint = self._endpoint_service.get_by_endpoint_id(requested_endpoint_id)
            if endpoint is None:
                raise ToolRouterError("execution_target_not_found", f"Execution target not found: {requested_endpoint_id}", retryable=True)
            capability = None
            for candidate in self._endpoint_capability_service.list_for_endpoint(endpoint_row_id=endpoint.id):
                if str(getattr(candidate, "tool_key", "") or "") == normalized_tool_key and bool(getattr(candidate, "enabled", True)):
                    capability = candidate
                    break
            if requested_endpoint_id == "core.local":
                return ExecutionTarget("core.local", "core", endpoint=endpoint, endpoint_capability=capability)
            if capability is None:
                raise ToolRouterError(
                    "endpoint_capability_not_found",
                    f"Endpoint cannot execute tool: {requested_endpoint_id} -> {normalized_tool_key}",
                    details={"endpoint_id": requested_endpoint_id, "tool_key": normalized_tool_key},
                )
            provider_type = str(getattr(endpoint, "provider_type", "") or "").strip()
            target_type = "external" if provider_type in {"external", "webhook", "feishu", "wechatbot", "email"} else "endpoint"
            return ExecutionTarget(requested_endpoint_id, target_type, endpoint=endpoint, endpoint_capability=capability, offline_policy=offline_policy)

        if self._core_executor.has_tool(normalized_tool_key) or normalized_tool_key.startswith("core."):
            endpoint = self._endpoint_service.get_by_endpoint_id("core.local")
            return ExecutionTarget("core.local", "core", endpoint=endpoint)

        workspace = self._workspace_service.get_by_workspace_id(workspace_id) if workspace_id else None
        capabilities = self._endpoint_capability_service.list_enabled_for_tool(tool_key=normalized_tool_key)
        for capability in capabilities:
            endpoint = self._endpoint_service.get_by_id(getattr(capability, "endpoint_id", None))
            if endpoint is None:
                continue
            if workspace is not None:
                scope = list(getattr(endpoint, "workspace_scope", []) or [])
                if scope and workspace.workspace_id not in scope:
                    continue
            status = str(getattr(endpoint, "status", "") or "").strip().lower()
            if status in {"ready", "online", "active"}:
                return ExecutionTarget(endpoint.endpoint_id, "endpoint", endpoint=endpoint, endpoint_capability=capability, offline_policy=offline_policy)
        if offline_policy in {"queue_until_online", "store_in_outbox"} and capabilities:
            capability = capabilities[0]
            endpoint = self._endpoint_service.get_by_id(getattr(capability, "endpoint_id", None))
            if endpoint is not None:
                return ExecutionTarget(endpoint.endpoint_id, "endpoint", endpoint=endpoint, endpoint_capability=capability, offline_policy=offline_policy)
        raise ToolRouterError("execution_target_unavailable", f"No execution target can run tool: {normalized_tool_key}", retryable=True)

    async def route_tool_call(
        self,
        *,
        tool_key: str,
        arguments: dict[str, Any],
        workspace_id: str,
        thread_row_id=None,
        requested_by_actor_id=None,
        requested_by_run_id=None,
        execution_target: dict[str, Any] | None = None,
        endpoint_id: str = "",
        title: str = "",
        timeout_seconds: int = 120,
        confirmed: bool = False,
        offline_policy: str = "fail_fast",
        return_operation: bool = False,
    ) -> dict[str, Any]:
        target = self.resolve_execution_target(
            tool_key=tool_key,
            workspace_id=workspace_id,
            execution_target=execution_target,
            endpoint_id=endpoint_id,
            offline_policy=offline_policy,
        )
        if target.target_type == "core":
            return await self._core_executor.execute(tool_key=tool_key, arguments=arguments)
        return await self._dispatch_target(
            target=target,
            tool_key=tool_key,
            arguments=arguments,
            workspace_id=workspace_id,
            thread_row_id=thread_row_id,
            requested_by_actor_id=requested_by_actor_id,
            requested_by_run_id=requested_by_run_id,
            title=title,
            timeout_seconds=timeout_seconds,
            confirmed=confirmed,
            return_operation=return_operation,
        )

    async def _dispatch_target(
        self,
        *,
        target: ExecutionTarget,
        tool_key: str,
        arguments: dict[str, Any],
        workspace_id: str,
        thread_row_id=None,
        requested_by_actor_id=None,
        requested_by_run_id=None,
        title: str = "",
        timeout_seconds: int = 120,
        confirmed: bool = False,
        return_operation: bool = False,
    ) -> dict[str, Any]:
        workspace = self._workspace_service.get_by_workspace_id(workspace_id)
        if workspace is None:
            raise ToolRouterError("workspace_not_found", f"Workspace not found: {workspace_id}")
        capability = target.endpoint_capability
        if capability is not None and bool(getattr(capability, "requires_confirmation", False)) and not confirmed:
            raise ToolRouterError(
                "tool_confirmation_required",
                "Tool call requires explicit confirmation before dispatch.",
                details={
                    "endpoint_id": target.target_id,
                    "tool_key": tool_key,
                    "risk_level": getattr(capability, "risk_level", ""),
                },
            )
        try:
            protected_arguments = protect_sensitive_arguments(arguments, purpose=ENDPOINT_TOOL_ARGUMENTS_PURPOSE)
        except CredentialTransportError as exc:
            raise ToolRouterError(exc.code, exc.message) from exc
        operation = self._operation_service.create_operation(
            thread_id=thread_row_id,
            workspace_id=workspace.id,
            operation_type="tool_call",
            execution_target=target.target_id,
            execution_target_type=target.target_type,
            execution_target_id=target.target_id,
            target_endpoint_id=getattr(target.endpoint, "id", None),
            requested_by_actor_id=requested_by_actor_id,
            requested_by_run_id=requested_by_run_id,
            title=title or f"Tool: {tool_key}",
            status="queued",
            metadata={
                "tool_key": tool_key,
                "execution_target_id": target.target_id,
                "arguments": dict(protected_arguments.public_arguments or {}),
                "arguments_encrypted": bool(protected_arguments.encrypted_arguments),
            },
        )
        call = self._operation_call_service.create_call(
            operation_id=operation.id,
            endpoint_capability_id=getattr(capability, "id", None),
            target_endpoint_id=getattr(target.endpoint, "id", None),
            execution_target_id=target.target_id,
            status="queued",
            arguments=dict(protected_arguments.public_arguments or {}),
        )
        frame = {
            "schema": "meetyou.endpoint.ws.v4",
            "type": "tool.call.request",
            "endpoint_id": target.target_id,
            "message_id": f"dispatch-{call.call_id}",
            "payload": {
                "operation_id": operation.operation_id,
                "call_id": call.call_id,
                "workspace_id": workspace.workspace_id,
                "tool_key": str(tool_key or "").strip(),
                "capability_id": str(getattr(capability, "capability_id", "") or ""),
                "arguments": dict(protected_arguments.public_arguments or {}),
                "encrypted_arguments": protected_arguments.encrypted_arguments,
                "timeout_seconds": timeout_seconds,
                "audit_context": {
                    "requested_by_actor_id": str(requested_by_actor_id or ""),
                    "requested_by_run_id": str(requested_by_run_id or ""),
                    "execution_target_id": target.target_id,
                },
            },
        }
        if target.target_type == "external":
            if self._external_transport is None:
                raise ToolRouterError("external_executor_unavailable", "External executor is unavailable", retryable=True)
            result = dict(await self._external_transport(endpoint_id=target.target_id, frame=frame) or {})
            if return_operation:
                return {
                    "status": "succeeded",
                    "operation_id": operation.operation_id,
                    "call_id": call.call_id,
                    "execution_target_id": target.target_id,
                    "result": result,
                }
            return result
        if self._endpoint_transport is None:
            self._operation_call_service.mark_failed(call_id=call.call_id, error={"code": "endpoint_transport_unavailable"})
            raise ToolRouterError("endpoint_transport_unavailable", "Endpoint transport is unavailable", retryable=True)

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        async with self._lock:
            self._pending[call.call_id] = future
        dispatched = await self._endpoint_transport(endpoint_id=target.target_id, payload=frame)
        if not dispatched:
            async with self._lock:
                self._pending.pop(call.call_id, None)
            if target.offline_policy in {"queue_until_online", "store_in_outbox"}:
                self._operation_call_service.mark_failed(call_id=call.call_id, error={"code": "waiting_for_endpoint"})
                return {"status": "waiting_for_endpoint", "operation_id": operation.operation_id, "call_id": call.call_id}
            self._operation_call_service.mark_failed(call_id=call.call_id, error={"code": "target_endpoint_unavailable"})
            raise ToolRouterError("target_endpoint_unavailable", f"Endpoint is unavailable: {target.target_id}", retryable=True)
        self._operation_call_service.mark_dispatched(call_id=call.call_id)
        try:
            result = await asyncio.wait_for(future, timeout=max(5, timeout_seconds))
            if return_operation:
                return {
                    "status": "succeeded",
                    "operation_id": operation.operation_id,
                    "call_id": call.call_id,
                    "execution_target_id": target.target_id,
                    "result": dict(result or {}),
                }
            return result
        except asyncio.TimeoutError as exc:
            self._operation_call_service.mark_failed(call_id=call.call_id, error={"code": "endpoint_tool_timeout"})
            raise ToolRouterError("endpoint_tool_timeout", f"Endpoint tool call timed out after {timeout_seconds} seconds", retryable=True) from exc
        finally:
            async with self._lock:
                self._pending.pop(call.call_id, None)

    async def notify_call_result(self, call_id: str, result: dict[str, Any]) -> None:
        self._operation_call_service.mark_succeeded(call_id=call_id, result=result)
        async with self._lock:
            future = self._pending.get(call_id)
            if future is not None and not future.done():
                future.set_result(dict(result or {}))

    async def notify_call_error(self, call_id: str, error: dict[str, Any]) -> None:
        self._operation_call_service.mark_failed(call_id=call_id, error=error)
        async with self._lock:
            future = self._pending.get(call_id)
            if future is not None and not future.done():
                future.set_exception(
                    ToolRouterError(
                        str(error.get("code") or "endpoint_tool_failed"),
                        str(error.get("message") or "Endpoint tool call failed"),
                        details=dict(error or {}),
                        retryable=bool(error.get("retryable", False)),
                    )
                )
