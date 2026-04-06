"""
FastAPI 网关。
"""

import asyncio
import contextlib
import inspect
import re

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from core.exceptions import ConfigError
from core.io_protocol import (
    EventTarget,
    EventType,
    InboundEvent,
    SourceKind,
    TargetKind,
    make_source,
)
from core.protocol_schema import build_ui_protocol_schema
from gateway.models import (
    AckPayload,
    AckResponse,
    ConfigEntryResponse,
    ConfigPatchRequest,
    ConfigPatchResponse,
    ConfigSnapshotResponse,
    ControlRequest,
    ErrorResponse,
    HealthEnvelopeResponse,
    HealthResponse,
    InputRequest,
    MemoryGraphResponse,
    MemorySnapshotResponse,
    RuntimeEnvelopePayload,
    RuntimeEnvelopeResponse,
    RuntimeStateResponse,
    RuntimeUsageResponse,
    UiProtocolSchemaEnvelopeResponse,
    UiProtocolSchemaResponse,
    WebSocketCommand,
)
from service_runtime.models import RuntimeError, RuntimeErrorCategory
from gateway.ws_manager import WebSocketManager, WebSocketOutputAdapter


_HTTP_SCHEMA = "meetyou.http.v1"
_WS_SCHEMA = "meetyou.ws.v1"
_LOOPBACK_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$", re.IGNORECASE)


class GatewayHttpError(Exception):
    def __init__(self, status_code: int, error: RuntimeError):
        super().__init__(error.message)
        self.status_code = status_code
        self.error = error


