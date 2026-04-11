import asyncio
import io
import unittest
from contextlib import redirect_stdout

from edge_agent.config import EdgeAgentConfig
from edge_agent.runtime import EdgeAgentRuntime
import main as meetyou_main


class EdgeAgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_edge_agent_runtime_can_start_and_stop(self):
        runtime = EdgeAgentRuntime(
            EdgeAgentConfig(
                agent_id="edge-test-agent",
                pull_interval_seconds=1,
            )
        )

        task = asyncio.create_task(runtime.run())
        await asyncio.sleep(0.05)
        runtime.stop()
        await asyncio.wait_for(task, timeout=2)

    def test_main_usage_mentions_edge_agent(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            meetyou_main._print_usage()
        output = buffer.getvalue()
        self.assertIn("python main.py edge-agent", output)


if __name__ == "__main__":
    unittest.main()
