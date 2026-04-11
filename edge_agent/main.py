from __future__ import annotations

from edge_agent.config import load_edge_agent_config
from edge_agent.runtime import EdgeAgentRuntime


async def run_edge_agent() -> None:
    config = load_edge_agent_config()
    runtime = EdgeAgentRuntime(config)
    await runtime.run()
