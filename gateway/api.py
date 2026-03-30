"""
FastAPI 网关。
"""

import asyncio
import contextlib
import inspect

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from core.io_protocol import (
    ConfirmResponseEvent,
    EventTarget,
    EventType,
    InboundEvent,
    SourceKind,
    TargetKind,
    make_source,
)
from gateway.models import (
    ConfigPatchRequest,
    ConfigPatchResponse,
    ConfigSnapshotResponse,
    ConfigEntryResponse,
    HealthResponse,
    InputAcceptedResponse,
    InputRequest,
    WebSocketCommand,
)
from gateway.ws_manager import WebSocketManager, WebSocketOutputAdapter


class FastAPIGateway:
    def __init__(
        self,
        event_bus,
        session_manager,
        config_snapshot_getter=None,
        config_item_getter=None,
        config_updater=None,
    ):
        self._event_bus = event_bus
        self._session_manager = session_manager
        self._config_snapshot_getter = config_snapshot_getter
        self._config_item_getter = config_item_getter
        self._config_updater = config_updater
        self.ws_manager = WebSocketManager()
        self.output_adapter = WebSocketOutputAdapter(self.ws_manager)
        self.app = FastAPI(title="MeetYou Gateway")
        
        # Add CORS middleware to allow frontend connection
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        self._server = None
        self._server_task = None
        self._setup_routes()

    async def _resolve(self, func, *args, **kwargs):
        if func is None:
            raise HTTPException(status_code=404, detail="配置服务未启用")
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _safe_send_json(self, websocket: WebSocket, payload: dict) -> bool:
        try:
            await websocket.send_json(payload)
            return True
        except WebSocketDisconnect:
            return False
        except Exception:
            return False

    def _setup_routes(self):
        @self.app.get("/health", response_model=HealthResponse)
        async def health():
            return HealthResponse()

        @self.app.post("/inputs", response_model=InputAcceptedResponse)
        async def post_inputs(request: InputRequest):
            source = make_source(SourceKind.WEB.value, request.source_id, **request.metadata)
            session_id = self._session_manager.get_or_create_session(source, request.session_id)
            event = InboundEvent(
                session_id=session_id,
                type=EventType.MESSAGE.value,
                role=request.role,
                content=request.content,
                source=source,
                target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                metadata=request.metadata,
            )
            await self._event_bus.inbound_queue.put(event)
            return InputAcceptedResponse(session_id=session_id, event_id=event.event_id)

        @self.app.get("/config", response_model=ConfigSnapshotResponse)
        async def get_config():
            items = await self._resolve(self._config_snapshot_getter)
            return ConfigSnapshotResponse(
                items={
                    key: ConfigEntryResponse(**value)
                    for key, value in items.items()
                }
            )

        @self.app.get("/config/{key}", response_model=ConfigEntryResponse)
        async def get_config_item(key: str):
            try:
                item = await self._resolve(self._config_item_getter, key)
            except Exception as e:
                raise HTTPException(status_code=404, detail=str(e)) from e
            return ConfigEntryResponse(**item)

        @self.app.patch("/config", response_model=ConfigPatchResponse)
        async def patch_config(request: ConfigPatchRequest):
            result = await self._resolve(self._config_updater, request.updates)
            return ConfigPatchResponse(**result)

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            source_id = websocket.query_params.get("source_id", "websocket")
            requested_session_id = websocket.query_params.get("session_id")
            source = make_source(SourceKind.WEB.value, source_id)
            session_id = self._session_manager.get_or_create_session(source, requested_session_id)
            await self.ws_manager.connect(session_id, websocket)
            connected = await self._safe_send_json(websocket, {
                "schema": "meetyou.ws.v1",
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
                        sent = await self._safe_send_json(websocket, {
                            "schema": "meetyou.ws.v1",
                            "kind": "error",
                            "error": {
                                "code": "invalid_payload",
                                "message": str(e),
                            },
                        })
                        if not sent:
                            break
                        continue
                    if command.action == "ping":
                        sent = await self._safe_send_json(websocket, {
                            "schema": "meetyou.ws.v1",
                            "kind": "pong",
                        })
                        if not sent:
                            break
                        continue
                    if command.action == "confirm_response":
                        if command.request_id is None or command.accepted is None:
                            sent = await self._safe_send_json(websocket, {
                                "schema": "meetyou.ws.v1",
                                "kind": "error",
                                "error": {
                                    "code": "invalid_confirm_response",
                                    "message": "request_id 和 accepted 为必填字段",
                                },
                            })
                            if not sent:
                                break
                            continue
                        await self._event_bus.inbound_queue.put(
                            ConfirmResponseEvent(
                                session_id=session_id,
                                type=EventType.CONFIRM_RESPONSE.value,
                                role="user",
                                content="confirm_response",
                                source=source,
                                target=EventTarget(kind=TargetKind.INTERNAL.value),
                                request_id=command.request_id,
                                accepted=command.accepted,
                                metadata=command.metadata,
                            )
                        )
                        sent = await self._safe_send_json(websocket, {
                            "schema": "meetyou.ws.v1",
                            "kind": "ack",
                            "ack": {
                                "action": command.action,
                                "request_id": command.request_id,
                            },
                        })
                        if not sent:
                            break
                        continue
                    sent = await self._safe_send_json(websocket, {
                        "schema": "meetyou.ws.v1",
                        "kind": "error",
                        "error": {
                            "code": "unsupported_action",
                            "message": f"不支持的 action: {command.action}",
                        },
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
