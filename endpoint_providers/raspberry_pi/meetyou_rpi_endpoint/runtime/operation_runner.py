from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from ..capabilities.base import CapabilityError
from .result_models import (
    OperationEvent,
    OperationFinal,
    OperationRequest,
)


EventEmitter = Callable[[OperationEvent], Awaitable[None]]


class OperationRunner:
    def __init__(
        self,
        registry,
        *,
        default_timeout_seconds: int = 30,
        max_timeout_seconds: int = 300,
    ):
        self.registry = registry
        self.default_timeout_seconds = max(1, int(default_timeout_seconds))
        self.max_timeout_seconds = max(self.default_timeout_seconds, int(max_timeout_seconds))
        self._final_by_operation_id: dict[str, OperationFinal] = {}
        self._seq_by_operation_id: dict[str, int] = {}

    async def run(self, request: OperationRequest, *, emit: EventEmitter | None = None) -> OperationFinal:
        operation_id = str(request.operation_id or "").strip()
        call_id = str(request.call_id or "").strip()
        capability_name = str(request.capability_name or "").strip()
        if not operation_id:
            return await self._fail(
                request,
                code="operation_id_required",
                message="operation_id is required",
                emit=emit,
            )
        cached = self._final_by_operation_id.get(operation_id)
        if cached is not None:
            return cached
        if not call_id:
            return await self._fail(
                request,
                code="call_id_required",
                message="call_id is required",
                emit=emit,
            )
        if not capability_name:
            return await self._fail(
                request,
                code="capability_required",
                message="capability_name is required",
                emit=emit,
            )
        definition = self.registry.get(capability_name)
        if definition is None:
            return await self._fail(
                request,
                code="capability_not_found",
                message=f"Capability is not registered: {capability_name}",
                emit=emit,
            )
        try:
            _validate_input_schema(definition.input_schema, request.arguments)
        except CapabilityError as exc:
            return await self._fail(
                request,
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
                emit=emit,
            )

        await self._emit(
            request,
            status="progress",
            payload={"phase": "running", "detail": f"Executing {capability_name}"},
            emit=emit,
        )
        timeout_seconds = self._timeout_seconds(request.timeout_seconds)
        try:
            result = await asyncio.wait_for(
                self.registry.execute(capability_name, request.arguments),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            return await self._fail(
                request,
                code="operation_timeout",
                message=f"Operation timed out after {timeout_seconds} seconds",
                retryable=True,
                emit=emit,
            )
        except CapabilityError as exc:
            return await self._fail(
                request,
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
                emit=emit,
            )
        except asyncio.CancelledError:
            final = self._final(request, status="cancelled", error={"code": "operation_cancelled", "message": "Operation cancelled"})
            self._final_by_operation_id[operation_id] = final
            await self._emit_final(final, emit=emit)
            raise
        except Exception as exc:
            return await self._fail(
                request,
                code="operation_failed",
                message=str(exc),
                emit=emit,
            )

        final = self._final(request, status="completed", payload=dict(result or {}))
        self._final_by_operation_id[operation_id] = final
        await self._emit_final(final, emit=emit)
        return final

    def get_final(self, operation_id: str) -> OperationFinal | None:
        return self._final_by_operation_id.get(str(operation_id or "").strip())

    async def _fail(
        self,
        request: OperationRequest,
        *,
        code: str,
        message: str,
        retryable: bool = False,
        emit: EventEmitter | None,
    ) -> OperationFinal:
        final = self._final(
            request,
            status="failed",
            error={
                "code": code,
                "message": message,
                "retryable": retryable,
            },
        )
        if request.operation_id:
            self._final_by_operation_id[str(request.operation_id).strip()] = final
        await self._emit_final(final, emit=emit)
        return final

    def _timeout_seconds(self, requested: int | float | None) -> float:
        if requested is None:
            return float(self.default_timeout_seconds)
        try:
            timeout = float(requested)
        except (TypeError, ValueError):
            timeout = float(self.default_timeout_seconds)
        return max(0.001, min(timeout, float(self.max_timeout_seconds)))

    async def _emit(
        self,
        request: OperationRequest,
        *,
        status: str,
        payload: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        emit: EventEmitter | None,
    ) -> OperationEvent:
        seq = self._next_seq(request.operation_id)
        event = OperationEvent(
            operation_id=str(request.operation_id or ""),
            call_id=str(request.call_id or ""),
            capability_name=str(request.capability_name or ""),
            status=status,
            payload=dict(payload or {}),
            error=dict(error) if error else None,
            seq=seq,
        )
        if emit is not None:
            await emit(event)
        return event

    async def _emit_final(self, final: OperationFinal, *, emit: EventEmitter | None) -> None:
        if emit is None:
            return
        await emit(
            OperationEvent(
                operation_id=final.operation_id,
                call_id=final.call_id,
                capability_name=final.capability_name,
                status=final.status,
                payload=dict(final.payload or {}),
                error=dict(final.error) if final.error else None,
                seq=final.seq,
                timestamp=final.timestamp,
            )
        )

    def _final(
        self,
        request: OperationRequest,
        *,
        status: str,
        payload: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> OperationFinal:
        seq = self._next_seq(request.operation_id)
        return OperationFinal(
            operation_id=str(request.operation_id or ""),
            call_id=str(request.call_id or ""),
            capability_name=str(request.capability_name or ""),
            status=status,
            payload=dict(payload or {}),
            error=dict(error) if error else None,
            seq=seq,
        )

    def _next_seq(self, operation_id: str) -> int:
        key = str(operation_id or "").strip() or "_missing"
        self._seq_by_operation_id[key] = self._seq_by_operation_id.get(key, 0) + 1
        return self._seq_by_operation_id[key]


def _validate_input_schema(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise CapabilityError("invalid_arguments", "arguments must be an object")
    if not isinstance(schema, dict) or not schema:
        return
    expected_type = schema.get("type")
    if expected_type == "object":
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key in required:
            if key not in arguments:
                raise CapabilityError("invalid_arguments", f"missing required argument: {key}")
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if schema.get("additionalProperties") is False:
            allowed = set(properties)
            extras = sorted(str(key) for key in arguments if key not in allowed)
            if extras:
                raise CapabilityError("invalid_arguments", f"unexpected argument(s): {', '.join(extras)}")
        for key, rule in properties.items():
            if key not in arguments or not isinstance(rule, dict):
                continue
            _validate_value_type(key, arguments[key], rule.get("type"))


def _validate_value_type(key: str, value: Any, expected_type: Any) -> None:
    if expected_type is None:
        return
    types = expected_type if isinstance(expected_type, list) else [expected_type]
    if any(_matches_type(value, item) for item in types):
        return
    readable = " or ".join(str(item) for item in types)
    raise CapabilityError("invalid_arguments", f"argument {key} must be {readable}")


def _matches_type(value: Any, expected_type: Any) -> bool:
    if expected_type == "null":
        return value is None
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    return True
