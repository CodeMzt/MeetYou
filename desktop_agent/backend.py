from __future__ import annotations

from desktop_agent.config import DesktopAgentConfig
from desktop_agent.desktop_api import DesktopApiServer
from desktop_agent.runtime import DesktopAgentRuntime


class DesktopAgentBackend:
    def __init__(self, config: DesktopAgentConfig):
        self.config = config
        self.runtime = DesktopAgentRuntime(config)
        self.api_server = DesktopApiServer(config) if config.local_bridge_enabled else None

    async def run(self) -> None:
        if self.api_server is not None:
            await self.api_server.start()
        try:
            await self.runtime.run()
        finally:
            if self.api_server is not None:
                await self.api_server.stop()
