"""
WebSocket 连接管理。
"""

import asyncio

from core.io_protocol import event_to_dict


class WebSocketManager:
    def __init__(self):
        self._connections: dict[str, set] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, websocket):
        async with self._lock:
            self._connections.setdefault(session_id, set()).add(websocket)

    async def disconnect(self, session_id: str, websocket):
        async with self._lock:
            connections = self._connections.get(session_id)
            if not connections:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(session_id, None)

    async def send_event(self, session_id: str, event):
        payload = self._serialize_event(event)
        async with self._lock:
            connections = list(self._connections.get(session_id, set()))
        for websocket in connections:
            await websocket.send_json(payload)

    async def broadcast_event(self, event):
        payload = self._serialize_event(event)
        async with self._lock:
            all_connections = [ws for conns in self._connections.values() for ws in conns]
        for websocket in all_connections:
            await websocket.send_json(payload)

    def _serialize_event(self, event):
        if isinstance(event, dict):
            return {
                "schema": "meetyou.ws.v1",
                "kind": "event",
                "event": dict(event),
            }
        payload = event_to_dict(event)
        return {
            "schema": "meetyou.ws.v1",
            "kind": "event",
            "event": payload,
            "stream": {
                "id": payload.get("stream_id", ""),
                "phase": payload.get("metadata", {}).get("stream_event", ""),
            },
            "confirm": payload.get("confirm", {}),
        }


class WebSocketOutputAdapter:
    def __init__(self, ws_manager: WebSocketManager):
        self._ws_manager = ws_manager

    async def send(self, event):
        if event.target.kind == "broadcast":
            await self._ws_manager.broadcast_event(event)
            return
        await self._ws_manager.send_event(event.session_id, event)
