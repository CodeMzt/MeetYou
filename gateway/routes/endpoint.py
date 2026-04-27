from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from gateway.endpoint_ws import ENDPOINT_WS_SCHEMA


def _frame(frame_type: str, *, payload: dict[str, Any] | None = None, endpoint_id: str = "", correlation_id: str = "") -> dict[str, Any]:
    return {
        "schema": ENDPOINT_WS_SCHEMA,
        "type": frame_type,
        "endpoint_id": str(endpoint_id or "").strip(),
        "correlation_id": str(correlation_id or "").strip(),
        "payload": dict(payload or {}),
    }


async def _send_error(gateway, websocket: WebSocket, *, code: str, message: str, correlation_id: str = "") -> None:
    await gateway._safe_send_json(
        websocket,
        _frame(
            "endpoint.error",
            correlation_id=correlation_id,
            payload={"code": code, "message": message},
        ),
    )


def _public_run_event(row) -> dict[str, Any]:
    return {
        "event_id": getattr(row, "event_id", ""),
        "run_id": str(getattr(row, "run_id", "")),
        "thread_id": str(getattr(row, "thread_id", "") or ""),
        "seq": getattr(row, "seq", 0),
        "type": getattr(row, "type", ""),
        "payload": dict(getattr(row, "payload", {}) or {}),
        "durable": bool(getattr(row, "durable", True)),
        "created_at": getattr(getattr(row, "created_at", None), "isoformat", lambda: "")(),
    }


