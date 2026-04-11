from __future__ import annotations

import asyncio

from desktop_agent.config import load_desktop_agent_config
from desktop_agent.runtime import DesktopAgentRuntime


async def run_desktop_agent() -> None:
    config = load_desktop_agent_config()
    runtime = DesktopAgentRuntime(config)
    await runtime.run()
