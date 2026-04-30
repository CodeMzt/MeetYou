from __future__ import annotations

import asyncio
import contextlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from desktop_client.backend import DesktopClientBackend
from desktop_client.config import DesktopClientConfig
from desktop_client.core_client import DesktopCoreClient
from desktop_client.desktop_api import DESKTOP_WS_PATH, LOCAL_BRIDGE_STATUS_PATH, _desktop_routes


class DesktopEndpointBridgeTests(unittest.TestCase):
    def test_local_desktop_ws_bridges_to_endpoint_ws(self):
        config = DesktopClientConfig(
            core_base_url="https://core.example.test",
            gateway_access_token="core-token",
            local_bridge_access_token="local-token",
        )
        request = SimpleNamespace(rel_url=SimpleNamespace(query_string="thread_id=thr_1&access_token=local-token"))
        core_client = DesktopCoreClient(config)

        url = core_client._build_core_ws_url(request, local_access_token="local-token")

        self.assertEqual(url, "wss://core.example.test/endpoint/ws?thread_id=thr_1")

    def test_core_http_url_merges_route_defaults_with_request_query(self):
        config = DesktopClientConfig(core_base_url="https://core.example.test")
        core_client = DesktopCoreClient(config)

        url = core_client._build_core_http_url(
            "/runtime/workspaces/personal/endpoints?include_tools=true",
            "include_tools=true&status=online",
        )

        self.assertEqual(
            url,
            "https://core.example.test/runtime/workspaces/personal/endpoints?include_tools=true&status=online",
        )

    def test_desktop_local_surface_keeps_ui_paths_stable(self):
        self.assertEqual(LOCAL_BRIDGE_STATUS_PATH, "/desktop/status")
        self.assertEqual(DESKTOP_WS_PATH, "/desktop/ws")

    def test_desktop_skills_route_proxies_to_operator_skills(self):
        route = next(item for item in _desktop_routes() if item.desktop_path == "/desktop/skills")
        request = SimpleNamespace(query_string="skill_type=reusable&query=task")

        self.assertEqual(
            route.core_path_builder(request),
            "/operator/skills?skill_type=reusable&query=task",
        )


class DesktopEndpointBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_backend_starts_endpoint_runtime_when_local_bridge_is_enabled(self):
        events: list[str] = []

        class _FakeRuntime:
            def __init__(self, config):
                self.config = config
                self.stopped = False

            async def run(self):
                events.append("runtime.run")
                while not self.stopped:
                    await asyncio.sleep(0.01)

            def stop(self):
                self.stopped = True
                events.append("runtime.stop")

        class _FakeApiServer:
            def __init__(self, config, on_endpoint_session_created=None):
                self.config = config
                self.on_endpoint_session_created = on_endpoint_session_created

            async def start(self):
                events.append("api.start")

            async def stop(self):
                events.append("api.stop")

        with patch("desktop_client.backend.DesktopClientRuntime", _FakeRuntime), patch(
            "desktop_client.backend.DesktopApiServer",
            _FakeApiServer,
        ):
            backend = DesktopClientBackend(DesktopClientConfig(local_bridge_enabled=True))
            task = asyncio.create_task(backend.run())
            for _ in range(20):
                if "runtime.run" in events:
                    break
                await asyncio.sleep(0.01)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self.assertEqual(events[0], "api.start")
        self.assertIn("runtime.run", events)
        self.assertIn("runtime.stop", events)
        self.assertEqual(events[-1], "api.stop")


if __name__ == "__main__":
    unittest.main()