async def _handle_endpoint_frame(gateway, websocket: WebSocket, frame: dict[str, Any], state: dict[str, Any]) -> None:
    if str(frame.get("schema") or "") != ENDPOINT_WS_SCHEMA:
        await _send_error(gateway, websocket, code="invalid_schema", message="expected meetyou.endpoint.ws.v4")
        return
    frame_type = str(frame.get("type") or "").strip()
    payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
    correlation_id = str(frame.get("message_id") or frame.get("correlation_id") or "").strip()
    domain = gateway._require_core_domain()

    if frame_type == "endpoint.hello":
        provider = payload.get("provider") if isinstance(payload.get("provider"), dict) else {}
        endpoints = payload.get("endpoints") if isinstance(payload.get("endpoints"), list) else []
        if not endpoints:
            await _send_error(gateway, websocket, code="endpoint_required", message="endpoint.hello requires at least one endpoint", correlation_id=correlation_id)
            return
        created = []
        primary = None
        for item in endpoints:
            if not isinstance(item, dict):
                continue
            endpoint_id = str(item.get("endpoint_id") or "").strip()
            if not endpoint_id:
                continue
            row = domain.services.endpoint.ensure_endpoint(
                endpoint_id=endpoint_id,
                endpoint_type=str(item.get("endpoint_type") or "endpoint"),
                provider_type=str(provider.get("provider_type") or item.get("provider_type") or "external"),
                transport_type=str(item.get("transport_type") or "websocket"),
                workspace_scope=list(item.get("workspace_ids") or item.get("workspace_scope") or []),
                status="online",
                labels=list(item.get("roles") or item.get("labels") or []),
                metadata={
                    "provider": provider,
                    "roles": list(item.get("roles") or []),
                },
            )
            if primary is None:
                primary = row
            created.append(endpoint_id)
        if primary is None:
            await _send_error(gateway, websocket, code="endpoint_required", message="endpoint.hello did not include a valid endpoint", correlation_id=correlation_id)
            return
        connection_id = str(frame.get("connection_id") or payload.get("connection_id") or f"conn_{uuid4().hex}")
        state["endpoint_id"] = primary.endpoint_id
        state["connection_id"] = connection_id
        connection = domain.services.endpoint_connection.upsert_connection(
            endpoint_row_id=primary.id,
            connection_id=connection_id,
            protocol_version=ENDPOINT_WS_SCHEMA,
            remote_addr=str(getattr(websocket.client, "host", "") or ""),
            metadata={"provider": provider, "endpoints": created},
        )
        await gateway.endpoint_ws_manager.bind_endpoint(
            websocket,
            endpoint_id=primary.endpoint_id,
            connection_id=connection.connection_id,
            provider=provider,
            metadata={"endpoint_ids": created},
        )
        await gateway._safe_send_json(
            websocket,
            _frame(
                "endpoint.hello.ack",
                endpoint_id=primary.endpoint_id,
                correlation_id=correlation_id,
                payload={
                    "accepted": True,
                    "protocol": ENDPOINT_WS_SCHEMA,
                    "connection_id": connection.connection_id,
                    "requires_capabilities_snapshot": True,
                    "heartbeat_interval_seconds": 20,
                    "registered_endpoints": created,
                },
            ),
        )
        return

    if frame_type == "endpoint.capabilities.snapshot":
        endpoint_id = str(payload.get("endpoint_id") or frame.get("endpoint_id") or state.get("endpoint_id") or "").strip()
        endpoint = domain.services.endpoint.get_by_endpoint_id(endpoint_id)
        if endpoint is None:
            await _send_error(gateway, websocket, code="endpoint_not_found", message=f"unknown endpoint: {endpoint_id}", correlation_id=correlation_id)
            return
        capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), list) else []
        count = domain.services.endpoint_capability.replace_snapshot(
            endpoint_row_id=endpoint.id,
            endpoint_public_id=endpoint.endpoint_id,
            capabilities=capabilities,
        )
        await gateway._safe_send_json(
            websocket,
            _frame("endpoint.ready", endpoint_id=endpoint.endpoint_id, correlation_id=correlation_id, payload={"registered_capability_count": count}),
        )
        return

    if frame_type == "endpoint.ready":
        endpoint_id = str(frame.get("endpoint_id") or payload.get("endpoint_id") or state.get("endpoint_id") or "").strip()
        if endpoint_id:
            domain.services.endpoint.set_status(endpoint_id=endpoint_id, status="ready")
        return

    if frame_type == "endpoint.heartbeat":
        connection_id = str(frame.get("connection_id") or payload.get("connection_id") or state.get("connection_id") or "").strip()
        if connection_id:
            domain.services.endpoint_connection.heartbeat(connection_id=connection_id, metadata={"heartbeat": payload})
        return

    if frame_type == "subscription.start":
        target_type = str(payload.get("target_type") or "").strip()
        target_id = str(payload.get("target_id") or "").strip()
        subscription_id = str(payload.get("subscription_id") or "").strip()
        await gateway.endpoint_ws_manager.subscribe(
            websocket,
            target_type=target_type,
            target_id=target_id,
            subscription_id=subscription_id,
        )
        await gateway._safe_send_json(
            websocket,
            _frame("subscription.ack", correlation_id=correlation_id, payload={"subscription_id": subscription_id, "target_type": target_type, "target_id": target_id}),
        )
        replay = payload.get("replay", True)
        if isinstance(replay, str):
            replay = replay.strip().lower() not in {"0", "false", "no", "off"}
        if target_type == "thread" and bool(replay):
            thread = domain.services.thread.get_by_thread_id(target_id)
            if thread is not None:
                for event in domain.services.run_event.list_for_thread_after(
                    thread_id=thread.id,
                    after_seq=int(payload.get("last_seen_event_seq") or 0),
                    durable_only=True,
                ):
                    await gateway._safe_send_json(
                        websocket,
                        _frame("delivery.run_event", payload=_public_run_event(event)),
                    )
        return

    if frame_type == "tool.call.result":
        call_id = str(payload.get("call_id") or "").strip()
        if call_id:
            domain.services.operation_call.mark_succeeded(call_id=call_id, result=payload.get("result") if isinstance(payload.get("result"), dict) else {})
            await domain.services.tool_router.notify_call_result(
                call_id,
                payload.get("result") if isinstance(payload.get("result"), dict) else {},
            )
        return

    if frame_type == "tool.call.accepted":
        call_id = str(payload.get("call_id") or "").strip()
        if call_id:
            domain.services.operation_call.mark_accepted(call_id=call_id)
        return

    if frame_type == "tool.call.progress":
        call_id = str(payload.get("call_id") or "").strip()
        if call_id:
            domain.services.operation_call.mark_progress(
                call_id=call_id,
                detail=str(payload.get("detail") or ""),
                metadata={"phase": str(payload.get("phase") or "running")},
            )
        return

    if frame_type == "tool.call.error":
        call_id = str(payload.get("call_id") or "").strip()
        if call_id:
            domain.services.operation_call.mark_failed(call_id=call_id, error=payload.get("error") if isinstance(payload.get("error"), dict) else {})
            await domain.services.tool_router.notify_call_error(
                call_id,
                payload.get("error") if isinstance(payload.get("error"), dict) else {},
            )
        return

    if frame_type == "endpoint.goodbye":
        connection_id = str(state.get("connection_id") or "").strip()
        if connection_id:
            domain.services.endpoint_connection.mark_disconnected(connection_id=connection_id)
        await websocket.close(code=1000)
        return

    await _send_error(gateway, websocket, code="unsupported_frame", message=f"unsupported endpoint frame: {frame_type}", correlation_id=correlation_id)


def build_endpoint_router(gateway) -> APIRouter:
    router = APIRouter(prefix="/endpoint", tags=["endpoint"])

    @router.websocket("/ws")
    async def endpoint_websocket(websocket: WebSocket):
        if not await gateway._authorize_websocket(websocket):
            return
        await websocket.accept()
        await gateway.endpoint_ws_manager.connect(websocket)
        state: dict[str, Any] = {}
        try:
            while True:
                frame = await websocket.receive_json()
                if not isinstance(frame, dict):
                    await _send_error(gateway, websocket, code="invalid_payload", message="endpoint frame must be an object")
                    continue
                await _handle_endpoint_frame(gateway, websocket, frame, state)
        except WebSocketDisconnect:
            pass
        finally:
            metadata = await gateway.endpoint_ws_manager.disconnect(websocket)
            connection_id = str(state.get("connection_id") or metadata.get("connection_id") or "").strip()
            domain = getattr(getattr(gateway, "_dependencies", None), "core_domain", None)
            if domain is not None and connection_id:
                domain.services.endpoint_connection.mark_disconnected(connection_id=connection_id)

    return router
