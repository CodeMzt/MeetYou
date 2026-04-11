import json
import tempfile
import unittest
from pathlib import Path

from edge_agent.config import load_edge_agent_config
from edge_agent.protocol import build_capability_call_lease, build_pull_empty, build_pull_next, topic_down, topic_pull, topic_up


class EdgeAgentProtocolTests(unittest.TestCase):
    def test_topic_builders(self):
        self.assertEqual(topic_up("edge-1"), "meetyou/agents/edge-1/up")
        self.assertEqual(topic_down("edge-1"), "meetyou/agents/edge-1/down")
        self.assertEqual(topic_pull("edge-1"), "meetyou/agents/edge-1/pull")

    def test_pull_and_lease_envelopes(self):
        pull = build_pull_next("edge-1", workspace_ids=["home-lab"], capabilities=["sensor.read"])
        empty = build_pull_empty("edge-1", correlation_id="corr-1", retry_after_seconds=15)
        lease = build_capability_call_lease(
            "edge-1",
            correlation_id="corr-2",
            operation_id="op_1",
            call_id="call_1",
            workspace_id="home-lab",
            capability_id="sensor.read",
            lease_seconds=30,
            arguments={"pin": 1},
        )

        self.assertEqual(pull["type"], "agent.pull.next")
        self.assertEqual(pull["payload"]["workspace_ids"], ["home-lab"])
        self.assertEqual(empty["type"], "agent.pull.empty")
        self.assertEqual(empty["payload"]["retry_after_seconds"], 15)
        self.assertEqual(lease["type"], "capability.call.lease")
        self.assertEqual(lease["payload"]["capability_id"], "sensor.read")

    def test_load_edge_agent_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "edge_agent.json"
            config_path.write_text(
                json.dumps(
                    {
                        "core_base_url": "http://127.0.0.1:8000",
                        "mqtt_broker_url": "mqtt://broker:1883",
                        "agent_id": "edge-k230",
                        "display_name": "K230 Edge",
                        "workspace_ids": ["home-lab", "study"],
                        "pull_interval_seconds": 5,
                    }
                ),
                encoding="utf-8",
            )

            config = load_edge_agent_config(str(config_path))
            self.assertEqual(config.agent_id, "edge-k230")
            self.assertEqual(config.workspace_ids, ["home-lab", "study"])
            self.assertEqual(config.pull_interval_seconds, 5)


if __name__ == "__main__":
    unittest.main()
