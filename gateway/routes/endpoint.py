from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.db.base import utcnow
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


def _public_address(row) -> dict[str, Any]:
    metadata = dict(getattr(row, "meta", {}) or {})
    return {
        "address_id": str(getattr(row, "address_id", "") or ""),
        "provider_type": str(getattr(row, "provider_type", "") or ""),
        "address_type": str(getattr(row, "address_type", "") or ""),
        "external_ref": str(getattr(row, "external_ref", "") or ""),
        "display_name": str(getattr(row, "display_name", "") or ""),
        "workspace_ids": list(getattr(row, "workspace_scope", []) or []),
        "status": str(getattr(row, "status", "") or "unknown"),
        "capabilities": list(getattr(row, "capabilities", []) or []),
        "supports_markdown": _bool_value(metadata.get("supports_markdown"), default=True),
        "metadata": metadata,
        "last_seen_at": getattr(getattr(row, "last_seen_at", None), "isoformat", lambda: "")(),
        "last_verified_at": getattr(getattr(row, "last_verified_at", None), "isoformat", lambda: "")(),
    }


def _bool_value(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _address_payload_item(item: dict[str, Any], *, endpoint_id: str, provider_type: str) -> dict[str, Any]:
    external_ref = str(item.get("external_ref") or item.get("chat_id") or item.get("room_id") or item.get("id") or "").strip()
    address_type = str(item.get("address_type") or item.get("chat_type") or "direct").strip().lower() or "direct"
    if address_type in {"private", "p2p", "person"}:
        address_type = "direct"
    if address_type in {"group_chat"}:
        address_type = "group"
    metadata = dict(item.get("metadata") or {})
    default_markdown = str(provider_type or "").strip().lower() not in {"feishu", "wechat", "meetwechat", "wechatbot"}
    supports_markdown = _bool_value(
        item.get("supports_markdown", metadata.get("supports_markdown")),
        default=default_markdown,
    )
    metadata["supports_markdown"] = supports_markdown
    return {
        "address_id": str(item.get("address_id") or f"addr.{provider_type}.{address_type}.{external_ref}").strip(),
        "endpoint_id": str(item.get("endpoint_id") or endpoint_id).strip(),
        "provider_type": str(item.get("provider_type") or provider_type).strip(),
        "address_type": address_type,
        "external_ref": external_ref,
        "display_name": str(item.get("display_name") or item.get("name") or external_ref).strip(),
        "workspace_scope": list(item.get("workspace_ids") or item.get("workspace_scope") or []),
        "status": str(item.get("status") or "sendable").strip() or "sendable",
        "capabilities": list(item.get("capabilities") or ["receive_message"]),
        "metadata": metadata,
    }


def _operation_update_payload(domain, call_row, *, phase: str = "", detail: str = "", result: dict | None = None, error: dict | None = None) -> tuple[str, str, dict[str, Any]]:
    if call_row is None:
        return "", "", {}
    operation_service = getattr(domain.services, "operation", None)
    get_operation = getattr(operation_service, "get_by_id", None)
    operation = get_operation(getattr(call_row, "operation_id", None)) if callable(get_operation) else None
    if operation is None:
        return "", "", {}
    thread_service = getattr(domain.services, "thread", None)
    get_thread = getattr(thread_service, "get_by_id", None)
    thread = get_thread(getattr(operation, "thread_id", None)) if callable(get_thread) else None
    metadata = dict(getattr(operation, "meta", {}) or {})
    payload = {
        "thread_id": str(getattr(thread, "thread_id", "") or ""),
        "workspace_id": str(metadata.get("workspace_id") or ""),
        "operation_id": str(getattr(operation, "operation_id", "") or ""),
        "title": str(getattr(operation, "title", "") or ""),
        "operation_type": str(getattr(operation, "operation_type", "") or ""),
        "execution_target": str(getattr(operation, "execution_target", "") or ""),
        "execution_target_id": str(getattr(operation, "execution_target_id", "") or metadata.get("execution_target_id") or ""),
        "target_endpoint_id": str(
            metadata.get("target_endpoint_id")
            or metadata.get("execution_target_id")
            or getattr(operation, "execution_target_id", "")
            or ""
        ),
        "tool_key": str(metadata.get("preferred_tool_key") or metadata.get("tool_key") or ""),
        "tool_id": str(metadata.get("tool_id") or metadata.get("capability_id") or ""),
        "call_id": str(getattr(call_row, "call_id", "") or ""),
        "status": str(getattr(operation, "status", "") or getattr(call_row, "status", "") or ""),
        "phase": str(phase or ""),
        "detail": str(detail or ""),
        "routing_reason": str(metadata.get("routing_reason") or ""),
        "approval_id": str(metadata.get("approval_id") or ""),
        "approval_status": str(metadata.get("approval_status") or ""),
        "approval_required": bool(metadata.get("approval_required", False)),
    }
    if isinstance(result, dict):
        payload["result"] = dict(result)
    if isinstance(error, dict):
        payload["error"] = dict(error)
    return payload["thread_id"], payload["operation_id"], payload


async def _publish_operation_update(
    gateway,
    domain,
    call_row,
    *,
    phase: str = "",
    detail: str = "",
    result: dict | None = None,
    error: dict | None = None,
) -> None:
    thread_id, operation_id, payload = _operation_update_payload(
        domain,
        call_row,
        phase=phase,
        detail=detail,
        result=result,
        error=error,
    )
    if not operation_id:
        return
    publisher = getattr(gateway, "publish_endpoint_operation_update", None)
    if callable(publisher):
        await publisher(thread_id=thread_id, operation_id=operation_id, payload=payload)


async def _drain_endpoint_outbox(domain, endpoint) -> None:
    drainer = getattr(getattr(domain.services, "delivery", None), "drain_endpoint_outbox", None)
    if callable(drainer) and endpoint is not None:
        await drainer(target_endpoint=endpoint)


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
        provider = dict(provider)
        provider_supports_markdown = _bool_value(
            provider.get("supports_markdown", payload.get("supports_markdown")),
            default=True,
        )
        provider["supports_markdown"] = provider_supports_markdown
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
            endpoint_supports_markdown = _bool_value(
                item.get("supports_markdown"),
                default=provider_supports_markdown,
            )
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
                    "supports_markdown": endpoint_supports_markdown,
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
        await _drain_endpoint_outbox(domain, endpoint)
        return

    if frame_type in {"endpoint.addresses.snapshot", "endpoint.address.upsert"}:
        endpoint_id = str(payload.get("endpoint_id") or frame.get("endpoint_id") or state.get("endpoint_id") or "").strip()
        endpoint = domain.services.endpoint.get_by_endpoint_id(endpoint_id)
        if endpoint is None:
            await _send_error(gateway, websocket, code="endpoint_not_found", message=f"unknown endpoint: {endpoint_id}", correlation_id=correlation_id)
            return
        provider_type = str(getattr(endpoint, "provider_type", "") or "").strip()
        raw_addresses = payload.get("addresses") if frame_type == "endpoint.addresses.snapshot" else [payload.get("address") or payload]
        if not isinstance(raw_addresses, list):
            raw_addresses = []
        saved = []
        for item in raw_addresses:
            if not isinstance(item, dict):
                continue
            normalized = _address_payload_item(item, endpoint_id=endpoint.endpoint_id, provider_type=provider_type)
            if not normalized["external_ref"]:
                continue
            row = domain.services.endpoint_address.upsert_address(
                endpoint_row_id=endpoint.id,
                provider_type=normalized["provider_type"],
                address_type=normalized["address_type"],
                external_ref=normalized["external_ref"],
                address_id=normalized["address_id"],
                display_name=normalized["display_name"],
                workspace_scope=normalized["workspace_scope"],
                status=normalized["status"],
                capabilities=normalized["capabilities"],
                last_seen_at=utcnow(),
                last_verified_at=utcnow() if normalized["status"] == "sendable" else None,
                metadata=normalized["metadata"],
            )
            saved.append(_public_address(row))
        await gateway._safe_send_json(
            websocket,
            _frame(
                "endpoint.addresses.ack",
                endpoint_id=endpoint.endpoint_id,
                correlation_id=correlation_id,
                payload={"count": len(saved), "addresses": saved},
            ),
        )
        return

    if frame_type == "endpoint.address.delete":
        address_id = str(payload.get("address_id") or "").strip()
        deleted = domain.services.endpoint_address.delete_address(address_id=address_id) if address_id else False
        await gateway._safe_send_json(
            websocket,
            _frame("endpoint.address.delete.ack", correlation_id=correlation_id, payload={"address_id": address_id, "deleted": bool(deleted)}),
        )
        return

    if frame_type == "endpoint.ready":
        endpoint_id = str(frame.get("endpoint_id") or payload.get("endpoint_id") or state.get("endpoint_id") or "").strip()
        if endpoint_id:
            endpoint = domain.services.endpoint.set_status(endpoint_id=endpoint_id, status="ready")
            await _drain_endpoint_outbox(domain, endpoint)
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
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            call_row = domain.services.operation_call.mark_succeeded(call_id=call_id, result=result)
            await _publish_operation_update(gateway, domain, call_row, phase="completed", result=result)
            await domain.services.tool_router.notify_call_result(
                call_id,
                result,
            )
        return

    if frame_type == "tool.call.accepted":
        call_id = str(payload.get("call_id") or "").strip()
        if call_id:
            call_row = domain.services.operation_call.mark_accepted(call_id=call_id)
            await _publish_operation_update(gateway, domain, call_row, phase="accepted")
        return

    if frame_type == "tool.call.progress":
        call_id = str(payload.get("call_id") or "").strip()
        if call_id:
            detail = str(payload.get("detail") or "")
            phase = str(payload.get("phase") or "running")
            call_row = domain.services.operation_call.mark_progress(
                call_id=call_id,
                detail=detail,
                metadata={"phase": phase},
            )
            await _publish_operation_update(gateway, domain, call_row, phase=phase, detail=detail)
        return

    if frame_type == "tool.call.error":
        call_id = str(payload.get("call_id") or "").strip()
        if call_id:
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            call_row = domain.services.operation_call.mark_failed(call_id=call_id, error=error)
            await _publish_operation_update(gateway, domain, call_row, phase="failed", error=error)
            await domain.services.tool_router.notify_call_error(
                call_id,
                error,
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
