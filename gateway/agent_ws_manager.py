from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone


logger = logging.getLogger("meetyou.gateway.agent_ws")


class AgentConnectionManager:
    def __init__(self):
        self._connections: dict[str, object] = {}
        self._connected_at: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def connect(self, agent_id: str, websocket) -> None:
        async with self._lock:
            self._connections[agent_id] = websocket
            self._connected_at[agent_id] = datetime.now(timezone.utc).isoformat()

    async def disconnect(self, agent_id: str, websocket) -> bool:
        async with self._lock:
            current = self._connections.get(agent_id)
            if current is websocket:
                self._connections.pop(agent_id, None)
                self._connected_at.pop(agent_id, None)
                return True
            return False

    async def send_to_agent(self, agent_id: str, payload: dict) -> bool:
        async with self._lock:
            websocket = self._connections.get(agent_id)
        if websocket is None:
            return False
        try:
            await websocket.send_json(payload)
            return True
        except Exception:
            logger.debug("Failed to send payload to agent: %s", agent_id)
            await self.disconnect(agent_id, websocket)
            return False

    async def is_connected(self, agent_id: str) -> bool:
        async with self._lock:
            return agent_id in self._connections

    async def connected_agent_ids(self) -> set[str]:
        async with self._lock:
            return set(self._connections.keys())

    async def snapshot(self) -> list[dict]:
        async with self._lock:
            return [
                {
                    "agent_id": agent_id,
                    "connected": True,
                    "connected_at": self._connected_at.get(agent_id, ""),
                }
                for agent_id in sorted(self._connections.keys())
            ]
