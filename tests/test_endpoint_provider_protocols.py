from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from desktop_client.config import DesktopClientConfig
from desktop_client.config import load_desktop_client_config
from desktop_client.mcp_runtime import DesktopClientMCPRuntime
from desktop_client.protocol import build_hello as build_desktop_hello
from desktop_client.protocol import build_tools_snapshot as build_desktop_tools_snapshot
from edge_client.config import EdgeClientConfig
from edge_client.config import load_edge_client_config
from edge_client.protocol import build_hello as build_edge_hello
from edge_client.protocol import build_tools_snapshot as build_edge_tools_snapshot


class EndpointProviderProtocolTests(unittest.TestCase):
    def test_desktop_provider_advertises_endpoint_identity_and_capabilities(self):
        config = DesktopClientConfig(provider_id="desktop-main", workspace_ids=["desktop-main"])

        hello = build_desktop_hello(config)
        snapshot = build_desktop_tools_snapshot(config)

        self.assertEqual(hello["schema"], "meetyou.endpoint.ws.v4")
        self.assertEqual(hello["type"], "endpoint.hello")
        self.assertEqual(hello["payload"]["provider"]["provider_type"], "desktop")
        self.assertEqual(hello["payload"]["endpoints"][0]["endpoint_id"], "desktop.desktop-main.ui")
        self.assertEqual(snapshot["type"], "endpoint.capabilities.snapshot")
        self.assertTrue(all(str(item["tool_id"]).startswith("endpoint.desktop.desktop-main.executor.") for item in snapshot["payload"]["capabilities"]))

    def test_edge_provider_uses_endpoint_schema(self):
        config = EdgeClientConfig(provider_id="edge-one", workspace_ids=["home-lab"], provider_type="edge")

        hello = build_edge_hello(config)
        snapshot = build_edge_tools_snapshot(config)

        self.assertEqual(hello["schema"], "meetyou.endpoint.ws.v4")
        self.assertEqual(hello["type"], "endpoint.hello")
        self.assertEqual(hello["payload"]["provider"]["provider_type"], "edge")
        self.assertEqual(hello["payload"]["endpoints"][0]["endpoint_id"], "edge.edge-one.executor")
        self.assertEqual(snapshot["endpoint_id"], "edge.edge-one.executor")
        self.assertEqual({item["tool_key"] for item in snapshot["payload"]["capabilities"]}, {"utility.echo", "math.add", "math.divide"})

    def test_desktop_local_mcp_capability_ids_use_executor_endpoint_prefix(self):
        manager = type(
            "_FakeMCPManager",
            (),
            {
                "mcp_tools": {
                    "filesystem": [
                        {
                            "function": {
                                "name": "read_file",
                                "description": "Read file",
                                "parameters": {"type": "object"},
                            }
                        }
                    ]
                }
            },
        )()
        runtime = DesktopClientMCPRuntime(
            DesktopClientConfig(provider_id="desktop-main", workspace_ids=["desktop-main"]),
            manager=manager,
        )

        runtime._rebuild_tool_map()  # noqa: SLF001
        tools = runtime.tool_definitions()

        self.assertEqual(len(tools), 1)
        self.assertEqual(
            tools[0]["tool_id"],
            "endpoint.desktop.desktop-main.executor.mcp.filesystem.read_file",
        )
        self.assertEqual(tools[0]["tool_key"], "mcp.filesystem.read_file")

    def test_desktop_process_env_overrides_repository_env_for_local_acceptance(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("MEETYOU_CORE_BASE_URL=https://remote.example\n", encoding="utf-8")
            config_path = root / "user" / "desktop_client.json"
            config_path.parent.mkdir()
            env = {
                "MEETYOU_CORE_BASE_URL": "http://127.0.0.1:8000",
                "MEETYOU_GATEWAY_ACCESS_TOKEN": "local-token",
            }

            with patch.dict("os.environ", env, clear=True):
                config = load_desktop_client_config(str(config_path))

        self.assertEqual(config.core_base_url, "http://127.0.0.1:8000")
        self.assertEqual(config.gateway_access_token, "local-token")

    def test_edge_process_env_overrides_repository_env_for_local_acceptance(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("MEETYOU_CORE_BASE_URL=https://remote.example\n", encoding="utf-8")
            config_path = root / "user" / "edge_client.json"
            config_path.parent.mkdir()

            with patch.dict("os.environ", {"MEETYOU_CORE_BASE_URL": "http://127.0.0.1:8000"}, clear=True):
                config = load_edge_client_config(str(config_path))

        self.assertEqual(config.core_base_url, "http://127.0.0.1:8000")


if __name__ == "__main__":
    unittest.main()
