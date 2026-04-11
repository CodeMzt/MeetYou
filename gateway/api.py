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
from gateway.client_ws import ClientWebSocketManager
from gateway.agent_ws_manager import AgentConnectionManager
from gateway.dependencies import GatewayDependencies
from gateway.models import (
    ConfigEntryResponse,
    ConfigPatchRequest,
    ConfigPatchResponse,
    ConfigSnapshotResponse,
    ErrorResponse,
    HealthEnvelopeResponse,
    HealthResponse,
    MemoryGraphResponse,
    MemorySnapshotResponse,
    RuntimeEnvelopePayload,
    RuntimeEnvelopeResponse,
    RuntimeStateResponse,
    RuntimeUsageResponse,
    UiProtocolSchemaEnvelopeResponse,
    UiProtocolSchemaResponse,
)
from gateway.routes import build_agent_router, build_client_router, build_developer_router, build_operator_router
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
        core_domain=None,
        agent_access_token: str = "",
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
            runtime_state_getter=runtime_state_getter,
            runtime_usage_getter=runtime_usage_getter,
            runtime_debug_getter=runtime_debug_getter,
            health_getter=health_getter,
        )
        self._event_bus = event_bus
        self._session_manager = session_manager
        self._interaction_responses = self._dependencies.interaction_response_service
        self._config_snapshot_getter = config_snapshot_getter
        self._config_item_getter = config_item_getter
        self._config_updater = config_updater
        self._memory_snapshot_getter = memory_snapshot_getter
        self._memory_graph_getter = memory_graph_getter
        self._runtime_state_getter = runtime_state_getter
        self._runtime_usage_getter = runtime_usage_getter
        self._runtime_debug_getter = runtime_debug_getter
        self._health_getter = health_getter
        self._agent_access_token = str(agent_access_token or "").strip() or str(access_token or "").strip()
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
        self.client_ws_manager = ClientWebSocketManager()
        self.agent_ws_manager = AgentConnectionManager()
        self.output_adapter = WebSocketOutputAdapter(self.ws_manager)
        self.app = FastAPI(title="MeetYou Gateway")
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=list(self._cors_origins),
            allow_origin_regex=_LOOPBACK_ORIGIN_RE.pattern,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "PUT"],
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

    async def publish_client_thread_event(self, thread_id: str, *, event_type: str, payload: dict) -> None:
        await self.client_ws_manager.publish_event(thread_id, event_type=event_type, payload=payload)

    async def dispatch_agent_call(self, *, agent_id: str, payload: dict) -> bool:
        return await self.agent_ws_manager.send_to_agent(agent_id, payload)

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

    def _require_agent_http_auth(self, request: Request) -> None:
        if not self._agent_access_token:
            return
        access_token = self._resolve_http_access_token(request)
        if access_token == self._agent_access_token:
            return
        self._raise_http_error(
            status_code=401,
            code="unauthorized",
            category=RuntimeErrorCategory.RUNTIME.value,
            message="缺少有效 agent 访问令牌",
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

    async def _authorize_agent_websocket(self, websocket: WebSocket) -> bool:
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
        if not self._agent_access_token:
            return True
        access_token = self._resolve_ws_access_token(websocket)
        if access_token == self._agent_access_token:
            return True
        await self._send_ws_error_and_close(
            websocket,
            code="unauthorized",
            category=RuntimeErrorCategory.RUNTIME.value,
            message="缺少有效 agent 访问令牌",
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
        self.app.include_router(build_agent_router(self))
        self.app.include_router(build_client_router(self))
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
            await self._send_ws_error_and_close(
                websocket,
                code="legacy_websocket_path_removed",
                category=RuntimeErrorCategory.VALIDATION.value,
                message="根路径 /ws 已停止承载聊天流，请改用 /client/ws。",
                details={
                    "legacy_path": "/ws",
                    "replacement_path": "/client/ws",
                    "required_query": ["thread_id"],
                },
                close_code=4404,
            )

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
