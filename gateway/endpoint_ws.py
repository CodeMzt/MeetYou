from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger("meetyou.gateway.endpoint_ws")
ENDPOINT_WS_SCHEMA = "meetyou.endpoint.ws.v4"


class EndpointWebSocketManager:
    def __init__(self):
        self._connections: dict[str, set] = {}
        self._connection_meta: dict[object, dict] = {}
        self._subscriptions: dict[tuple[str, str], set] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            self._connection_meta[websocket] = {
                "endpoint_id": "",
                "connection_id": "",
                "provider": {},
                "subscriptions": [],
                "connected_at": now,
                "updated_at": now,
            }

    async def bind_endpoint(
        self,
        websocket,
        *,
        endpoint_id: str,
        connection_id: str,
        provider: dict | None = None,
        metadata: dict | None = None,
    ) -> None:
        normalized_endpoint_id = str(endpoint_id or "").strip()
        metadata_payload = dict(metadata or {})
        endpoint_ids: list[str] = []
        for candidate in [normalized_endpoint_id, *(metadata_payload.get("endpoint_ids") or metadata_payload.get("registered_endpoints") or [])]:
            value = str(candidate or "").strip()
            if value and value not in endpoint_ids:
                endpoint_ids.append(value)
        async with self._lock:
            previous = dict(self._connection_meta.get(websocket) or {})
            previous_endpoint_ids = [
                str(item or "").strip()
                for item in (previous.get("endpoint_ids") or [previous.get("endpoint_id")])
                if str(item or "").strip()
            ]
            for previous_endpoint_id in previous_endpoint_ids:
                if previous_endpoint_id in endpoint_ids:
                    continue
                connections = self._connections.get(previous_endpoint_id)
                if connections:
                    connections.discard(websocket)
                    if not connections:
                        self._connections.pop(previous_endpoint_id, None)
            for bound_endpoint_id in endpoint_ids:
                self._connections.setdefault(bound_endpoint_id, set()).add(websocket)
            now = datetime.now(timezone.utc).isoformat()
            self._connection_meta[websocket] = {
                **previous,
                "endpoint_id": normalized_endpoint_id,
                "endpoint_ids": endpoint_ids,
                "connection_id": str(connection_id or previous.get("connection_id") or "").strip(),
                "provider": dict(provider or previous.get("provider") or {}),
                "metadata": metadata_payload or dict(previous.get("metadata") or {}),
                "updated_at": now,
            }

    async def disconnect(self, websocket) -> dict:
        async with self._lock:
            metadata = self._connection_meta.pop(websocket, {})
            endpoint_ids = [
                str(item or "").strip()
                for item in (metadata.get("endpoint_ids") or [metadata.get("endpoint_id")])
                if str(item or "").strip()
            ]
            for endpoint_id in endpoint_ids:
                connections = self._connections.get(endpoint_id)
                if connections:
                    connections.discard(websocket)
                    if not connections:
                        self._connections.pop(endpoint_id, None)
            for key, sockets in list(self._subscriptions.items()):
                sockets.discard(websocket)
                if not sockets:
                    self._subscriptions.pop(key, None)
            return metadata

    async def subscribe(self, websocket, *, target_type: str, target_id: str, subscription_id: str = "") -> None:
        normalized_target_type = str(target_type or "").strip()
        normalized_target_id = str(target_id or "").strip()
        normalized_subscription_id = str(subscription_id or "").strip()
        if not normalized_target_type or not normalized_target_id:
            return
        async with self._lock:
            self._subscriptions.setdefault((normalized_target_type, normalized_target_id), set()).add(websocket)
            metadata = dict(self._connection_meta.get(websocket) or {})
            subscriptions = []
            for item in list(metadata.get("subscriptions") or []):
                if self._subscription_matches(
                    item,
                    subscription_id=normalized_subscription_id,
                    target_type=normalized_target_type,
                    target_id=normalized_target_id,
                ):
                    key = (
                        str((item or {}).get("target_type") or "").strip(),
                        str((item or {}).get("target_id") or "").strip(),
                    )
                    sockets = self._subscriptions.get(key)
                    if sockets and key != (normalized_target_type, normalized_target_id):
                        sockets.discard(websocket)
                        if not sockets:
                            self._subscriptions.pop(key, None)
                    continue
                subscriptions.append(item)
            subscriptions.append(
                {
                    "subscription_id": normalized_subscription_id,
                    "target_type": normalized_target_type,
                    "target_id": normalized_target_id,
                }
            )
            metadata["subscriptions"] = subscriptions
            metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._connection_meta[websocket] = metadata

    async def update_subscription(self, websocket, *, target_type: str, target_id: str, subscription_id: str = "") -> None:
        await self.unsubscribe(
            websocket,
            target_type="" if subscription_id else target_type,
            target_id="" if subscription_id else target_id,
            subscription_id=subscription_id,
        )
        await self.subscribe(
            websocket,
            target_type=target_type,
            target_id=target_id,
            subscription_id=subscription_id,
        )

    async def unsubscribe(self, websocket, *, target_type: str = "", target_id: str = "", subscription_id: str = "") -> int:
        removed = 0
        normalized_target_type = str(target_type or "").strip()
        normalized_target_id = str(target_id or "").strip()
        normalized_subscription_id = str(subscription_id or "").strip()
        async with self._lock:
            metadata = dict(self._connection_meta.get(websocket) or {})
            subscriptions = list(metadata.get("subscriptions") or [])
            kept = []
            for item in subscriptions:
                if self._subscription_matches(
                    item,
                    subscription_id=normalized_subscription_id,
                    target_type=normalized_target_type,
                    target_id=normalized_target_id,
                ):
                    key = (
                        str((item or {}).get("target_type") or "").strip(),
                        str((item or {}).get("target_id") or "").strip(),
                    )
                    sockets = self._subscriptions.get(key)
                    if sockets:
                        sockets.discard(websocket)
                        if not sockets:
                            self._subscriptions.pop(key, None)
                    removed += 1
                    continue
                kept.append(item)
            metadata["subscriptions"] = kept
            metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._connection_meta[websocket] = metadata
        return removed

    @staticmethod
    def _subscription_matches(item: dict, *, subscription_id: str = "", target_type: str = "", target_id: str = "") -> bool:
        item_subscription_id = str((item or {}).get("subscription_id") or "").strip()
        item_target_type = str((item or {}).get("target_type") or "").strip()
        item_target_id = str((item or {}).get("target_id") or "").strip()
        if subscription_id and item_subscription_id == subscription_id:
            return True
        if target_type and target_id and item_target_type == target_type and item_target_id == target_id:
            return True
        return False

    def has_subscription(self, *, target_type: str, target_id: str) -> bool:
        key = (str(target_type or "").strip(), str(target_id or "").strip())
        return bool(self._subscriptions.get(key))

    async def send_to_endpoint(self, endpoint_id: str, frame: dict[str, Any]) -> int:
        normalized_endpoint_id = str(endpoint_id or "").strip()
        if not normalized_endpoint_id:
            return 0
        async with self._lock:
            targets = list(self._connections.get(normalized_endpoint_id, set()))
        return await self._send_many(targets, frame)

    async def connected_endpoint_ids(self) -> set[str]:
        async with self._lock:
            return {endpoint_id for endpoint_id, sockets in self._connections.items() if sockets}

    def connected_endpoint_ids_now(self) -> set[str]:
        return {endpoint_id for endpoint_id, sockets in self._connections.items() if sockets}

    async def snapshot(self, *, endpoint_id: str = "") -> list[dict[str, Any]]:
        normalized_endpoint_id = str(endpoint_id or "").strip()
        async with self._lock:
            rows: list[dict[str, Any]] = []
            for websocket, metadata in self._connection_meta.items():
                row = dict(metadata or {})
                row_endpoint_id = str(row.get("endpoint_id") or "").strip()
                row_endpoint_ids = [
                    str(item or "").strip()
                    for item in (row.get("endpoint_ids") or [row_endpoint_id])
                    if str(item or "").strip()
                ]
                if normalized_endpoint_id and normalized_endpoint_id not in row_endpoint_ids:
                    continue
                row["connected"] = any(
                    endpoint_id and websocket in self._connections.get(endpoint_id, set())
                    for endpoint_id in (row_endpoint_ids or [row_endpoint_id])
                )
                if normalized_endpoint_id:
                    row["endpoint_id"] = normalized_endpoint_id
                    rows.append(row)
                else:
                    for endpoint_id in (row_endpoint_ids or [row_endpoint_id]):
                        if not endpoint_id:
                            continue
                        endpoint_row = dict(row)
                        endpoint_row["endpoint_id"] = endpoint_id
                        endpoint_row["connected"] = bool(websocket in self._connections.get(endpoint_id, set()))
                        rows.append(endpoint_row)
            return rows

    async def publish_subscription(self, *, target_type: str, target_id: str, frame: dict[str, Any]) -> int:
        key = (str(target_type or "").strip(), str(target_id or "").strip())
        async with self._lock:
            targets = list(self._subscriptions.get(key, set()))
        return await self._send_many(targets, frame)

    async def publish_run_event(self, *, thread_id: str = "", run_id: str = "", event: dict[str, Any]) -> int:
        frame = {
            "schema": ENDPOINT_WS_SCHEMA,
            "type": "delivery.run_event",
            "payload": dict(event or {}),
        }
        delivered = 0
        if thread_id:
            delivered += await self.publish_subscription(target_type="thread", target_id=thread_id, frame=frame)
        if run_id:
            delivered += await self.publish_subscription(target_type="run", target_id=run_id, frame=frame)
        return delivered

    async def publish_message(self, *, thread_id: str = "", payload: dict[str, Any]) -> int:
        frame = {
            "schema": ENDPOINT_WS_SCHEMA,
            "type": "delivery.message",
            "payload": dict(payload or {}),
        }
        if not thread_id:
            thread_id = str((payload or {}).get("thread_id") or "").strip()
        if not thread_id:
            return 0
        return await self.publish_subscription(target_type="thread", target_id=thread_id, frame=frame)

    async def publish_notice(self, *, target_endpoint_id: str, payload: dict[str, Any]) -> int:
        frame = {
            "schema": ENDPOINT_WS_SCHEMA,
            "type": "delivery.notice",
            "endpoint_id": str(target_endpoint_id or "").strip(),
            "payload": dict(payload or {}),
        }
        return await self.send_to_endpoint(target_endpoint_id, frame)

    async def publish_operation_update(self, *, thread_id: str = "", operation_id: str = "", payload: dict[str, Any]) -> int:
        frame = {
            "schema": ENDPOINT_WS_SCHEMA,
            "type": "delivery.operation_update",
            "payload": dict(payload or {}),
        }
        delivered = 0
        if thread_id:
            delivered += await self.publish_subscription(target_type="thread", target_id=thread_id, frame=frame)
        if operation_id:
            delivered += await self.publish_subscription(target_type="operation", target_id=operation_id, frame=frame)
        return delivered

    async def publish_inbox_item(self, *, target_endpoint_id: str = "", thread_id: str = "", payload: dict[str, Any]) -> int:
        frame = {
            "schema": ENDPOINT_WS_SCHEMA,
            "type": "delivery.inbox_item",
            "endpoint_id": str(target_endpoint_id or "").strip(),
            "payload": dict(payload or {}),
        }
        if target_endpoint_id:
            return await self.send_to_endpoint(target_endpoint_id, frame)
        if thread_id:
            return await self.publish_subscription(target_type="thread", target_id=thread_id, frame=frame)
        return 0

    async def _send_many(self, targets: list, frame: dict[str, Any]) -> int:
        async def _send(websocket) -> bool:
            try:
                await websocket.send_json(frame)
                return True
            except Exception:
                logger.debug("Endpoint WS send failed, removing websocket")
                await self.disconnect(websocket)
                return False

        if not targets:
            return 0
        results = await asyncio.gather(*(_send(websocket) for websocket in targets))
        return sum(1 for item in results if item)
