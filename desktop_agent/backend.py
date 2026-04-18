from __future__ import annotations

from desktop_agent.config import DesktopAgentConfig
from desktop_agent.runtime import DesktopAgentRuntime
from desktop_agent.ui_bridge import DesktopUiBridge


class DesktopAgentBackend:
    def __init__(self, config: DesktopAgentConfig):
        self.config = config
        self.runtime = DesktopAgentRuntime(config)
        self.ui_bridge = DesktopUiBridge(config) if config.local_bridge_enabled else None

    async def run(self) -> None:
        if self.ui_bridge is not None:
            await self.ui_bridge.start()
        try:
            await self.runtime.run()
        finally:
            if self.ui_bridge is not None:
                await self.ui_bridge.stop()
