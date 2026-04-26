import unittest
raise unittest.SkipTest("Legacy Edge Agent protocol tests were replaced by Edge Client protocol coverage.")

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

        self.assertEqual(len(capabilities), 3)
        self.assertEqual(hello["schema"], "meetyou.agent.v1")
        self.assertEqual(hello["type"], "agent.hello")
        self.assertEqual(hello["payload"]["transport_profile"], "edge_wss")
        self.assertEqual(hello["payload"]["protocol"]["schema"], "meetyou.agent.v1")
        self.assertEqual(hello["payload"]["protocol"]["version"], 1)
        self.assertIn("feature_negotiation", hello["payload"]["protocol"]["features"])
        self.assertIn("connection_prompt", hello["payload"]["protocol"]["features"])
        self.assertEqual(snapshot["type"], "agent.capabilities.snapshot")
        self.assertEqual(snapshot["payload"]["revision"], 2)
        self.assertEqual(capabilities[0]["capability_id"], "agent.edge-1.utility.echo")
        self.assertEqual(capabilities[1]["capability_id"], "agent.edge-1.math.add")
        self.assertEqual(capabilities[2]["capability_id"], "agent.edge-1.math.divide")
        self.assertEqual(capabilities[1]["abstract_capability_key"], "math.add")
        self.assertEqual(capabilities[1]["input_schema"]["required"], ["left", "right"])
        self.assertEqual(capabilities[2]["output_schema"]["required"], ["summary", "result", "operation"])
        self.assertEqual(snapshot["payload"]["capabilities"][0]["workspace_ids"], ["home-lab"])
        self.assertEqual(heartbeat["type"], "agent.heartbeat")
        self.assertEqual(heartbeat["payload"]["metrics"]["workspace_count"], 1)

    def test_build_hello_normalizes_macos_host_os(self):
        config = EdgeAgentConfig(
            agent_id="edge-1",
            display_name="Edge One",
            workspace_ids=["home-lab"],
        )
        with mock.patch("edge_agent.protocol.platform.system", return_value="Darwin"):
            hello = build_hello(config)
        self.assertEqual(hello["payload"]["host"]["os"], "macos")

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

    def test_load_edge_agent_config_reads_dotenv_without_gateway_fallback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "edge_agent.json"
            env_path = Path(tmp_dir) / ".env"
            config_path.write_text(json.dumps({"core_base_url": "http://127.0.0.1:8000"}), encoding="utf-8")
            env_path.write_text(
                "MEETYOU_GATEWAY_ACCESS_TOKEN=gateway-from-dotenv\nMEETYOU_EDGE_ACCESS_TOKEN=edge-from-dotenv\n",
                encoding="utf-8",
            )

            previous_cwd = Path.cwd()
            previous_edge = os.environ.get("MEETYOU_EDGE_ACCESS_TOKEN")
            previous_agent = os.environ.get("MEETYOU_AGENT_ACCESS_TOKEN")
            previous_gateway = os.environ.get("MEETYOU_GATEWAY_ACCESS_TOKEN")
            os.chdir(tmp_dir)
            os.environ.pop("MEETYOU_EDGE_ACCESS_TOKEN", None)
            os.environ.pop("MEETYOU_AGENT_ACCESS_TOKEN", None)
            os.environ.pop("MEETYOU_GATEWAY_ACCESS_TOKEN", None)
            try:
                config = load_edge_agent_config(str(config_path))
            finally:
                os.chdir(previous_cwd)
                if previous_edge is None:
                    os.environ.pop("MEETYOU_EDGE_ACCESS_TOKEN", None)
                else:
                    os.environ["MEETYOU_EDGE_ACCESS_TOKEN"] = previous_edge
                if previous_agent is None:
                    os.environ.pop("MEETYOU_AGENT_ACCESS_TOKEN", None)
                else:
                    os.environ["MEETYOU_AGENT_ACCESS_TOKEN"] = previous_agent
                if previous_gateway is None:
                    os.environ.pop("MEETYOU_GATEWAY_ACCESS_TOKEN", None)
                else:
                    os.environ["MEETYOU_GATEWAY_ACCESS_TOKEN"] = previous_gateway

        self.assertEqual(config.agent_access_token, "edge-from-dotenv")

    def test_load_edge_agent_config_prefers_agent_ws_env_over_legacy_env_and_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "edge_agent.json"
            config_path.write_text(
                json.dumps(
                    {
                        "core_base_url": "http://127.0.0.1:8000",
                        "agent_access_token": "edge-from-file",
                    }
                ),
                encoding="utf-8",
            )

            previous_cwd = Path.cwd()
            previous_ws = os.environ.get("MEETYOU_AGENT_WS_ACCESS_TOKEN")
            previous_agent = os.environ.get("MEETYOU_AGENT_ACCESS_TOKEN")
            previous_edge = os.environ.get("MEETYOU_EDGE_ACCESS_TOKEN")
            os.chdir(tmp_dir)
            os.environ.pop("MEETYOU_EDGE_ACCESS_TOKEN", None)
            os.environ["MEETYOU_AGENT_WS_ACCESS_TOKEN"] = "edge-from-ws-env"
            os.environ["MEETYOU_AGENT_ACCESS_TOKEN"] = "edge-from-legacy-env"
            try:
                config = load_edge_agent_config(str(config_path))
            finally:
                os.chdir(previous_cwd)
                if previous_ws is None:
                    os.environ.pop("MEETYOU_AGENT_WS_ACCESS_TOKEN", None)
                else:
                    os.environ["MEETYOU_AGENT_WS_ACCESS_TOKEN"] = previous_ws
                if previous_agent is None:
                    os.environ.pop("MEETYOU_AGENT_ACCESS_TOKEN", None)
                else:
                    os.environ["MEETYOU_AGENT_ACCESS_TOKEN"] = previous_agent
                if previous_edge is None:
                    os.environ.pop("MEETYOU_EDGE_ACCESS_TOKEN", None)
                else:
                    os.environ["MEETYOU_EDGE_ACCESS_TOKEN"] = previous_edge

        self.assertEqual(config.agent_access_token, "edge-from-ws-env")


if __name__ == "__main__":
    unittest.main()