class FastAPIGateway:
    def __init__(
        self,
        event_bus,
        session_manager,
        config_snapshot_getter=None,
        config_item_getter=None,
        config_updater=None,
        memory_snapshot_getter=None,
        memory_graph_getter=None,
        runtime_state_getter=None,
        runtime_usage_getter=None,
        runtime_debug_getter=None,
        health_getter=None,
        ws_delivery_observer=None,
        access_token: str = "",
        cors_origins: list[str] | tuple[str, ...] | None = None,
    ):
        self._event_bus = event_bus
        self._session_manager = session_manager
        self._config_snapshot_getter = config_snapshot_getter
        self._config_item_getter = config_item_getter
        self._config_updater = config_updater
        self._memory_snapshot_getter = memory_snapshot_getter
        self._memory_graph_getter = memory_graph_getter
        self._runtime_state_getter = runtime_state_getter
        self._runtime_usage_getter = runtime_usage_getter
        self._runtime_debug_getter = runtime_debug_getter
        self._health_getter = health_getter
        self._access_token = str(access_token or "").strip()
        self._cors_origins = tuple(
            origin
            for origin in {
                str(item or "").strip()
                for item in (cors_origins or [])
            }
            if origin
        )
        self.ws_manager = WebSocketManager(delivery_observer=ws_delivery_observer)
        self.output_adapter = WebSocketOutputAdapter(self.ws_manager)
        self.app = FastAPI(title="MeetYou Gateway")
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=list(self._cors_origins),
            allow_origin_regex=_LOOPBACK_ORIGIN_RE.pattern,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["Authorization", "Content-Type", "X-API-Key"],
        )
        self._server = None
        self._server_task = None
        self._setup_exception_handlers()
        self._setup_routes()

    async def _resolve(self, func, *args, **kwargs):
        if func is None:
            self._raise_http_error(
                status_code=404,
                code="service_unavailable",
                category=RuntimeErrorCategory.DEPENDENCY.value,
                message="配置服务未启用",
            )
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def _setup_exception_handlers(self):
        @self.app.exception_handler(GatewayHttpError)
        async def handle_gateway_http_error(request: Request, exc: GatewayHttpError):
            del request
            return JSONResponse(
                status_code=exc.status_code,
                content=ErrorResponse(
                    schema_name=_HTTP_SCHEMA,
                    error=exc.error,
                ).model_dump(by_alias=True),
            )

        @self.app.exception_handler(HTTPException)
        async def handle_http_exception(request: Request, exc: HTTPException):
            del request
            detail = exc.detail
            message = detail if isinstance(detail, str) else "请求失败"
            error = RuntimeError(
                code=f"http_{exc.status_code}",
                category=RuntimeErrorCategory.RUNTIME.value,
                message=message,
                details={"status_code": exc.status_code},
            )
            return JSONResponse(
                status_code=exc.status_code,
                content=ErrorResponse(
                    schema_name=_HTTP_SCHEMA,
                    error=error,
                ).model_dump(by_alias=True),
            )

        @self.app.exception_handler(RequestValidationError)
        async def handle_request_validation_error(request: Request, exc: RequestValidationError):
            del request
            error = RuntimeError(
                code="invalid_request",
                category=RuntimeErrorCategory.VALIDATION.value,
                message="请求参数不合法",
                details={"errors": exc.errors()},
            )
            return JSONResponse(
                status_code=422,
                content=ErrorResponse(
                    schema_name=_HTTP_SCHEMA,
                    error=error,
                ).model_dump(by_alias=True),
            )

    def _build_error(
        self,
        *,
        code: str,
        message: str,
        category: str = RuntimeErrorCategory.RUNTIME.value,
        retryable: bool = False,
        details: dict | None = None,
    ) -> RuntimeError:
        return RuntimeError(
            code=code,
            category=category,
            message=message,
            retryable=retryable,
            details=dict(details or {}),
        )

    def _raise_http_error(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        category: str = RuntimeErrorCategory.RUNTIME.value,
        retryable: bool = False,
        details: dict | None = None,
    ) -> None:
        raise GatewayHttpError(
            status_code,
            self._build_error(
                code=code,
                message=message,
                category=category,
                retryable=retryable,
                details=details,
            ),
        )

    def _extract_bearer_token(self, authorization: str) -> str:
        scheme, _, token = str(authorization or "").partition(" ")
        if scheme.lower() != "bearer":
            return ""
        return token.strip()

    def _resolve_http_access_token(self, request: Request) -> str:
        bearer = self._extract_bearer_token(request.headers.get("Authorization", ""))
        if bearer:
            return bearer
        return str(request.headers.get("X-API-Key", "")).strip()

    def _resolve_ws_access_token(self, websocket: WebSocket) -> str:
        bearer = self._extract_bearer_token(websocket.headers.get("Authorization", ""))
        if bearer:
            return bearer
        header_token = str(websocket.headers.get("X-API-Key", "")).strip()
        if header_token:
            return header_token
        return str(websocket.query_params.get("access_token", "")).strip()

    def _is_origin_allowed(self, origin: str) -> bool:
        candidate = str(origin or "").strip()
        if not candidate:
            return True
        if candidate in self._cors_origins:
            return True
        return bool(_LOOPBACK_ORIGIN_RE.fullmatch(candidate))

    def _require_http_auth(self, request: Request) -> None:
        if not self._access_token:
            return
        access_token = self._resolve_http_access_token(request)
        if access_token == self._access_token:
            return
        self._raise_http_error(
            status_code=401,
            code="unauthorized",
            category=RuntimeErrorCategory.RUNTIME.value,
            message="缺少有效访问令牌",
            details={"auth_type": "bearer_or_api_key"},
        )

    async def _send_ws_error_and_close(
        self,
        websocket: WebSocket,
        *,
        code: str,
        message: str,
        category: str = RuntimeErrorCategory.RUNTIME.value,
        details: dict | None = None,
        close_code: int = 4401,
    ) -> None:
        await websocket.accept()
        await self._safe_send_json(
            websocket,
            {
                "schema": _WS_SCHEMA,
                "kind": "error",
                "error": self._build_error(
                    code=code,
                    category=category,
                    message=message,
                    details=details,
                ).model_dump(),
            },
        )
        await websocket.close(code=close_code)

    async def _authorize_websocket(self, websocket: WebSocket) -> bool:
        origin = websocket.headers.get("origin", "")
        if origin and not self._is_origin_allowed(origin):
            await self._send_ws_error_and_close(
                websocket,
                code="origin_not_allowed",
                category=RuntimeErrorCategory.RUNTIME.value,
                message="当前 Origin 不在允许列表内",
                details={"origin": origin},
                close_code=status.WS_1008_POLICY_VIOLATION,
            )
            return False
        if not self._access_token:
            return True
        access_token = self._resolve_ws_access_token(websocket)
        if access_token == self._access_token:
            return True
        await self._send_ws_error_and_close(
            websocket,
            code="unauthorized",
            category=RuntimeErrorCategory.RUNTIME.value,
            message="缺少有效访问令牌",
            details={"auth_type": "bearer_or_api_key_or_query"},
            close_code=4401,
        )
        return False

    async def _safe_send_json(self, websocket: WebSocket, payload: dict) -> bool:
        try:
            await websocket.send_json(payload)
            return True
        except WebSocketDisconnect:
            return False
        except Exception:
            return False

    def _setup_routes(self):
        @self.app.get("/health", response_model=HealthEnvelopeResponse)
        async def health():
            payload = await self._resolve(self._health_getter) if self._health_getter is not None else {}
            if isinstance(payload, HealthResponse):
                health_payload = payload
            elif hasattr(payload, "model_dump"):
                health_payload = HealthResponse(**payload.model_dump())
            else:
                health_payload = HealthResponse(**payload)
            return HealthEnvelopeResponse(
                schema_name=_HTTP_SCHEMA,
                health=health_payload,
            )

        @self.app.get("/schema/ui", response_model=UiProtocolSchemaEnvelopeResponse)
        async def get_ui_schema(request: Request):
            self._require_http_auth(request)
            return UiProtocolSchemaEnvelopeResponse(
                schema_name=_HTTP_SCHEMA,
                ui_schema=UiProtocolSchemaResponse(**build_ui_protocol_schema()),
            )

        @self.app.post("/inputs", response_model=AckResponse)
        async def post_inputs(http_request: Request, request: InputRequest):
            self._require_http_auth(http_request)
            metadata = dict(request.metadata)
            if request.preferred_mode:
                metadata["preferred_mode"] = request.preferred_mode
            if request.options is not None:
                metadata["input_options"] = request.options.model_dump(exclude_none=True)
            client_message_id = str(request.client_message_id or "").strip()
            if client_message_id:
                metadata["client_message_id"] = client_message_id
            source = make_source(SourceKind.WEB.value, request.source_id, **request.metadata)
            session_id = self._session_manager.get_or_create_session(source, request.session_id)
            if client_message_id:
                existing_event_id = self._session_manager.get_recent_inbound_event_id(
                    session_id,
                    source,
                    client_message_id,
                )
                if existing_event_id:
                    return AckResponse(
                        schema_name=_HTTP_SCHEMA,
                        ack=AckPayload(
                            action="input.accepted",
                            session_id=session_id,
                            event_id=existing_event_id,
                        ),
                    )
            event = InboundEvent(
                session_id=session_id,
                type=EventType.MESSAGE.value,
                role=request.role,
                content=request.content,
                source=source,
                target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                metadata=metadata,
            )
            if client_message_id:
                remembered_event_id = self._session_manager.remember_inbound_event_id(
                    session_id,
                    source,
                    client_message_id,
                    event.event_id,
                )
                if remembered_event_id != event.event_id:
                    return AckResponse(
                        schema_name=_HTTP_SCHEMA,
                        ack=AckPayload(
                            action="input.accepted",
                            session_id=session_id,
                            event_id=remembered_event_id,
                        ),
                    )
            await self._event_bus.inbound_queue.put(event)
            return AckResponse(
                schema_name=_HTTP_SCHEMA,
                ack=AckPayload(
                    action="input.accepted",
                    session_id=session_id,
                    event_id=event.event_id,
                ),
            )

        @self.app.post("/controls", response_model=AckResponse)
        async def post_controls(http_request: Request, request: ControlRequest):
            self._require_http_auth(http_request)
            metadata = dict(request.metadata)
            metadata["control_kind"] = "reply_control"
            client_request_id = str(request.client_request_id or "").strip()
            if client_request_id:
                metadata["client_request_id"] = client_request_id
            source = make_source(SourceKind.WEB.value, request.source_id, **request.metadata)
            session_id = self._session_manager.get_or_create_session(source, request.session_id)
            if client_request_id:
                existing_event_id = self._session_manager.get_recent_inbound_event_id(
                    session_id,
                    source,
                    client_request_id,
                )
                if existing_event_id:
                    return AckResponse(
                        schema_name=_HTTP_SCHEMA,
                        ack=AckPayload(
                            action=request.action,
                            session_id=session_id,
                            event_id=existing_event_id,
                            request_id=client_request_id,
                            status="accepted",
                        ),
                    )
            event = InboundEvent(
                session_id=session_id,
                type=EventType.CONTROL.value,
                role="system",
                content={
                    "action": request.action,
                    "guidance": request.guidance,
                    "checkpoint_id": request.checkpoint_id,
                    "turn_id": request.turn_id,
                    "stream_id": request.stream_id,
                },
                source=source,
                target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                metadata=metadata,
            )
            if client_request_id:
                remembered_event_id = self._session_manager.remember_inbound_event_id(
                    session_id,
                    source,
                    client_request_id,
                    event.event_id,
                )
                if remembered_event_id != event.event_id:
                    return AckResponse(
                        schema_name=_HTTP_SCHEMA,
                        ack=AckPayload(
                            action=request.action,
                            session_id=session_id,
                            event_id=remembered_event_id,
                            request_id=client_request_id,
                            status="accepted",
                        ),
                    )
            await self._event_bus.inbound_queue.put(event)
            return AckResponse(
                schema_name=_HTTP_SCHEMA,
                ack=AckPayload(
                    action=request.action,
                    session_id=session_id,
                    event_id=event.event_id,
                    request_id=client_request_id,
                    status="accepted",
                ),
            )

        @self.app.get("/config", response_model=ConfigSnapshotResponse)
        async def get_config(request: Request):
            self._require_http_auth(request)
            items = await self._resolve(self._config_snapshot_getter)
            return ConfigSnapshotResponse(
                items={
                    key: ConfigEntryResponse(**value)
                    for key, value in items.items()
                }
            )

        @self.app.get("/config/{key}", response_model=ConfigEntryResponse)
        async def get_config_item(key: str, request: Request):
            self._require_http_auth(request)
            try:
                item = await self._resolve(self._config_item_getter, key)
            except Exception as e:
                self._raise_http_error(
                    status_code=404,
                    code="config_not_found",
                    category=RuntimeErrorCategory.DEPENDENCY.value,
                    message=str(e),
                    details={"key": key},
                )
            return ConfigEntryResponse(**item)

        @self.app.patch("/config", response_model=ConfigPatchResponse)
        async def patch_config(http_request: Request, request: ConfigPatchRequest):
            self._require_http_auth(http_request)
            try:
                result = await self._resolve(self._config_updater, request.updates)
            except (ConfigError, ValueError) as exc:
                self._raise_http_error(
                    status_code=400,
                    code="invalid_config_update",
                    category=RuntimeErrorCategory.VALIDATION.value,
                    message=str(exc),
                )
            return ConfigPatchResponse(**result)

        @self.app.get("/memory", response_model=MemorySnapshotResponse)
        async def get_memory(
            request: Request,
            source_id: str = "",
            session_id: str = "",
            include_invalidated: bool = False,
        ):
            self._require_http_auth(request)
            payload = await self._resolve(
                self._memory_snapshot_getter,
                source_id=source_id,
                session_id=session_id,
                include_invalidated=include_invalidated,
            )
            return MemorySnapshotResponse(**payload)

        @self.app.get("/memory/graph", response_model=MemoryGraphResponse)
        async def get_memory_graph(
            request: Request,
            source_id: str = "",
            session_id: str = "",
            include_invalidated: bool = False,
        ):
            self._require_http_auth(request)
            payload = await self._resolve(
                self._memory_graph_getter,
                source_id=source_id,
                session_id=session_id,
                include_invalidated=include_invalidated,
            )
            return MemoryGraphResponse(**payload)

        @self.app.get("/runtime/state", response_model=RuntimeEnvelopeResponse)
        async def get_runtime_state(request: Request, session_id: str = ""):
            self._require_http_auth(request)
            try:
                payload = await self._resolve(self._runtime_state_getter, session_id=session_id)
            except Exception as e:
                self._raise_http_error(
                    status_code=404,
                    code="runtime_state_not_found",
                    category=RuntimeErrorCategory.DEPENDENCY.value,
                    message=str(e),
                    details={"session_id": session_id},
                )
            state = RuntimeStateResponse(**payload)
            resolved_session_id = ""
            if state.session_state is not None and state.session_state.session_id:
                resolved_session_id = state.session_state.session_id
            elif state.global_state.session_id:
                resolved_session_id = state.global_state.session_id
            return RuntimeEnvelopeResponse(
                schema_name=_HTTP_SCHEMA,
                runtime=RuntimeEnvelopePayload(
                    resource="state",
                    session_id=resolved_session_id,
                    state=state,
                ),
            )

        @self.app.get("/runtime/usage", response_model=RuntimeEnvelopeResponse)
        async def get_runtime_usage(request: Request, session_id: str):
            self._require_http_auth(request)
            try:
                payload = await self._resolve(self._runtime_usage_getter, session_id=session_id)
            except Exception as e:
                self._raise_http_error(
                    status_code=404,
                    code="runtime_usage_not_found",
                    category=RuntimeErrorCategory.DEPENDENCY.value,
                    message=str(e),
                    details={"session_id": session_id},
                )
            usage = RuntimeUsageResponse(**payload)
            return RuntimeEnvelopeResponse(
                schema_name=_HTTP_SCHEMA,
                runtime=RuntimeEnvelopePayload(
                    resource="usage",
                    session_id=usage.session_id,
                    usage=usage,
                ),
            )

        @self.app.get("/runtime/debug", response_model=RuntimeEnvelopeResponse)
        async def get_runtime_debug(request: Request, session_id: str):
            self._require_http_auth(request)
            try:
                payload = await self._resolve(self._runtime_debug_getter, session_id=session_id)
            except Exception as e:
                self._raise_http_error(
                    status_code=404,
                    code="runtime_debug_not_found",
                    category=RuntimeErrorCategory.DEPENDENCY.value,
                    message=str(e),
                    details={"session_id": session_id},
                )
            return RuntimeEnvelopeResponse(
                schema_name=_HTTP_SCHEMA,
                runtime=RuntimeEnvelopePayload(
                    resource="debug",
                    session_id=str(payload.get("session_id") or session_id),
                    debug=dict(payload or {}),
                ),
            )

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            if not await self._authorize_websocket(websocket):
                return
            await websocket.accept()
            source_id = websocket.query_params.get("source_id", "websocket")
            requested_session_id = websocket.query_params.get("session_id")
            source = make_source(SourceKind.WEB.value, source_id)
            session_id = self._session_manager.get_or_create_session(source, requested_session_id)
            await self.ws_manager.connect(session_id, websocket)
            connected = await self._safe_send_json(websocket, {
                "schema": _WS_SCHEMA,
                "kind": "connection",
                "connection": {
                    "session_id": session_id,
                    "source_id": source_id,
                    "status": "connected",
                },
            })
            if not connected:
                await self.ws_manager.disconnect(session_id, websocket)
                return
            try:
                while True:
                    try:
                        command = WebSocketCommand.model_validate(
                            await websocket.receive_json()
                        )
                    except WebSocketDisconnect:
                        break
                    except ValidationError as e:
                        error = RuntimeError(
                            code="invalid_payload",
                            category="validation",
                            message=str(e),
                        )
                        sent = await self._safe_send_json(websocket, {
                            "schema": _WS_SCHEMA,
                            "kind": "error",
                            "error": error.model_dump(),
                        })
                        if not sent:
                            break
                        continue
                    if command.action == "ping":
                        sent = await self._safe_send_json(websocket, {
                            "schema": _WS_SCHEMA,
                            "kind": "pong",
                        })
                        if not sent:
                            break
                        continue
                    if command.action == "confirm_response":
                        if command.request_id is None or command.accepted is None:
                            error = RuntimeError(
                                code="invalid_confirm_response",
                                category="validation",
                                message="request_id 和 accepted 为必填字段",
                            )
                            sent = await self._safe_send_json(websocket, {
                                "schema": _WS_SCHEMA,
                                "kind": "error",
                                "error": error.model_dump(),
                            })
                            if not sent:
                                break
                            continue
                        resolved = self._event_bus.submit_confirmation_response(
                            command.accepted,
                            request_id=command.request_id,
                            session_id=session_id,
                        )
                        if not resolved:
                            error = RuntimeError(
                                code="stale_confirm_response",
                                message="确认请求已失效、已处理，或与当前会话不匹配。",
                            )
                            sent = await self._safe_send_json(websocket, {
                                "schema": _WS_SCHEMA,
                                "kind": "error",
                                "error": error.model_dump(),
                            })
                            if not sent:
                                break
                            continue
                        sent = await self._safe_send_json(websocket, {
                            "schema": _WS_SCHEMA,
                            "kind": "ack",
                            "ack": {
                                "action": command.action,
                                "request_id": command.request_id,
                                "session_id": session_id,
                                "accepted": True,
                            },
                        })
                        if not sent:
                            break
                        continue
                    if command.action in {"stop", "append_guidance", "regenerate", "rollback", "list_checkpoints"}:
                        client_request_id = str(command.client_request_id or "").strip()
                        if client_request_id:
                            existing_event_id = self._session_manager.get_recent_inbound_event_id(
                                session_id,
                                source,
                                client_request_id,
                            )
                            if existing_event_id:
                                sent = await self._safe_send_json(websocket, {
                                    "schema": _WS_SCHEMA,
                                    "kind": "ack",
                                    "ack": {
                                        "action": command.action,
                                        "request_id": client_request_id,
                                        "session_id": session_id,
                                        "event_id": existing_event_id,
                                        "accepted": True,
                                        "status": "accepted",
                                    },
                                })
                                if not sent:
                                    break
                                continue
                        event = InboundEvent(
                            session_id=session_id,
                            type=EventType.CONTROL.value,
                            role="system",
                            content={
                                "action": command.action,
                                "guidance": command.guidance,
                                "checkpoint_id": command.checkpoint_id,
                                "turn_id": command.turn_id,
                                "stream_id": command.stream_id,
                            },
                            source=source,
                            target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                            metadata={
                                "control_kind": "reply_control",
                                **dict(command.metadata or {}),
                                **({"client_request_id": client_request_id} if client_request_id else {}),
                            },
                        )
                        if client_request_id:
                            remembered_event_id = self._session_manager.remember_inbound_event_id(
                                session_id,
                                source,
                                client_request_id,
                                event.event_id,
                            )
                            if remembered_event_id != event.event_id:
                                sent = await self._safe_send_json(websocket, {
                                    "schema": _WS_SCHEMA,
                                    "kind": "ack",
                                    "ack": {
                                        "action": command.action,
                                        "request_id": client_request_id,
                                        "session_id": session_id,
                                        "event_id": remembered_event_id,
                                        "accepted": True,
                                        "status": "accepted",
                                    },
                                })
                                if not sent:
                                    break
                                continue
                        await self._event_bus.inbound_queue.put(event)
                        sent = await self._safe_send_json(websocket, {
                            "schema": _WS_SCHEMA,
                            "kind": "ack",
                            "ack": {
                                "action": command.action,
                                "request_id": client_request_id,
                                "session_id": session_id,
                                "event_id": event.event_id,
                                "accepted": True,
                                "status": "accepted",
                            },
                        })
                        if not sent:
                            break
                        continue
                    if command.action == "input_response":
                        if command.request_id is None:
                            error = RuntimeError(
                                code="invalid_input_response",
                                category="validation",
                                message="request_id 为必填字段",
                            )
                            sent = await self._safe_send_json(websocket, {
                                "schema": _WS_SCHEMA,
                                "kind": "error",
                                "error": error.model_dump(),
                            })
                            if not sent:
                                break
                            continue
                        resolved = self._event_bus.submit_human_input_response(
                            command.answer_text or "",
                            request_id=command.request_id,
                            session_id=session_id,
                            selected_option=command.selected_option,
                        )
                        if not resolved:
                            error = RuntimeError(
                                code="stale_input_response",
                                message="输入请求已失效、已处理，或与当前会话不匹配。",
                            )
                            sent = await self._safe_send_json(websocket, {
                                "schema": _WS_SCHEMA,
                                "kind": "error",
                                "error": error.model_dump(),
                            })
                            if not sent:
                                break
                            continue
                        sent = await self._safe_send_json(websocket, {
                            "schema": _WS_SCHEMA,
                            "kind": "ack",
                            "ack": {
                                "action": command.action,
                                "request_id": command.request_id,
                                "session_id": session_id,
                                "accepted": True,
                            },
                        })
                        if not sent:
                            break
                        continue
                    error = RuntimeError(
                        code="unsupported_action",
                        category="validation",
                        message=f"不支持的 action: {command.action}",
                    )
                    sent = await self._safe_send_json(websocket, {
                        "schema": _WS_SCHEMA,
                        "kind": "error",
                        "error": error.model_dump(),
                    })
                    if not sent:
                        break
            except WebSocketDisconnect:
                pass
            finally:
                await self.ws_manager.disconnect(session_id, websocket)

    async def start(self, host: str = "127.0.0.1", port: int = 8000):
        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._server.serve())

    async def stop(self):
        if self._server:
            self._server.should_exit = True
        if self._server_task:
            self._server_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._server_task
