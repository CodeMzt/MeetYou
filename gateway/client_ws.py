from __future__ import annotations

import asyncio
import logging


logger = logging.getLogger("meetyou.gateway.client_ws")
_CLIENT_WS_SCHEMA = "meetyou.client.ws.v1"


class ClientWebSocketManager:
    def __init__(self):
        self._connections: dict[str, set] = {}
        self._lock = asyncio.Lock()

    async def connect(self, thread_id: str, websocket) -> None:
        async with self._lock:
            self._connections.setdefault(thread_id, set()).add(websocket)

    async def disconnect(self, thread_id: str, websocket) -> None:
        async with self._lock:
            connections = self._connections.get(thread_id)
            if not connections:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(thread_id, None)

    async def publish_event(self, thread_id: str, *, event_type: str, payload: dict) -> None:
        frame = {
            "schema": _CLIENT_WS_SCHEMA,
            "kind": "event",
            "event": {
                "type": event_type,
                **dict(payload or {}),
            },
        }
        async with self._lock:
            connections = list(self._connections.get(thread_id, set()))
        for websocket in connections:
            try:
                await websocket.send_json(frame)
            except Exception:
                logger.debug("Client WS send failed, removing websocket: thread=%s", thread_id)
                await self.disconnect(thread_id, websocket)

    @staticmethod
    def connection_payload(thread_id: str) -> dict:
        return {
            "schema": _CLIENT_WS_SCHEMA,
            "kind": "connection",
            "connection": {
                "thread_id": thread_id,
                "status": "connected",
            },
        }

    @staticmethod
    def pong_payload() -> dict:
        return {
            "schema": _CLIENT_WS_SCHEMA,
            "kind": "pong",
        }
