from __future__ import annotations

from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from gateway.endpoint_frame_handlers import (
    _invalidate_tool_router_cache,
    endpoint_frame as _frame,
    handle_endpoint_frame,
    send_endpoint_error as _send_error,
)


async def _handle_endpoint_frame(gateway, websocket: WebSocket, frame: dict[str, Any], state: dict[str, Any]) -> None:
    await handle_endpoint_frame(gateway, websocket, frame, state)


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
            if domain is not None:
                endpoint_ids = [
                    str(item or "").strip()
                    for item in (metadata.get("endpoint_ids") or state.get("endpoint_ids") or [metadata.get("endpoint_id")])
                    if str(item or "").strip()
                ]
                for endpoint_id in endpoint_ids:
                    _invalidate_tool_router_cache(domain, endpoint_id=endpoint_id)

    return router
