from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from core.db.base import utcnow
from endpoint_tool_sdk.protocol import (
    DEFAULT_ENDPOINT_TOOL_PROTOCOL_FEATURES,
    ENDPOINT_TOOL_PROTOCOL_VERSION,
    build_endpoint_protocol_selection,
)
from gateway.endpoint_ws import ENDPOINT_WS_SCHEMA


def endpoint_frame(frame_type: str, *, payload: dict[str, Any] | None = None, endpoint_id: str = "", correlation_id: str = "") -> dict[str, Any]:
    return {
        "schema": ENDPOINT_WS_SCHEMA,
        "type": frame_type,
        "endpoint_id": str(endpoint_id or "").strip(),
        "correlation_id": str(correlation_id or "").strip(),
        "payload": dict(payload or {}),
    }


async def send_endpoint_error(gateway, websocket, *, code: str, message: str, correlation_id: str = "") -> None:
    await gateway._safe_send_json(
        websocket,
        endpoint_frame(
            "endpoint.error",
            correlation_id=correlation_id,
            payload={"code": code, "message": message},
        ),
    )


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


def _string_set(values: Any) -> set[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    return {str(item or "").strip() for item in values if str(item or "").strip()}


def _int_set(values: Any) -> set[int]:
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    result: set[int] = set()
    for item in values:
        try:
            result.add(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _negotiate_endpoint_protocol(protocol_offer: Any) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    if not isinstance(protocol_offer, dict) or not protocol_offer:
        return None, {
            "code": "endpoint_protocol_required",
            "message": "endpoint.hello must include a V4 protocol offer",
        }
    supported_schemas = _string_set(protocol_offer.get("supported_schemas") or protocol_offer.get("schema"))
    if ENDPOINT_WS_SCHEMA not in supported_schemas:
        return None, {
            "code": "unsupported_endpoint_protocol",
            "message": f"endpoint.hello must support schema {ENDPOINT_WS_SCHEMA}",
        }
    supported_versions = _int_set(protocol_offer.get("supported_versions") or protocol_offer.get("version"))
    if ENDPOINT_TOOL_PROTOCOL_VERSION not in supported_versions:
        return None, {
            "code": "unsupported_endpoint_protocol",
            "message": f"endpoint.hello must support protocol version {ENDPOINT_TOOL_PROTOCOL_VERSION}",
        }
    server_features = tuple(DEFAULT_ENDPOINT_TOOL_PROTOCOL_FEATURES)
    offered_features = _string_set(protocol_offer.get("features") or [])
    required_features = _string_set(protocol_offer.get("required_features") or [])
    unsupported_required = sorted(required_features - set(server_features))
    if unsupported_required:
        return None, {
            "code": "unsupported_endpoint_features",
            "message": f"endpoint.hello requires unsupported features: {', '.join(unsupported_required)}",
        }
    enabled_features = [
        feature
        for feature in server_features
        if feature in offered_features or feature in required_features
    ]
    disabled_features = [feature for feature in server_features if feature not in set(enabled_features)]
    return build_endpoint_protocol_selection(
        selected_schema=ENDPOINT_WS_SCHEMA,
        selected_version=ENDPOINT_TOOL_PROTOCOL_VERSION,
        enabled_features=enabled_features,
        disabled_features=disabled_features,
    ), None


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
        "routing_decision": dict(metadata.get("routing_decision") or {}) if isinstance(metadata.get("routing_decision"), dict) else {},
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


def _invalidate_tool_router_cache(domain, *, endpoint_id: str = "") -> None:
    invalidator = getattr(getattr(domain.services, "tool_router", None), "invalidate_cache", None)
    if callable(invalidator):
        invalidator(endpoint_id=str(endpoint_id or "").strip())


@dataclass(slots=True)
class EndpointFrameContext:
    gateway: Any
    websocket: Any
    frame: dict[str, Any]
    state: dict[str, Any]
    domain: Any
    frame_type: str
    payload: dict[str, Any]
    correlation_id: str

    async def send(self, frame_type: str, *, payload: dict[str, Any] | None = None, endpoint_id: str = "") -> None:
        await self.gateway._safe_send_json(
            self.websocket,
            endpoint_frame(frame_type, endpoint_id=endpoint_id, correlation_id=self.correlation_id, payload=payload),
        )

    async def error(self, *, code: str, message: str) -> None:
        await send_endpoint_error(
            self.gateway,
            self.websocket,
            code=code,
            message=message,
            correlation_id=self.correlation_id,
        )

    def endpoint_id(self) -> str:
        return str(self.payload.get("endpoint_id") or self.frame.get("endpoint_id") or self.state.get("endpoint_id") or "").strip()


class EndpointFrameHandler:
    frame_types: tuple[str, ...] = ()

    async def handle(self, context: EndpointFrameContext) -> None:
        raise NotImplementedError


class EndpointFrameRegistry:
    def __init__(self, handlers: list[EndpointFrameHandler] | tuple[EndpointFrameHandler, ...]):
        self._handlers: dict[str, EndpointFrameHandler] = {}
        for handler in handlers:
            for frame_type in handler.frame_types:
                self._handlers[str(frame_type or "").strip()] = handler

    def handler_for(self, frame_type: str) -> EndpointFrameHandler | None:
        return self._handlers.get(str(frame_type or "").strip())

    def handler_names(self) -> dict[str, str]:
        return {frame_type: handler.__class__.__name__ for frame_type, handler in self._handlers.items()}

    async def dispatch(self, gateway, websocket, frame: dict[str, Any], state: dict[str, Any]) -> None:
        if str(frame.get("schema") or "") != ENDPOINT_WS_SCHEMA:
            await send_endpoint_error(gateway, websocket, code="invalid_schema", message="expected meetyou.endpoint.ws.v4")
            return
        frame_type = str(frame.get("type") or "").strip()
        payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
        correlation_id = str(frame.get("message_id") or frame.get("correlation_id") or "").strip()
        handler = self.handler_for(frame_type)
        if handler is None:
            await send_endpoint_error(
                gateway,
                websocket,
                code="unsupported_frame",
                message=f"unsupported endpoint frame: {frame_type}",
                correlation_id=correlation_id,
            )
            return
        context = EndpointFrameContext(
            gateway=gateway,
            websocket=websocket,
            frame=frame,
            state=state,
            domain=gateway._require_core_domain(),
            frame_type=frame_type,
            payload=payload,
            correlation_id=correlation_id,
        )
        await handler.handle(context)


class EndpointHelloHandler(EndpointFrameHandler):
    frame_types = ("endpoint.hello",)

    async def handle(self, context: EndpointFrameContext) -> None:
        provider = context.payload.get("provider") if isinstance(context.payload.get("provider"), dict) else {}
        provider = dict(provider)
        provider_supports_markdown = _bool_value(
            provider.get("supports_markdown", context.payload.get("supports_markdown")),
            default=True,
        )
        provider["supports_markdown"] = provider_supports_markdown
        protocol_selection, protocol_error = _negotiate_endpoint_protocol(context.payload.get("protocol"))
        if protocol_error:
            await context.send(
                "endpoint.hello.ack",
                payload={
                    "accepted": False,
                    "reject_reason": protocol_error,
                },
            )
            return
        endpoints = context.payload.get("endpoints") if isinstance(context.payload.get("endpoints"), list) else []
        if not endpoints:
            await context.error(code="endpoint_required", message="endpoint.hello requires at least one endpoint")
            return
        created = []
        primary = None
        for item in endpoints:
            if not isinstance(item, dict):
                continue
            endpoint_id = str(item.get("endpoint_id") or "").strip()
            if not endpoint_id:
                continue
            endpoint_supports_markdown = _bool_value(item.get("supports_markdown"), default=provider_supports_markdown)
            row = context.domain.services.endpoint.ensure_endpoint(
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
            await context.error(code="endpoint_required", message="endpoint.hello did not include a valid endpoint")
            return
        connection_id = str(context.frame.get("connection_id") or context.payload.get("connection_id") or f"conn_{uuid4().hex}")
        context.state["endpoint_id"] = primary.endpoint_id
        context.state["endpoint_ids"] = created
        context.state["connection_id"] = connection_id
        connection = context.domain.services.endpoint_connection.upsert_connection(
            endpoint_row_id=primary.id,
            connection_id=connection_id,
            protocol_version=ENDPOINT_WS_SCHEMA,
            remote_addr=str(getattr(getattr(context.websocket, "client", None), "host", "") or ""),
            metadata={"provider": provider, "endpoints": created},
        )
        await context.gateway.endpoint_ws_manager.bind_endpoint(
            context.websocket,
            endpoint_id=primary.endpoint_id,
            connection_id=connection.connection_id,
            provider=provider,
            metadata={"endpoint_ids": created},
        )
        for created_endpoint_id in created:
            _invalidate_tool_router_cache(context.domain, endpoint_id=created_endpoint_id)
        await context.send(
            "endpoint.hello.ack",
            endpoint_id=primary.endpoint_id,
            payload={
                "accepted": True,
                "protocol": protocol_selection,
                "connection_id": connection.connection_id,
                "requires_capabilities_snapshot": True,
                "heartbeat_interval_seconds": 20,
                "registered_endpoints": created,
            },
        )


class CapabilitySnapshotHandler(EndpointFrameHandler):
    frame_types = ("endpoint.capabilities.snapshot",)

    async def handle(self, context: EndpointFrameContext) -> None:
        endpoint_id = context.endpoint_id()
        endpoint = context.domain.services.endpoint.get_by_endpoint_id(endpoint_id)
        if endpoint is None:
            await context.error(code="endpoint_not_found", message=f"unknown endpoint: {endpoint_id}")
            return
        capabilities = context.payload.get("capabilities") if isinstance(context.payload.get("capabilities"), list) else []
        count = context.domain.services.endpoint_capability.replace_snapshot(
            endpoint_row_id=endpoint.id,
            endpoint_public_id=endpoint.endpoint_id,
            capabilities=capabilities,
        )
        _invalidate_tool_router_cache(context.domain, endpoint_id=endpoint.endpoint_id)
        await context.send("endpoint.ready", endpoint_id=endpoint.endpoint_id, payload={"registered_capability_count": count})
        await _drain_endpoint_outbox(context.domain, endpoint)


class AddressHandler(EndpointFrameHandler):
    frame_types = ("endpoint.addresses.snapshot", "endpoint.address.upsert", "endpoint.address.delete")

    async def handle(self, context: EndpointFrameContext) -> None:
        if context.frame_type == "endpoint.address.delete":
            address_id = str(context.payload.get("address_id") or "").strip()
            deleted = context.domain.services.endpoint_address.delete_address(address_id=address_id) if address_id else False
            await context.send("endpoint.address.delete.ack", payload={"address_id": address_id, "deleted": bool(deleted)})
            return

        endpoint_id = context.endpoint_id()
        endpoint = context.domain.services.endpoint.get_by_endpoint_id(endpoint_id)
        if endpoint is None:
            await context.error(code="endpoint_not_found", message=f"unknown endpoint: {endpoint_id}")
            return
        provider_type = str(getattr(endpoint, "provider_type", "") or "").strip()
        raw_addresses = context.payload.get("addresses") if context.frame_type == "endpoint.addresses.snapshot" else [context.payload.get("address") or context.payload]
        if not isinstance(raw_addresses, list):
            raw_addresses = []
        saved = []
        for item in raw_addresses:
            if not isinstance(item, dict):
                continue
            normalized = _address_payload_item(item, endpoint_id=endpoint.endpoint_id, provider_type=provider_type)
            if not normalized["external_ref"]:
                continue
            row = context.domain.services.endpoint_address.upsert_address(
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
        await context.send(
            "endpoint.addresses.ack",
            endpoint_id=endpoint.endpoint_id,
            payload={"count": len(saved), "addresses": saved},
        )


class EndpointLifecycleHandler(EndpointFrameHandler):
    frame_types = ("endpoint.ready", "endpoint.heartbeat", "endpoint.goodbye")

    async def handle(self, context: EndpointFrameContext) -> None:
        if context.frame_type == "endpoint.ready":
            endpoint_id = context.endpoint_id()
            if endpoint_id:
                endpoint = context.domain.services.endpoint.set_status(endpoint_id=endpoint_id, status="ready")
                _invalidate_tool_router_cache(context.domain, endpoint_id=endpoint_id)
                await _drain_endpoint_outbox(context.domain, endpoint)
            return

        if context.frame_type == "endpoint.heartbeat":
            connection_id = str(context.frame.get("connection_id") or context.payload.get("connection_id") or context.state.get("connection_id") or "").strip()
            endpoint_id = context.endpoint_id()
            metrics = context.payload.get("metrics") if isinstance(context.payload.get("metrics"), dict) else {}
            status = str(context.payload.get("status") or "ready").strip() or "ready"
            if connection_id:
                context.domain.services.endpoint_connection.heartbeat(
                    connection_id=connection_id,
                    metadata={"heartbeat": context.payload, "endpoint_id": endpoint_id, "metrics": dict(metrics or {})},
                )
            updater = getattr(context.domain.services.endpoint, "update_heartbeat", None)
            if callable(updater) and endpoint_id:
                updater(endpoint_id=endpoint_id, status=status, metrics=dict(metrics or {}), payload=context.payload)
                _invalidate_tool_router_cache(context.domain, endpoint_id=endpoint_id)
            return

        connection_id = str(context.state.get("connection_id") or "").strip()
        if connection_id:
            context.domain.services.endpoint_connection.mark_disconnected(connection_id=connection_id)
        await context.websocket.close(code=1000)


class SubscriptionHandler(EndpointFrameHandler):
    frame_types = ("subscription.start", "subscription.update", "subscription.stop")

    async def handle(self, context: EndpointFrameContext) -> None:
        if context.frame_type == "subscription.stop":
            target_type = str(context.payload.get("target_type") or "").strip()
            target_id = str(context.payload.get("target_id") or "").strip()
            subscription_id = str(context.payload.get("subscription_id") or "").strip()
            removed = await context.gateway.endpoint_ws_manager.unsubscribe(
                context.websocket,
                target_type=target_type,
                target_id=target_id,
                subscription_id=subscription_id,
            )
            await context.send(
                "subscription.ack",
                payload={
                    "action": "stop",
                    "subscription_id": subscription_id,
                    "target_type": target_type,
                    "target_id": target_id,
                    "active": False,
                    "removed": removed,
                },
            )
            return
        target_type = str(context.payload.get("target_type") or "").strip()
        target_id = str(context.payload.get("target_id") or "").strip()
        subscription_id = str(context.payload.get("subscription_id") or "").strip()
        if not target_type or not target_id:
            await context.error(code="subscription_target_required", message="subscription requires target_type and target_id")
            return
        if context.frame_type == "subscription.update":
            await context.gateway.endpoint_ws_manager.update_subscription(
                context.websocket,
                target_type=target_type,
                target_id=target_id,
                subscription_id=subscription_id,
            )
        else:
            await context.gateway.endpoint_ws_manager.subscribe(
                context.websocket,
                target_type=target_type,
                target_id=target_id,
                subscription_id=subscription_id,
            )
        await context.send(
            "subscription.ack",
            payload={
                "action": "update" if context.frame_type == "subscription.update" else "start",
                "subscription_id": subscription_id,
                "target_type": target_type,
                "target_id": target_id,
                "active": True,
            },
        )
        replay = context.payload.get("replay", True)
        if isinstance(replay, str):
            replay = replay.strip().lower() not in {"0", "false", "no", "off"}
        if target_type == "thread" and bool(replay):
            thread = context.domain.services.thread.get_by_thread_id(target_id)
            if thread is not None:
                for event in context.domain.services.run_event.list_for_thread_after(
                    thread_id=thread.id,
                    after_seq=int(context.payload.get("last_seen_event_seq") or 0),
                    durable_only=True,
                ):
                    await context.gateway._safe_send_json(
                        context.websocket,
                        endpoint_frame("delivery.run_event", payload=_public_run_event(event)),
                    )


class ToolResultHandler(EndpointFrameHandler):
    frame_types = ("tool.call.result", "tool.call.accepted", "tool.call.progress", "tool.call.error", "tool.call.cancel")

    async def handle(self, context: EndpointFrameContext) -> None:
        call_id = str(context.payload.get("call_id") or "").strip()
        if not call_id:
            return
        if context.frame_type == "tool.call.cancel":
            reason = str(context.payload.get("reason") or "endpoint cancelled tool call")
            error = {"code": "endpoint_tool_cancelled", "message": reason, "retryable": False}
            call_row = await context.domain.services.tool_router.notify_call_cancelled(call_id, error)
            await _publish_operation_update(context.gateway, context.domain, call_row, phase="cancelled", error=error)
            return
        if context.frame_type == "tool.call.result":
            result = context.payload.get("result") if isinstance(context.payload.get("result"), dict) else {}
            call_row = await context.domain.services.tool_router.notify_call_result(call_id, result)
            await _publish_operation_update(context.gateway, context.domain, call_row, phase="completed", result=result)
            return
        if context.frame_type == "tool.call.accepted":
            call_row = context.domain.services.operation_call.mark_accepted(call_id=call_id)
            await _publish_operation_update(context.gateway, context.domain, call_row, phase="accepted")
            return
        if context.frame_type == "tool.call.progress":
            detail = str(context.payload.get("detail") or "")
            phase = str(context.payload.get("phase") or "running")
            call_row = context.domain.services.operation_call.mark_progress(
                call_id=call_id,
                detail=detail,
                metadata={"phase": phase},
            )
            await _publish_operation_update(context.gateway, context.domain, call_row, phase=phase, detail=detail)
            return
        error = context.payload.get("error") if isinstance(context.payload.get("error"), dict) else {}
        call_row = await context.domain.services.tool_router.notify_call_error(call_id, error)
        await _publish_operation_update(context.gateway, context.domain, call_row, phase="failed", error=error)


def build_default_endpoint_frame_registry() -> EndpointFrameRegistry:
    return EndpointFrameRegistry(
        [
            EndpointHelloHandler(),
            CapabilitySnapshotHandler(),
            AddressHandler(),
            EndpointLifecycleHandler(),
            SubscriptionHandler(),
            ToolResultHandler(),
        ]
    )


DEFAULT_ENDPOINT_FRAME_REGISTRY = build_default_endpoint_frame_registry()


async def handle_endpoint_frame(gateway, websocket, frame: dict[str, Any], state: dict[str, Any], *, registry: EndpointFrameRegistry | None = None) -> None:
    await (registry or DEFAULT_ENDPOINT_FRAME_REGISTRY).dispatch(gateway, websocket, frame, state)
