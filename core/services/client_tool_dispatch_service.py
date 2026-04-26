from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from client_tool_protocol import CLIENT_TOOL_ARGUMENTS_PURPOSE, build_tool_call_request
from core.credential_transport import CredentialTransportError, protect_sensitive_arguments


class ClientToolDispatchError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None, retryable: bool = False):
        super().__init__(message)
        self.tool_error_code = code
        self.tool_error_message = message
        self.tool_error_details = dict(details or {})
        self.tool_error_retryable = retryable


@dataclass(slots=True)
class DispatchSelection:
    client: Any
    workspace: Any
    tool_key: str
    tool_id: str
    capability: Any


class ClientToolDispatchService:
    def __init__(
        self,
        *,
        client_service,
        capability_service,
        session_service,
        thread_service,
        workspace_service,
        operation_service,
        operation_call_service,
    ):
        self._client_service = client_service
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

    @staticmethod
    def _tool_list(values) -> set[str]:
        return {str(value or "").strip() for value in values or [] if str(value or "").strip()}

    def _resolve_dispatch_workspace(self, *, session_id: str = "", workspace_id: str = ""):
        normalized_session_id = str(session_id or "").strip()
        if normalized_session_id:
            session_row = self._session_service.get_by_session_id(normalized_session_id)
            if session_row is not None:
                workspace = self._workspace_service.get_by_id(getattr(session_row, "active_workspace_id", None))
                if workspace is not None:
                    return workspace, session_row
                thread_row = self._thread_service.get_by_id(getattr(session_row, "thread_id", None))
                workspace = self._workspace_service.get_by_id(getattr(thread_row, "workspace_id", None)) if thread_row is not None else None
                if workspace is not None:
                    return workspace, session_row
        normalized_workspace_id = str(workspace_id or "").strip()
        if normalized_workspace_id:
            workspace = self._workspace_service.get_by_workspace_id(normalized_workspace_id)
            if workspace is not None:
                return workspace, None
        return None, None

    def _assert_source_can_start(self, *, source_client_id: str, tool_key: str) -> None:
        normalized_source = str(source_client_id or "").strip()
        if not normalized_source:
            return
        source = self._client_service.get_by_client_id(normalized_source)
        if source is None:
            raise ClientToolDispatchError(
                "source_client_not_found",
                f"Unknown source client: {normalized_source}",
                details={"source_client_id": normalized_source},
            )
        available = self._tool_list(getattr(source, "available_tools", []) or [])
        if available and tool_key not in available:
            raise ClientToolDispatchError(
                "tool_not_available_for_source_client",
                f"Tool is not available from source client {normalized_source}: {tool_key}",
                details={"source_client_id": normalized_source, "tool_key": tool_key},
            )

    def _select_target_client(
        self,
        *,
        tool_key: str,
        workspace,
        source_client_id: str = "",
        target_client_id: str = "",
    ):
        normalized_target = str(target_client_id or "").strip()
        if normalized_target:
            candidate = self._client_service.get_by_client_id(normalized_target)
            if candidate is None:
                raise ClientToolDispatchError(
                    "target_client_unavailable",
                    f"Target client is unavailable: {normalized_target}",
                    details={"target_client_id": normalized_target, "tool_key": tool_key},
                    retryable=True,
                )
            if str(getattr(candidate, "status", "") or "").strip().lower() not in {"online", "ready", "active"}:
                raise ClientToolDispatchError(
                    "target_client_unavailable",
                    f"Target client is not online: {normalized_target}",
                    details={"target_client_id": normalized_target, "tool_key": tool_key},
                    retryable=True,
                )
            if tool_key not in self._tool_list(getattr(candidate, "executable_tools", []) or []):
                raise ClientToolDispatchError(
                    "tool_not_executable_by_target_client",
                    f"Target client cannot execute tool {tool_key}: {normalized_target}",
                    details={"target_client_id": normalized_target, "tool_key": tool_key},
                )
            if workspace is not None and not self._client_service.is_bound_to_workspace(client_id=normalized_target, workspace_id=workspace.id):
                raise ClientToolDispatchError(
                    "target_client_workspace_mismatch",
                    f"Target client {normalized_target} is not bound to workspace: {workspace.workspace_id}",
                    details={"target_client_id": normalized_target, "workspace_id": workspace.workspace_id},
                )
            return candidate

        normalized_source = str(source_client_id or "").strip()
        if normalized_source:
            source = self._client_service.get_by_client_id(normalized_source)
            if (
                source is not None
                and str(getattr(source, "status", "") or "").strip().lower() in {"online", "ready", "active"}
                and tool_key in self._tool_list(getattr(source, "executable_tools", []) or [])
                and (workspace is None or self._client_service.is_bound_to_workspace(client_id=normalized_source, workspace_id=workspace.id))
            ):
                return source

        if workspace is not None:
            candidates = self._client_service.list_tool_clients_for_workspace(workspace_id=workspace.id, tool_key=tool_key)
            ordered = sorted(
                candidates,
                key=lambda pair: (
                    0 if str(getattr(pair[0], "client_type", "") or "").lower() == "desktop" else 1,
                    str(getattr(pair[0], "display_name", "") or ""),
                    str(getattr(pair[0], "client_id", "") or ""),
                ),
            )
            for client, _membership in ordered:
                if str(getattr(client, "status", "") or "").strip().lower() in {"online", "ready", "active"}:
                    return client

        raise ClientToolDispatchError(
            "target_client_unavailable",
            f"No available client can execute tool: {tool_key}",
            details={"tool_key": tool_key, "workspace_id": getattr(workspace, "workspace_id", "")},
            retryable=True,
        )

    def resolve_specific_tool(self, *, client_id: str, tool_ref: str, workspace_id: str = ""):
        normalized_client_id = str(client_id or "").strip()
        normalized_ref = str(tool_ref or "").strip().strip(".")
        if not normalized_client_id or not normalized_ref:
            return None
        workspace = self._workspace_service.get_by_workspace_id(str(workspace_id or "").strip()) if workspace_id else None
        candidate_ids = []
        if normalized_ref.startswith("client."):
            candidate_ids.append(normalized_ref)
        else:
            candidate_ids.append(f"client.{normalized_client_id}.{normalized_ref}")
            candidate_ids.append(normalized_ref)
        for tool_id in candidate_ids:
            capability = self._capability_service.get_by_capability_id(tool_id)
            if capability is None:
                continue
            if str(getattr(capability, "provider_ref", "") or "") != normalized_client_id:
                continue
            if workspace is not None and not self._capability_service.is_available_in_workspace(
                capability_id=getattr(capability, "capability_id", ""),
                workspace_id=workspace.id,
            ):
                continue
            return capability
        if workspace is not None:
            return self._capability_service.resolve_tool_reference(
                tool_key=normalized_ref,
                workspace_id=workspace.id,
                target_client_id=normalized_client_id,
            )
        return None

    @staticmethod
    def _tool_requires_confirmation(capability) -> bool:
        risk_level = str(getattr(capability, "risk_level", "") or "").strip().lower()
        return bool(getattr(capability, "requires_confirmation", False)) or risk_level in {
            "write",
            "system",
            "local_write",
            "external_write",
            "destructive",
            "high",
        }

    async def dispatch_directed_tool(
        self,
        *,
        tool_key: str,
        arguments: dict[str, Any],
        source_client_id: str = "",
        target_client_id: str = "",
        session_id: str = "",
        workspace_id: str = "",
        title: str = "",
        operation_type: str = "tool_call",
        timeout_seconds: int = 120,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        normalized_tool_key = str(tool_key or "").strip().strip(".")
        if not normalized_tool_key:
            raise ClientToolDispatchError("tool_key_required", "tool_key is required")
        self._assert_source_can_start(source_client_id=source_client_id, tool_key=normalized_tool_key)
        workspace, session_row = self._resolve_dispatch_workspace(session_id=session_id, workspace_id=workspace_id)
        if workspace is None:
            raise ClientToolDispatchError(
                "missing_workspace_context",
                "Directed tool dispatch requires a valid workspace_id or session_id",
                details={"tool_key": normalized_tool_key, "workspace_id": workspace_id, "session_id": session_id},
            )
        target_client = self._select_target_client(
            tool_key=normalized_tool_key,
            workspace=workspace,
            source_client_id=source_client_id,
            target_client_id=target_client_id,
        )
        capability = self.resolve_specific_tool(
            client_id=target_client.client_id,
            tool_ref=normalized_tool_key,
            workspace_id=workspace.workspace_id,
        )
        if capability is None:
            raise ClientToolDispatchError(
                "tool_not_found",
                f"Tool is unavailable on client {target_client.client_id}: {normalized_tool_key}",
                details={"target_client_id": target_client.client_id, "tool_key": normalized_tool_key},
            )
        if self._tool_requires_confirmation(capability) and not confirmed:
            raise ClientToolDispatchError(
                "tool_confirmation_required",
                "Tool call requires explicit confirmation before dispatch.",
                details={
                    "target_client_id": target_client.client_id,
                    "tool_key": normalized_tool_key,
                    "tool_id": getattr(capability, "capability_id", ""),
                    "risk_level": getattr(capability, "risk_level", ""),
                    "requires_confirmation": bool(getattr(capability, "requires_confirmation", False)),
                },
            )
        if session_row is None:
            raise ClientToolDispatchError(
                "missing_session_context",
                "Tool dispatch requires a valid session_id so operation results can be tracked.",
                details={"tool_key": normalized_tool_key, "workspace_id": workspace.workspace_id, "session_id": session_id},
            )
        thread_row = self._thread_service.get_by_id(session_row.thread_id)
        if thread_row is None:
            raise ClientToolDispatchError("missing_thread_context", "Tool dispatch requires a valid thread context")

        try:
            protected_arguments = protect_sensitive_arguments(arguments, purpose=CLIENT_TOOL_ARGUMENTS_PURPOSE)
        except CredentialTransportError as exc:
            raise ClientToolDispatchError(
                exc.code,
                exc.message,
                details={"tool_id": getattr(capability, "capability_id", "")},
            ) from exc

        tool_id = str(getattr(capability, "capability_id", "") or f"client.{target_client.client_id}.{normalized_tool_key}")
        operation = self._operation_service.create_operation(
            thread_id=getattr(thread_row, "id", None),
            workspace_id=workspace.id,
            operation_type=operation_type,
            execution_target="specific_client",
            title=title or f"Client tool: {normalized_tool_key}",
            target_client_id=target_client.id,
            requested_by_session_id=getattr(session_row, "id", None),
            status="queued",
            metadata={
                "target_client_id": target_client.client_id,
                "tool_key": normalized_tool_key,
                "tool_id": tool_id,
                "arguments": dict(protected_arguments.public_arguments or {}),
                "arguments_encrypted": bool(protected_arguments.encrypted_arguments),
                "confirmed": bool(confirmed),
            },
        )
        call = self._operation_call_service.create_call(
            operation_id=operation.id,
            capability_id=capability.id,
            target_client_id=target_client.id,
            status="queued",
            arguments=dict(protected_arguments.public_arguments or {}),
        )

        if self._transport is None:
            self._operation_call_service.mark_failed(
                call_id=call.call_id,
                error={"code": "client_transport_unavailable", "message": "Client transport is unavailable"},
            )
            raise ClientToolDispatchError("client_transport_unavailable", "Client transport is unavailable")

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        async with self._lock:
            self._pending[call.call_id] = future
        dispatched = await self._transport(
            client_id=target_client.client_id,
            payload=build_tool_call_request(
                client_id=target_client.client_id,
                message_id=f"dispatch-{call.call_id}",
                operation_id=operation.operation_id,
                call_id=call.call_id,
                workspace_id=workspace.workspace_id,
                tool_id=tool_id,
                tool_key=normalized_tool_key,
                arguments=dict(protected_arguments.public_arguments or {}),
                encrypted_arguments=protected_arguments.encrypted_arguments,
                timeout_seconds=timeout_seconds,
                audit_context={
                    "principal_id": "self",
                    "session_id": session_id,
                    "source_client_id": source_client_id,
                    "operation_type": operation_type,
                },
            ),
        )
        if not dispatched:
            async with self._lock:
                self._pending.pop(call.call_id, None)
            self._operation_call_service.mark_failed(
                call_id=call.call_id,
                error={"code": "target_client_unavailable", "message": f"Client is offline: {target_client.client_id}"},
            )
            raise ClientToolDispatchError("target_client_unavailable", f"Client is offline: {target_client.client_id}", retryable=True)
        self._operation_call_service.mark_dispatched(call_id=call.call_id)
        try:
            return await asyncio.wait_for(future, timeout=max(5, timeout_seconds))
        except asyncio.TimeoutError as exc:
            self._operation_call_service.mark_failed(
                call_id=call.call_id,
                error={"code": "client_tool_timeout", "message": f"Client tool call timed out after {timeout_seconds} seconds"},
            )
            raise ClientToolDispatchError(
                "client_tool_timeout",
                f"Client tool call timed out after {timeout_seconds} seconds",
                retryable=True,
            ) from exc
        finally:
            async with self._lock:
                self._pending.pop(call.call_id, None)

    async def dispatch_workspace_tool(self, **kwargs) -> dict[str, Any]:
        return await self.dispatch_directed_tool(**kwargs)

    async def dispatch_specific_client_tool(self, **kwargs) -> dict[str, Any]:
        if "client_id" in kwargs and "target_client_id" not in kwargs:
            kwargs["target_client_id"] = kwargs.pop("client_id")
        return await self.dispatch_directed_tool(**kwargs)

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
                    ClientToolDispatchError(
                        str(error.get("code") or "client_tool_failed"),
                        str(error.get("message") or "Client tool call failed"),
                        details=dict(error or {}),
                        retryable=bool(error.get("retryable", False)),
                    )
                )
