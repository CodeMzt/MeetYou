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

from core.exceptions import ConfigError
from core.interaction_response_service import InteractionResponseService
from core.protocol_schema import build_ui_protocol_schema
from gateway.dependencies import GatewayDependencies
from gateway.endpoint_ws import EndpointWebSocketManager
from gateway.models import (
    ConfigEntryResponse,
    ConfigPatchRequest,
    ConfigPatchResponse,
    ConfigSnapshotResponse,
    ErrorResponse,
    HealthEnvelopeResponse,
    HealthResponse,
    MemoryClearResponse,
    MemoryGraphResponse,
    MemoryRecordMutationResponse,
    MemoryRecordPatchRequest,
    MemorySnapshotResponse,
    RuntimeEnvelopePayload,
    RuntimeEnvelopeResponse,
    RuntimeStateResponse,
    RuntimeUsageResponse,
    UiProtocolSchemaEnvelopeResponse,
    UiProtocolSchemaResponse,
)
from gateway.serialization import make_json_safe
from gateway.routes import build_developer_router, build_endpoint_router, build_operator_router, build_runtime_router
from service_runtime.models import RuntimeError, RuntimeErrorCategory


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
        memory_clearer=None,
        memory_record_status_updater=None,
        memory_record_deleter=None,
        runtime_state_getter=None,
        runtime_usage_getter=None,
        runtime_debug_getter=None,
        health_getter=None,
        skill_list_getter=None,
        skill_getter=None,
        thread_title_generator=None,
        core_domain=None,
        endpoint_connection_prompt_getter=None,
        endpoint_connection_event_handler=None,
        access_token: str = "",
        cors_origins: list[str] | tuple[str, ...] | None = None,
    ):
        self._dependencies = GatewayDependencies(
            event_bus=event_bus,
            session_manager=session_manager,
            interaction_response_service=InteractionResponseService(event_bus),
            core_domain=core_domain,
            config_snapshot_getter=config_snapshot_getter,
            config_item_getter=config_item_getter,
            config_updater=config_updater,
            memory_snapshot_getter=memory_snapshot_getter,
            memory_graph_getter=memory_graph_getter,
            memory_clearer=memory_clearer,
            memory_record_status_updater=memory_record_status_updater,
            memory_record_deleter=memory_record_deleter,
            runtime_state_getter=runtime_state_getter,
            runtime_usage_getter=runtime_usage_getter,
            runtime_debug_getter=runtime_debug_getter,
            health_getter=health_getter,
            skill_list_getter=skill_list_getter,
            skill_getter=skill_getter,
        )
        self._event_bus = event_bus
        self._session_manager = session_manager
        self._interaction_responses = self._dependencies.interaction_response_service
        self._config_snapshot_getter = config_snapshot_getter
        self._config_item_getter = config_item_getter
        self._config_updater = config_updater
        self._memory_snapshot_getter = memory_snapshot_getter
        self._memory_graph_getter = memory_graph_getter
        self._memory_clearer = memory_clearer
        self._memory_record_status_updater = memory_record_status_updater
        self._memory_record_deleter = memory_record_deleter
        self._runtime_state_getter = runtime_state_getter
        self._runtime_usage_getter = runtime_usage_getter
        self._runtime_debug_getter = runtime_debug_getter
        self._health_getter = health_getter
        self._skill_list_getter = skill_list_getter
        self._skill_getter = skill_getter
        self._thread_title_generator = thread_title_generator
        self._endpoint_connection_prompt_getter = endpoint_connection_prompt_getter
        self._endpoint_connection_event_handler = endpoint_connection_event_handler
        self._access_token = str(access_token or "").strip()
        self._cors_origins = tuple(
            origin
            for origin in {
                str(item or "").strip()
                for item in (cors_origins or [])
            }
            if origin
        )
        self.endpoint_ws_manager = EndpointWebSocketManager()
        self.app = FastAPI(title="MeetYou Gateway")
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=list(self._cors_origins),
            allow_origin_regex=_LOOPBACK_ORIGIN_RE.pattern,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
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

    def _require_core_domain(self):
        if self._dependencies.core_domain is not None:
            return self._dependencies.core_domain
        self._raise_http_error(
            status_code=503,
            code="core_domain_unavailable",
            category=RuntimeErrorCategory.DEPENDENCY.value,
            message="Core domain services are not available",
        )

    async def publish_thread_delivery_event(self, thread_id: str, *, event_type: str, payload: dict) -> int:
        return await self.endpoint_ws_manager.publish_run_event(
            thread_id=thread_id,
            event={
                "type": str(event_type or ""),
                "thread_id": thread_id,
                "payload": dict(payload or {}),
                "durable": False,
            },
        )

    async def publish_endpoint_run_event(self, *, thread_id: str = "", run_id: str = "", event: dict) -> int:
        return await self.endpoint_ws_manager.publish_run_event(thread_id=thread_id, run_id=run_id, event=event)

    async def publish_endpoint_message(self, *, thread_id: str = "", message: dict) -> int:
        return await self.endpoint_ws_manager.publish_message(thread_id=thread_id, payload=message)

    async def publish_endpoint_operation_update(self, *, thread_id: str = "", operation_id: str = "", payload: dict) -> int:
        return await self.endpoint_ws_manager.publish_operation_update(thread_id=thread_id, operation_id=operation_id, payload=payload)

    async def dispatch_endpoint_call(self, *, endpoint_id: str, payload: dict) -> bool:
        return bool(await self.endpoint_ws_manager.send_to_endpoint(endpoint_id, payload))

    async def build_endpoint_connection_prompt(
        self,
        *,
        endpoint_id: str,
        endpoint_type: str,
        display_name: str,
        transport_profile: str,
        workspace_ids: list[str] | tuple[str, ...] | None = None,
    ) -> dict | None:
        getter = self._endpoint_connection_prompt_getter
        if getter is None:
            return None
        payload = await self._resolve(
            getter,
            endpoint_id=endpoint_id,
            endpoint_type=endpoint_type,
            display_name=display_name,
            transport_profile=transport_profile,
            workspace_ids=list(workspace_ids or []),
        )
        return dict(payload or {}) if isinstance(payload, dict) else None

    async def notify_endpoint_connected(
        self,
        *,
        endpoint_id: str,
        endpoint_type: str,
        display_name: str,
        transport_profile: str,
        workspace_ids: list[str] | tuple[str, ...] | None = None,
        connection_prompt: dict | None = None,
    ) -> None:
        handler = self._endpoint_connection_event_handler
        if handler is None:
            return
        await self._resolve(
            handler,
            endpoint_id=endpoint_id,
            endpoint_type=endpoint_type,
            display_name=display_name,
            transport_profile=transport_profile,
            workspace_ids=list(workspace_ids or []),
            connection_prompt=dict(connection_prompt or {}) if isinstance(connection_prompt, dict) else None,
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
        self.app.include_router(build_runtime_router(self))
        self.app.include_router(build_endpoint_router(self))
        self.app.include_router(build_operator_router(self))
        self.app.include_router(build_developer_router(self))

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

        @self.app.delete("/memory", response_model=MemoryClearResponse)
        async def clear_memory(request: Request):
            self._require_http_auth(request)
            payload = await self._resolve(self._memory_clearer)
            return MemoryClearResponse(**payload)

        @self.app.patch("/memory/records/{memory_id}", response_model=MemoryRecordMutationResponse)
        async def update_memory_record_status(memory_id: str, http_request: Request, request: MemoryRecordPatchRequest):
            self._require_http_auth(http_request)
            try:
                payload = await self._resolve(self._memory_record_status_updater, memory_id, request.status)
            except KeyError:
                self._raise_http_error(
                    status_code=404,
                    code="memory_record_not_found",
                    category=RuntimeErrorCategory.VALIDATION.value,
                    message="Memory record not found.",
                    details={"memory_id": memory_id},
                )
            except ValueError as exc:
                self._raise_http_error(
                    status_code=400,
                    code="memory_record_update_invalid",
                    category=RuntimeErrorCategory.VALIDATION.value,
                    message=str(exc),
                    details={"memory_id": memory_id, "status": request.status},
                )
            return MemoryRecordMutationResponse(**payload)

        @self.app.delete("/memory/records/{memory_id}", response_model=MemoryRecordMutationResponse)
        async def delete_memory_record(memory_id: str, request: Request):
            self._require_http_auth(request)
            try:
                payload = await self._resolve(self._memory_record_deleter, memory_id)
            except KeyError:
                self._raise_http_error(
                    status_code=404,
                    code="memory_record_not_found",
                    category=RuntimeErrorCategory.VALIDATION.value,
                    message="Memory record not found.",
                    details={"memory_id": memory_id},
                )
            except ValueError as exc:
                self._raise_http_error(
                    status_code=400,
                    code="memory_record_delete_invalid",
                    category=RuntimeErrorCategory.VALIDATION.value,
                    message=str(exc),
                    details={"memory_id": memory_id},
                )
            return MemoryRecordMutationResponse(**payload)

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
                    debug=make_json_safe(dict(payload or {})),
                ),
            )

    async def start(self, host: str = "127.0.0.1", port: int = 8000):
        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._server.serve())
        for _ in range(100):
            if bool(getattr(self._server, "started", False)):
                return
            if self._server_task.done():
                await self._server_task
                raise RuntimeError(f"Gateway stopped before becoming ready on {host}:{port}")
            await asyncio.sleep(0.05)
        raise RuntimeError(f"Gateway did not become ready on {host}:{port}")

    async def stop(self):
        if self._server:
            self._server.should_exit = True
        if self._server_task:
            self._server_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._server_task
