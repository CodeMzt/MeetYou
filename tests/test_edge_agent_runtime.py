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
                core_base_url="http://127.0.0.1:9",
                agent_id="edge-test-agent",
                reconnect_delay_seconds=1,
            )
        )

        task = asyncio.create_task(runtime.run())
        await asyncio.sleep(0.05)
        runtime.stop()
        await asyncio.wait_for(task, timeout=2)

    async def test_runtime_handles_call_request_with_echo_handler(self):
        config = EdgeAgentConfig(agent_id="edge-test-agent", workspace_ids=["home-lab"])
        runtime = EdgeAgentRuntime(config)

        class _FakeWs:
            def __init__(self):
                self.sent = []

            async def send_json(self, payload):
                self.sent.append(payload)

        ws = _FakeWs()
        await runtime._handle_call_request(
            ws,
            {
                "schema": "meetyou.agent.v1",
                "type": "capability.call.request",
                "message_id": "dispatch-1",
                "payload": {
                    "call_id": "call-1",
                    "capability_id": f"agent.{config.agent_id}.utility.echo",
                    "arguments": {"text": "hello-edge"},
                },
            },
        )

        self.assertEqual([item["type"] for item in ws.sent], [
            "capability.call.accepted",
            "capability.call.progress",
            "capability.call.result",
        ])
        self.assertEqual(ws.sent[-1]["payload"]["result"]["echo"], "hello-edge")

    def test_main_usage_mentions_edge_agent(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            meetyou_main._print_usage()
        output = buffer.getvalue()
        self.assertIn("python main.py edge-agent", output)


if __name__ == "__main__":
    unittest.main()
