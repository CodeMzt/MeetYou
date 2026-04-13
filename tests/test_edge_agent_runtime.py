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

        async def _fake_run_connection():
            await asyncio.sleep(0.2)

        runtime._run_connection = _fake_run_connection
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

    async def test_hello_ack_applies_heartbeat_interval_without_waiting_old_interval(self):
        config = EdgeAgentConfig(
            agent_id="edge-test-agent",
            workspace_ids=["home-lab"],
            heartbeat_interval_seconds=30,
        )
        runtime = EdgeAgentRuntime(config)

        class _FakeWs:
            def __init__(self):
                self.sent = []
                self.sent_event = asyncio.Event()

            async def send_json(self, payload):
                self.sent.append(payload)
                self.sent_event.set()

        ws = _FakeWs()
        heartbeat_task = asyncio.create_task(runtime._heartbeat_loop(ws))
        try:
            await asyncio.sleep(0.05)
            ready_received = await runtime._handle_server_message(
                {
                    "schema": "meetyou.agent.v1",
                    "type": "agent.hello.ack",
                    "payload": {"heartbeat_interval_seconds": 1},
                },
                False,
                ws,
            )
            self.assertFalse(ready_received)
            self.assertEqual(runtime._heartbeat_interval_seconds, 1)
            await asyncio.wait_for(ws.sent_event.wait(), timeout=3.5)
            self.assertEqual(ws.sent[-1]["type"], "agent.heartbeat")
        finally:
            heartbeat_task.cancel()
            with __import__("contextlib").suppress(asyncio.CancelledError):
                await heartbeat_task

    def test_main_usage_mentions_edge_agent(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            meetyou_main._print_usage()
        output = buffer.getvalue()
        self.assertIn("python main.py edge-agent", output)

    async def test_hello_ack_updates_heartbeat_interval_and_wakes_loop(self):
        runtime = EdgeAgentRuntime(
            EdgeAgentConfig(
                core_base_url="http://127.0.0.1:8000",
                agent_id="edge-test-agent",
                workspace_ids=["home-lab"],
            )
        )
        self.assertEqual(runtime._heartbeat_interval_seconds, 20)
        self.assertFalse(runtime._heartbeat_interval_updated.is_set())

        ready_received = await runtime._handle_server_message(
            {
                "schema": "meetyou.agent.v1",
                "type": "agent.hello.ack",
                "payload": {"heartbeat_interval_seconds": 7},
            },
            False,
            object(),
        )

        self.assertFalse(ready_received)
        self.assertEqual(runtime._heartbeat_interval_seconds, 7)
        self.assertTrue(runtime._heartbeat_interval_updated.is_set())


if __name__ == "__main__":
    unittest.main()
