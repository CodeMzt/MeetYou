from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from agent_protocol import AGENT_ARGUMENTS_PURPOSE, build_capability_call_request
from core.credential_transport import CredentialTransportError, protect_sensitive_arguments


class AgentDispatchError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None, retryable: bool = False):
        super().__init__(message)
        self.tool_error_code = code
        self.tool_error_message = message
        self.tool_error_details = dict(details or {})
        self.tool_error_retryable = retryable


@dataclass(slots=True)
class DispatchSelection:
    agent: Any
    workspace: Any
    capability_id: str


class AgentDispatchService:
    def __init__(
        self,
        *,
        agent_service,
        capability_service,
        session_service,
        thread_service,
        workspace_service,
        operation_service,
        operation_call_service,
    ):
        self._agent_service = agent_service
        self._capability_service = capability_service
        self._session_service = session_service
        self._thread_service = thread_service
        self._workspace_service = workspace_service
        self._operation_service = operation_service
        self._operation_call_service = operation_call_service
        self._transport: Callable[..., Awaitable[bool]] | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    def set_transport(self, transport: Callable[..., Awaitable[bool]] | None) -> None:
        self._transport = transport

    async def dispatch_agent_capability(
        self,
        *,
        capability_suffix: str,
        arguments: dict[str, Any],
        session_id: str = "",
        title: str = "",
        operation_type: str = "tool_call",
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        selection = self._select_target_agent(capability_suffix=capability_suffix, session_id=session_id)
        capability = self._capability_service.get_by_capability_id(selection.capability_id)
        if capability is None:
            raise AgentDispatchError(
                "capability_not_found",
                f"Capability is unavailable on the selected local agent: {selection.capability_id}",
                details={"capability_id": selection.capability_id},
            )

        session_row = self._session_service.get_by_session_id(session_id) if session_id else None
        thread_row = self._thread_service.get_by_id(session_row.thread_id) if session_row is not None else None
        workspace = selection.workspace
        if session_row is None or thread_row is None or workspace is None:
            raise AgentDispatchError(
                "missing_session_context",
                "Workspace-scoped capability dispatch requires a valid session context",
                details={"session_id": session_id},
            )
        try:
            protected_arguments = protect_sensitive_arguments(
                arguments,
                purpose=AGENT_ARGUMENTS_PURPOSE,
            )
        except CredentialTransportError as exc:
            raise AgentDispatchError(
                exc.code,
                exc.message,
                details={"capability_id": selection.capability_id},
            ) from exc
        operation = self._operation_service.create_operation(
            thread_id=thread_row.id,
            workspace_id=workspace.id,
            operation_type=operation_type,
            execution_target="specific_agent",
            title=title or f"Agent capability: {capability_suffix}",
            target_agent_id=selection.agent.id,
            requested_by_session_id=getattr(session_row, "id", None),
            status="queued",
            metadata={
                "target_agent_key": selection.agent.agent_id,
                "capability_id": selection.capability_id,
                "arguments": dict(protected_arguments.public_arguments or {}),
                "arguments_encrypted": bool(protected_arguments.encrypted_arguments),
            },
        )
        call = self._operation_call_service.create_call(
            operation_id=operation.id,
            capability_id=capability.id,
            target_agent_id=selection.agent.id,
            status="queued",
            arguments=dict(protected_arguments.public_arguments or {}),
        )

        if self._transport is None:
            self._operation_call_service.mark_failed(
                call_id=call.call_id,
                error={"code": "agent_transport_unavailable", "message": "Agent transport is unavailable"},
            )
            raise AgentDispatchError("agent_transport_unavailable", "Agent transport is unavailable")

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        async with self._lock:
            self._pending[call.call_id] = future
        dispatched = await self._transport(
            agent_id=selection.agent.agent_id,
            payload=build_capability_call_request(
                agent_id=selection.agent.agent_id,
                message_id=f"dispatch-{call.call_id}",
                operation_id=operation.operation_id,
                call_id=call.call_id,
                workspace_id=workspace.workspace_id,
                capability_id=selection.capability_id,
                arguments=dict(protected_arguments.public_arguments or {}),
                encrypted_arguments=protected_arguments.encrypted_arguments,
                timeout_seconds=timeout_seconds,
                audit_context={"principal_id": "self", "session_id": session_id, "operation_type": operation_type},
            ),
        )
        if not dispatched:
            async with self._lock:
                self._pending.pop(call.call_id, None)
            self._operation_call_service.mark_failed(
                call_id=call.call_id,
                error={"code": "agent_offline", "message": f"Agent is offline: {selection.agent.agent_id}"},
            )
            raise AgentDispatchError("agent_offline", f"Local agent is offline: {selection.agent.agent_id}")
        self._operation_call_service.mark_dispatched(call_id=call.call_id)
        try:
            return await asyncio.wait_for(future, timeout=max(5, timeout_seconds))
        except asyncio.TimeoutError as exc:
            self._operation_call_service.mark_failed(
                call_id=call.call_id,
                error={"code": "agent_timeout", "message": f"Agent call timed out after {timeout_seconds} seconds"},
            )
            raise AgentDispatchError("agent_timeout", f"Local agent call timed out after {timeout_seconds} seconds", retryable=True) from exc
        finally:
            async with self._lock:
                self._pending.pop(call.call_id, None)

    async def dispatch_local_capability(
        self,
        *,
        capability_suffix: str,
        arguments: dict[str, Any],
        session_id: str = "",
        title: str = "",
        operation_type: str = "tool_call",
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        # Backward-compatible alias while callers migrate to the neutral capability-dispatch name.
        return await self.dispatch_agent_capability(
            capability_suffix=capability_suffix,
            arguments=arguments,
            session_id=session_id,
            title=title,
            operation_type=operation_type,
            timeout_seconds=timeout_seconds,
        )

    async def notify_call_result(self, *, call_id: str, result: dict[str, Any]) -> None:
        async with self._lock:
            future = self._pending.get(call_id)
        if future is not None and not future.done():
            future.set_result(dict(result or {}))

    async def notify_call_error(self, *, call_id: str, error: dict[str, Any]) -> None:
        async with self._lock:
            future = self._pending.get(call_id)
        if future is not None and not future.done():
            future.set_exception(
                AgentDispatchError(
                    str((error or {}).get("code") or "agent_call_failed"),
                    str((error or {}).get("message") or "Local agent call failed"),
                    details=dict(error or {}),
                    retryable=bool((error or {}).get("retryable", False)),
                )
            )

    def _select_target_agent(self, *, capability_suffix: str, session_id: str = "") -> DispatchSelection:
        if not session_id:
            raise AgentDispatchError(
                "missing_session_context",
                "Workspace-scoped capability dispatch requires a valid session context",
                details={"session_id": session_id},
            )

        session_row = self._session_service.get_by_session_id(session_id)
        if session_row is None:
            raise AgentDispatchError(
                "missing_session_context",
                "Workspace-scoped capability dispatch requires a valid session context",
                details={"session_id": session_id},
            )
        thread_row = self._thread_service.get_by_id(session_row.thread_id)
        workspace = self._workspace_service.get_by_id(thread_row.workspace_id) if thread_row is not None else None
        if thread_row is None or workspace is None:
            raise AgentDispatchError(
                "missing_session_context",
                "Workspace-scoped capability dispatch requires a valid session context",
                details={"session_id": session_id},
            )

        candidates: list[tuple[Any, str]] = []
        for agent in self._agent_service.list_agents():
            if str(getattr(agent, "status", "") or "").strip().lower() not in {"online", "ready"}:
                continue
            bindings = self._agent_service.list_workspace_bindings(agent.agent_id)
            if not any(binding.enabled and binding.workspace_id == workspace.id for binding in bindings):
                continue
            capability_id = f"agent.{agent.agent_id}.{capability_suffix}"
            if self._capability_service.get_by_capability_id(capability_id) is None:
                continue
            candidates.append((agent, capability_id))

        candidates.sort(
            key=lambda item: (
                0 if getattr(item[0], "owner_client_id", None) == getattr(session_row, "client_id", None) else 1,
                item[0].agent_id,
            )
        )
        if candidates:
            agent, capability_id = candidates[0]
            return DispatchSelection(
                agent=agent,
                workspace=workspace,
                capability_id=capability_id,
            )

        raise AgentDispatchError(
            "agent_capability_unavailable",
            f"No online agent with capability [{capability_suffix}] is available for workspace: {workspace.workspace_id}",
            details={"workspace_id": workspace.workspace_id, "capability_suffix": capability_suffix},
            retryable=True,
        )
