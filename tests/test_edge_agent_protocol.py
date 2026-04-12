import json
import tempfile
import unittest
from pathlib import Path

from edge_agent.config import EdgeAgentConfig, load_edge_agent_config
from edge_agent.protocol import build_capabilities_snapshot, build_heartbeat, build_hello, build_static_capabilities


class EdgeAgentProtocolTests(unittest.TestCase):
    def test_protocol_builders_use_shared_agent_schema(self):
        config = EdgeAgentConfig(
            agent_id="edge-1",
            display_name="Edge One",
            workspace_ids=["home-lab"],
        )

        capabilities = build_static_capabilities(config)
        hello = build_hello(config)
        snapshot = build_capabilities_snapshot(config, revision=2)
        heartbeat = build_heartbeat(config, metrics={"workspace_count": 1})

        self.assertEqual(hello["schema"], "meetyou.agent.v1")
        self.assertEqual(hello["type"], "agent.hello")
        self.assertEqual(hello["payload"]["transport_profile"], "edge_wss")
        self.assertEqual(snapshot["type"], "agent.capabilities.snapshot")
        self.assertEqual(snapshot["payload"]["revision"], 2)
        self.assertEqual(capabilities[0]["capability_id"], "agent.edge-1.utility.echo")
        self.assertEqual(snapshot["payload"]["capabilities"][0]["workspace_ids"], ["home-lab"])
        self.assertEqual(heartbeat["type"], "agent.heartbeat")
        self.assertEqual(heartbeat["payload"]["metrics"]["workspace_count"], 1)

    def test_load_edge_agent_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "edge_agent.json"
            config_path.write_text(
                json.dumps(
                    {
                        "core_base_url": "http://127.0.0.1:8000",
                        "agent_id": "edge-k230",
                        "display_name": "K230 Edge",
                        "workspace_ids": ["home-lab", "study"],
                        "heartbeat_interval_seconds": 5,
                        "transport_profile": "edge_wss",
                    }
                ),
                encoding="utf-8",
            )

            config = load_edge_agent_config(str(config_path))
            self.assertEqual(config.agent_id, "edge-k230")
            self.assertEqual(config.workspace_ids, ["home-lab", "study"])
            self.assertEqual(config.heartbeat_interval_seconds, 5)
            self.assertEqual(config.websocket_url, "ws://127.0.0.1:8000/agent/ws")


if __name__ == "__main__":
    unittest.main()
