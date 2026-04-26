from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiohttp

from client_tool_sdk.protocol import CLIENT_TOOL_SCHEMA
from client_tool_sdk.runtime import ClientToolRuntimeBase, ToolExecutionError, ToolExecutionOutcome
from desktop_client.config import DesktopClientConfig
from desktop_client.execution import build_tool_handlers
from desktop_client.mcp_runtime import DesktopClientMCPRuntime
from desktop_client.policy import DesktopClientPolicyError
from desktop_client.protocol import (
    build_call_accepted,
    build_call_error,
    build_call_progress,
    build_call_result,
    build_tools_snapshot,
    build_heartbeat,
    build_hello,
)

logger = logging.getLogger("meetyou.desktop_client")

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None


class DesktopClientRuntime(ClientToolRuntimeBase):
    def __init__(self, config: DesktopClientConfig):
        self._mcp_runtime = DesktopClientMCPRuntime(config)
        self._mcp_init_task: asyncio.Task | None = None
        self._mcp_ready = False
        super().__init__(config, handlers=build_tool_handlers(config), logger=logger)

    @property
    def protocol_schema(self) -> str:
        return CLIENT_TOOL_SCHEMA

    @property
    def runtime_label(self) -> str:
        return "Desktop Client"

    def core_access_token_source_hints(self) -> tuple[str, ...]:
        config_path = str(getattr(self.config, "config_file_path", "")).strip()
        hints = [
            "env `MEETYOU_CLIENT_ACCESS_TOKEN`",
            "env `MEETYOU_GATEWAY_ACCESS_TOKEN`",
        ]
        if config_path:
            hints.append(f"config `{config_path}` -> `core_access_token`")
        return tuple(hints)

    async def startup(self) -> None:
        if self._mcp_init_task is None:
            self._mcp_init_task = asyncio.create_task(self._initialize_mcp_runtime())

    async def shutdown(self) -> None:
        if self._mcp_init_task is not None:
            self._mcp_init_task.cancel()
            with __import__("contextlib").suppress(asyncio.CancelledError):
                await self._mcp_init_task
        await self._mcp_runtime.close()

    async def _initialize_mcp_runtime(self) -> None:
        try:
            await self._mcp_runtime.initialize()
            self._mcp_ready = True
            self._tool_revision += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Desktop Client MCP initialization failed: %s", exc)

    @staticmethod
    def _split_result_payload(result: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        payload = dict(result or {})
        attachment_outputs = payload.pop("attachment_outputs", [])
        if not isinstance(attachment_outputs, list):
            attachment_outputs = []
        return payload, [dict(item) for item in attachment_outputs if isinstance(item, dict)]

    async def _request_json(self, session: aiohttp.ClientSession, method: str, url: str, **kwargs) -> dict[str, Any]:
        async with session.request(method, url, **kwargs) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(str(payload))
            if not isinstance(payload, dict):
                raise RuntimeError(f"unexpected response payload: {payload!r}")
            return payload

    async def _upload_attachment_outputs(
        self,
        session: aiohttp.ClientSession,
        *,
        operation_id: str,
        attachment_outputs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        uploaded: list[dict[str, Any]] = []
        base_url = self.config.core_base_url.rstrip("/")
        for item in attachment_outputs:
            local_path = Path(str(item.get("local_path") or "")).expanduser().resolve()
            if not local_path.exists() or not local_path.is_file():
                raise RuntimeError(f"attachment local_path not found: {local_path}")
            content = await asyncio.to_thread(local_path.read_bytes)
            ticket = await self._request_json(
                session,
                "POST",
                f"{base_url}/client/attachments/upload-ticket",
                json={
                    "client_id": self.config.client_id,
                    "owner_type": str(item.get("owner_type") or "operation").strip() or "operation",
                    "owner_id": str(item.get("owner_id") or operation_id).strip() or operation_id,
                    "kind": str(item.get("kind") or "file").strip() or "file",
                    "mime_type": str(item.get("mime_type") or "application/octet-stream").strip() or "application/octet-stream",
                    "file_name": str(item.get("file_name") or local_path.name).strip() or local_path.name,
                    "size_bytes": len(content),
                    "lifecycle_policy": str(item.get("lifecycle_policy") or "normal").strip() or "normal",
                },
            )
            await self._request_json(session, "PUT", str(ticket.get("upload_url") or ""), data=content)
            complete = await self._request_json(
                session,
                "POST",
                f"{base_url}/client/attachments/{ticket['attachment_id']}/complete",
                json={
                    "ticket_id": ticket["ticket_id"],
                },
            )
            local_file_deleted = False
            cleanup_requested = bool(item.get("cleanup_local")) or (
                str(item.get("kind") or "").strip().lower() == "screenshot"
            ) or (
                str(item.get("lifecycle_policy") or "").strip().lower() == "ephemeral"
            )
            if cleanup_requested:
                try:
                    await asyncio.to_thread(local_path.unlink)
                    local_file_deleted = True
                except FileNotFoundError:
                    local_file_deleted = True
            uploaded.append(
                {
                    "attachment_id": complete.get("attachment_id"),
                    "kind": item.get("kind") or "file",
                    "mime_type": complete.get("mime_type"),
                    "file_name": complete.get("file_name"),
                    "size_bytes": complete.get("size_bytes"),
                    "lifecycle_policy": complete.get("lifecycle_policy"),
                    "expires_at": complete.get("expires_at"),
                    "sha256": complete.get("sha256"),
                    "status": complete.get("status"),
                    "local_file_deleted": local_file_deleted,
                }
            )
        return uploaded

    def build_hello_message(self) -> dict[str, Any]:
        return build_hello(self.config)

    def build_tools_snapshot_message(self, *, revision: int) -> dict[str, Any]:
        return build_tools_snapshot(
            self.config,
            revision=revision,
            extra_tools=self._mcp_runtime.tool_definitions() if self._mcp_ready else [],
        )

    def build_heartbeat_message(self, *, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        return build_heartbeat(self.config, metrics=metrics)

    def build_call_accepted_message(self, *, call_id: str, correlation_id: str) -> dict[str, Any]:
        return build_call_accepted(self.config, call_id=call_id, correlation_id=correlation_id)

    def build_call_progress_message(self, *, call_id: str, correlation_id: str, phase: str, detail: str) -> dict[str, Any]:
        return build_call_progress(
            self.config,
            call_id=call_id,
            correlation_id=correlation_id,
            phase=phase,
            detail=detail,
        )

    def build_call_result_message(self, *, call_id: str, correlation_id: str, outcome: ToolExecutionOutcome) -> dict[str, Any]:
        return build_call_result(
            self.config,
            call_id=call_id,
            correlation_id=correlation_id,
            result=outcome.result,
            attachment_outputs=outcome.attachment_outputs,
        )

    def build_call_error_message(
        self,
        *,
        call_id: str,
        correlation_id: str,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> dict[str, Any]:
        return build_call_error(
            self.config,
            call_id=call_id,
            correlation_id=correlation_id,
            code=code,
            message=message,
            retryable=retryable,
        )

    def call_progress_detail(self, tool_key: str) -> str:
        del tool_key
        return "Dispatching tool handler"

    def allows_parallel_tool(self, tool_key: str) -> bool:
        normalized = str(tool_key or "").strip()
        return normalized in {"utility.echo", "workspace.analyze", "file.read"} or any(
            normalized.endswith(suffix)
            for suffix in (".utility.echo", ".workspace.analyze", ".file.read")
        )

    async def execute_tool(
        self,
        *,
        tool_key: str,
        tool_id: str = "",
        arguments: dict[str, Any],
        envelope_payload: dict[str, Any],
        session,
    ) -> ToolExecutionOutcome:
        operation_id = str(envelope_payload.get("operation_id") or "")
        handler = self._handlers.get(tool_key)
        if handler is None and self._mcp_runtime.can_handle(tool_key):
            try:
                result = await self._mcp_runtime.call_tool(tool_key, arguments)
            except Exception as exc:
                raise ToolExecutionError("mcp_call_failed", str(exc)) from exc
            result_payload, attachment_outputs = self._split_result_payload(result)
            uploaded = await self._upload_attachment_outputs(session, operation_id=operation_id, attachment_outputs=attachment_outputs)
            return ToolExecutionOutcome(result=result_payload, attachment_outputs=uploaded)
        if handler is None:
            raise ToolExecutionError("tool_not_implemented", f"Tool not implemented: {tool_key or tool_id}")
        try:
            result = await handler(arguments)
        except DesktopClientPolicyError as exc:
            raise ToolExecutionError(exc.code, exc.message) from exc
        except Exception as exc:
            raise ToolExecutionError("tool_execution_failed", str(exc)) from exc
        result_payload, attachment_outputs = self._split_result_payload(result)
        uploaded = await self._upload_attachment_outputs(session, operation_id=operation_id, attachment_outputs=attachment_outputs)
        return ToolExecutionOutcome(result=result_payload, attachment_outputs=uploaded)

    @staticmethod
    def _collect_metrics() -> dict[str, float | int]:
        if psutil is None:
            return {"active_calls": 0}
        return {
            "cpu_percent": float(psutil.cpu_percent(interval=None)),
            "memory_percent": float(psutil.virtual_memory().percent),
            "active_calls": 0,
            "offline_queue_size": 0,
        }

    def collect_metrics(self) -> dict[str, float | int]:
        metrics = self._collect_metrics()
        metrics["active_calls"] = self._active_call_count
        return metrics
