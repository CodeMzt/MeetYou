from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone


logger = logging.getLogger("meetyou.gateway.client_ws")
_CLIENT_WS_SCHEMA = "meetyou.client.ws.v1"


class ClientWebSocketManager:
    def __init__(self):
        self._connections: dict[str, set] = {}
        self._connection_meta: dict[object, dict] = {}
        self._client_connections: dict[str, set] = {}
        self._session_connections: dict[str, set] = {}
        self._lock = asyncio.Lock()

    async def connect(self, thread_id: str, websocket) -> None:
        async with self._lock:
            self._connections.setdefault(thread_id, set()).add(websocket)
            now = datetime.now(timezone.utc).isoformat()
            self._connection_meta[websocket] = {
                "thread_id": thread_id,
                "client_id": "",
                "session_id": "",
                "workspace_id": "",
                "client_type": "",
                "display_name": "",
                "transport_profile": "",
                "available_tools": [],
                "executable_tools": [],
                "host": {},
                "connected_at": now,
                "updated_at": now,
            }

    def _drop_index(self, index: dict[str, set], key: str, websocket) -> None:
        if not key:
            return
        connections = index.get(key)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            index.pop(key, None)

    def _add_index(self, index: dict[str, set], key: str, websocket) -> None:
        if key:
            index.setdefault(key, set()).add(websocket)

    async def bind_connection(
        self,
        websocket,
        *,
        thread_id: str = "",
        client_id: str = "",
        session_id: str = "",
        workspace_id: str = "",
        client_type: str = "",
        display_name: str = "",
        transport_profile: str = "",
        available_tools: list | None = None,
        executable_tools: list | None = None,
        host: dict | None = None,
    ) -> None:
        normalized_client_id = str(client_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_thread_id = str(thread_id or "").strip()
        normalized_workspace_id = str(workspace_id or "").strip()
        async with self._lock:
            previous = dict(self._connection_meta.get(websocket) or {})
            if normalized_thread_id:
                old_thread_id = str(previous.get("thread_id") or "").strip()
                if old_thread_id and old_thread_id != normalized_thread_id:
                    self._drop_index(self._connections, old_thread_id, websocket)
                self._connections.setdefault(normalized_thread_id, set()).add(websocket)
            else:
                normalized_thread_id = str(previous.get("thread_id") or "").strip()

            self._drop_index(self._client_connections, str(previous.get("client_id") or "").strip(), websocket)
            self._drop_index(self._session_connections, str(previous.get("session_id") or "").strip(), websocket)
            self._add_index(self._client_connections, normalized_client_id, websocket)
            self._add_index(self._session_connections, normalized_session_id, websocket)

            now = datetime.now(timezone.utc).isoformat()
            self._connection_meta[websocket] = {
                **previous,
                "thread_id": normalized_thread_id,
                "client_id": normalized_client_id,
                "session_id": normalized_session_id,
                "workspace_id": normalized_workspace_id or str(previous.get("workspace_id") or "").strip(),
                "client_type": str(client_type or previous.get("client_type") or "").strip(),
                "display_name": str(display_name or previous.get("display_name") or "").strip(),
                "transport_profile": str(transport_profile or previous.get("transport_profile") or "").strip(),
                "available_tools": list(available_tools if available_tools is not None else previous.get("available_tools") or []),
                "executable_tools": list(executable_tools if executable_tools is not None else previous.get("executable_tools") or []),
                "host": dict(host if isinstance(host, dict) else previous.get("host") or {}),
                "connected_at": str(previous.get("connected_at") or now),
                "updated_at": now,
            }

    async def disconnect(self, thread_id: str, websocket) -> None:
        async with self._lock:
            connections = self._connections.get(thread_id)
            if connections:
                connections.discard(websocket)
                if not connections:
                    self._connections.pop(thread_id, None)
            metadata = self._connection_meta.pop(websocket, {})
            self._drop_index(self._client_connections, str(metadata.get("client_id") or "").strip(), websocket)
            self._drop_index(self._session_connections, str(metadata.get("session_id") or "").strip(), websocket)

    async def update_session_metadata(
        self,
        session_id: str,
        *,
        thread_id: str = "",
        client_id: str = "",
        workspace_id: str = "",
        client_type: str = "",
        display_name: str = "",
    ) -> int:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return 0
        async with self._lock:
            targets = [
                (websocket, dict(self._connection_meta.get(websocket) or {}))
                for websocket in self._session_connections.get(normalized_session_id, set())
            ]
        for websocket, previous in targets:
            await self.bind_connection(
                websocket,
                thread_id=thread_id or str(previous.get("thread_id") or "").strip(),
                client_id=client_id or str(previous.get("client_id") or "").strip(),
                session_id=normalized_session_id,
                workspace_id=workspace_id or str(previous.get("workspace_id") or "").strip(),
                client_type=client_type or str(previous.get("client_type") or "").strip(),
                display_name=display_name or str(previous.get("display_name") or "").strip(),
            )
        return len(targets)

    def has_connections(self, thread_id: str) -> bool:
        return bool(self._connections.get(thread_id, set()))

    async def connected_client_ids(self) -> set[str]:
        async with self._lock:
            return {
                str(client_id or "").strip()
                for client_id, connections in self._client_connections.items()
                if str(client_id or "").strip() and connections
            }

    async def snapshot(self, *, thread_id: str = "", client_id: str = "", session_id: str = "", workspace_id: str = "") -> list[dict]:
        normalized_thread_id = str(thread_id or "").strip()
        normalized_client_id = str(client_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_workspace_id = str(workspace_id or "").strip()
        async with self._lock:
            rows = [dict(item) for item in self._connection_meta.values()]
        result: list[dict] = []
        for item in rows:
            if normalized_thread_id and item.get("thread_id") != normalized_thread_id:
                continue
            if normalized_client_id and item.get("client_id") != normalized_client_id:
                continue
            if normalized_session_id and item.get("session_id") != normalized_session_id:
                continue
            if normalized_workspace_id and item.get("workspace_id") != normalized_workspace_id:
                continue
            if not str(item.get("client_id") or "").strip():
                continue
            result.append({**item, "connected": True})
        result.sort(key=lambda row: (str(row.get("client_id") or ""), str(row.get("session_id") or "")))
        return result

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
        async def _send(websocket) -> None:
            try:
                await websocket.send_json(frame)
            except Exception:
                logger.debug("Client WS send failed, removing websocket: thread=%s", thread_id)
                await self.disconnect(thread_id, websocket)
        if connections:
            await asyncio.gather(*(_send(websocket) for websocket in connections))

    async def send_to_client(
        self,
        client_id: str,
        frame: dict,
        *,
        thread_id: str = "",
        session_id: str = "",
        workspace_id: str = "",
    ) -> int:
        normalized_client_id = str(client_id or "").strip()
        if not normalized_client_id:
            return 0
        normalized_thread_id = str(thread_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_workspace_id = str(workspace_id or "").strip()
        async with self._lock:
            candidates = list(self._client_connections.get(normalized_client_id, set()))
            connections = []
            for websocket in candidates:
                metadata = dict(self._connection_meta.get(websocket) or {})
                if normalized_thread_id and str(metadata.get("thread_id") or "").strip() != normalized_thread_id:
                    continue
                if normalized_session_id and str(metadata.get("session_id") or "").strip() != normalized_session_id:
                    continue
                if normalized_workspace_id and str(metadata.get("workspace_id") or "").strip() != normalized_workspace_id:
                    continue
                connections.append((websocket, str(metadata.get("thread_id") or "").strip()))

        async def _send(websocket, connection_thread_id: str) -> bool:
            try:
                await websocket.send_json(frame)
                return True
            except Exception:
                logger.debug("Client WS targeted send failed, removing websocket: client=%s", normalized_client_id)
                await self.disconnect(connection_thread_id, websocket)
                return False

        if not connections:
            return 0
        results = await asyncio.gather(*(_send(websocket, connection_thread_id) for websocket, connection_thread_id in connections))
        return sum(1 for item in results if item)

    async def publish_client_event(
        self,
        client_id: str,
        *,
        event_type: str,
        payload: dict,
        thread_id: str = "",
        session_id: str = "",
        workspace_id: str = "",
    ) -> int:
        frame = {
            "schema": _CLIENT_WS_SCHEMA,
            "kind": "event",
            "event": {
                "type": event_type,
                **dict(payload or {}),
            },
        }
        return await self.send_to_client(
            client_id,
            frame,
            thread_id=thread_id,
            session_id=session_id,
            workspace_id=workspace_id,
        )

    async def send_client_tool_call(self, client_id: str, payload: dict) -> bool:
        return bool(await self.send_to_client(client_id, dict(payload or {})))

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
