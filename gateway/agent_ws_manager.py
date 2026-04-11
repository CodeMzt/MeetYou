from __future__ import annotations

import asyncio
import logging


logger = logging.getLogger("meetyou.gateway.agent_ws")


class AgentConnectionManager:
    def __init__(self):
        self._connections: dict[str, object] = {}
        self._lock = asyncio.Lock()

    async def connect(self, agent_id: str, websocket) -> None:
        async with self._lock:
            self._connections[agent_id] = websocket

    async def disconnect(self, agent_id: str, websocket) -> None:
        async with self._lock:
            current = self._connections.get(agent_id)
            if current is websocket:
                self._connections.pop(agent_id, None)

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
            return False

    async def is_connected(self, agent_id: str) -> bool:
        async with self._lock:
            return agent_id in self._connections
