"""
WebSocket 连接管理。
"""

import asyncio
import logging

from core.io_protocol import event_to_dict

logger = logging.getLogger("meetyou.gateway.ws")
_WS_SCHEMA = "meetyou.ws.v1"


class WebSocketManager:
    def __init__(self, delivery_observer=None):
        self._connections: dict[str, set] = {}
        self._lock = asyncio.Lock()
        self._delivery_observer = delivery_observer

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
        async def _send(websocket):
            try:
                await websocket.send_json(payload)
                self._notify_delivery_observer(
                    success=True,
                    session_id=session_id,
                    delivery_mode="session",
                    event_type=str(payload.get("event", {}).get("type") or payload.get("runtime", {}).get("resource") or ""),
                    metadata=self._payload_metadata(payload),
                )
            except Exception:
                logger.debug("发送 WebSocket 事件失败，连接将被移除: session=%s", session_id)
                self._notify_delivery_observer(
                    success=False,
                    session_id=session_id,
                    delivery_mode="session",
                    event_type=str(payload.get("event", {}).get("type") or payload.get("runtime", {}).get("resource") or ""),
                    reason="websocket_send_failed",
                    metadata=self._payload_metadata(payload),
                )
                await self.disconnect(session_id, websocket)
        if connections:
            await asyncio.gather(*(_send(websocket) for websocket in connections))

    async def broadcast_event(self, event):
        payload = self._serialize_event(event)
        async with self._lock:
            snapshot = {
                session_id: list(connections)
                for session_id, connections in self._connections.items()
            }
        for session_id, connections in snapshot.items():
            for websocket in connections:
                try:
                    await websocket.send_json(payload)
                    self._notify_delivery_observer(
                        success=True,
                        session_id=session_id,
                        delivery_mode="broadcast",
                        event_type=str(payload.get("event", {}).get("type") or payload.get("runtime", {}).get("resource") or ""),
                        metadata=self._payload_metadata(payload),
                    )
                except Exception:
                    logger.debug("广播 WebSocket 事件失败，连接将被移除: session=%s", session_id)
                    self._notify_delivery_observer(
                        success=False,
                        session_id=session_id,
                        delivery_mode="broadcast",
                        event_type=str(payload.get("event", {}).get("type") or payload.get("runtime", {}).get("resource") or ""),
                        reason="websocket_broadcast_failed",
                        metadata=self._payload_metadata(payload),
                    )
                    await self.disconnect(session_id, websocket)

    def has_session(self, session_id: str) -> bool:
        return bool(self._connections.get(session_id, set()))

    def _serialize_event(self, event):
        if isinstance(event, dict):
            return {
                "schema": _WS_SCHEMA,
                "kind": "event",
                "event": dict(event),
            }
        payload = event_to_dict(event)
        if payload.get("type") == "runtime_status":
            return {
                "schema": _WS_SCHEMA,
                "kind": "runtime",
                "runtime": {
                    "resource": "state",
                    "session_id": payload.get("session_id", ""),
                    "state": payload.get("content", {}),
                    "metadata": payload.get("metadata", {}),
                    "event_id": payload.get("event_id", ""),
                },
            }
        if payload.get("type") == "usage":
            return {
                "schema": _WS_SCHEMA,
                "kind": "runtime",
                "runtime": {
                    "resource": "usage",
                    "session_id": payload.get("session_id", ""),
                    "usage": payload.get("content", {}),
                    "metadata": payload.get("metadata", {}),
                    "event_id": payload.get("event_id", ""),
                },
            }
        return {
            "schema": _WS_SCHEMA,
            "kind": "event",
            "event": payload,
            "stream": {
                "id": payload.get("stream_id", ""),
                "phase": payload.get("metadata", {}).get("stream_event", ""),
                "channel": payload.get("metadata", {}).get("stream_channel", ""),
            },
            "confirm": payload.get("confirm", {}),
            "input_request": payload.get("input_request", {}),
            "input_response": payload.get("input_response", {}),
        }

    @staticmethod
    def _payload_metadata(payload: dict) -> dict:
        if "event" in payload and isinstance(payload.get("event"), dict):
            return dict(payload["event"].get("metadata") or {})
        if "runtime" in payload and isinstance(payload.get("runtime"), dict):
            return dict(payload["runtime"].get("metadata") or {})
        return {}

    def _notify_delivery_observer(
        self,
        *,
        success: bool,
        session_id: str,
        delivery_mode: str,
        event_type: str = "",
        reason: str = "",
        metadata: dict | None = None,
    ) -> None:
        if self._delivery_observer is None:
            return
        try:
            self._delivery_observer(
                success=success,
                session_id=session_id,
                delivery_mode=delivery_mode,
                event_type=event_type,
                reason=reason,
                metadata=dict(metadata or {}),
            )
        except Exception:
            logger.debug("WebSocket delivery observer failed", exc_info=True)


class WebSocketOutputAdapter:
    def __init__(self, ws_manager: WebSocketManager):
        self._ws_manager = ws_manager

    async def send(self, event):
        if event.target.kind == "broadcast":
            await self._ws_manager.broadcast_event(event)
            return
        await self._ws_manager.send_event(event.session_id, event)


class AgentOutputAdapter:
    def __init__(self, agent_ws_manager, envelope_builder):
        self._agent_ws_manager = agent_ws_manager
        self._envelope_builder = envelope_builder

    async def send(self, event):
        agent_id = str(getattr(event.target, "id", "") or "").strip()
        if not agent_id:
            return
        payload = self._envelope_builder(
            agent_id=agent_id,
            session_id=event.session_id,
            content=event.content,
            role=event.role,
            event_type=event.type,
            stream_id=getattr(event, "stream_id", "") or "",
            metadata=dict(getattr(event, "metadata", {}) or {}),
        )
        await self._agent_ws_manager.send_to_agent(agent_id, payload)
