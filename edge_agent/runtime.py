from __future__ import annotations

import asyncio
import logging

from edge_agent.config import EdgeAgentConfig
from edge_agent.protocol import build_pull_next

logger = logging.getLogger("meetyou.edge_agent")


class EdgeAgentRuntime:
    def __init__(self, config: EdgeAgentConfig):
        self.config = config
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        logger.info(
            "Edge Agent runtime skeleton started: agent_id=%s mqtt=%s",
            self.config.agent_id,
            self.config.mqtt_broker_url,
        )
        while not self._stop_event.is_set():
            envelope = build_pull_next(
                self.config.agent_id,
                workspace_ids=self.config.workspace_ids,
            )
            logger.debug("Edge Agent pull skeleton tick: %s", envelope)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=max(self.config.pull_interval_seconds, 1))
            except asyncio.TimeoutError:
                continue
