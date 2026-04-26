from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from core.app import App
from core.event_bus import EventBus
from core.io_protocol import InboundEvent, SourceKind, TargetKind
from core.session_manager import SessionManager
from core.io_protocol import make_source


class _PromptConfig:
    def __init__(self, start_prompt: str):
        self._start_prompt = start_prompt

    def get_prompt(self, prompt_name: str) -> str:
        if prompt_name in {"client_connected", "client_connection"}:
            return self._start_prompt
        if prompt_name == "start":
            return self._start_prompt
        raise AssertionError(prompt_name)


class ClientConnectionPromptTests(unittest.IsolatedAsyncioTestCase):
    def test_build_client_connection_prompt_includes_runtime_context(self):
        app = App.__new__(App)
        app.config = _PromptConfig("client connect prompt")

        payload = App.build_client_connection_prompt(
            app,
            client_id="desktop-main-client",
            client_type="desktop",
            display_name="Desktop Main Client",
            transport_profile="desktop_wss",
            workspace_ids=["personal", "desktop-main"],
        )

        self.assertEqual(payload["prompt_name"], "client_connected")
        self.assertEqual(payload["context"]["trigger"], "client_connected")
        self.assertEqual(payload["context"]["client_id"], "desktop-main-client")
        self.assertEqual(payload["context"]["workspace_ids"], ["personal", "desktop-main"])
        self.assertIn("client connect prompt", payload["prompt"])
        self.assertIn("desktop-main-client", payload["prompt"])
        self.assertIn("desktop_wss", payload["prompt"])

    async def test_inject_client_connection_event_enqueues_internal_message(self):
        app = App.__new__(App)
        app.config = _PromptConfig("client connect prompt")
        app.event_bus = EventBus()
        app.session_manager = SessionManager()
        app.session_manager.bind_runtime_session(
            make_source(SourceKind.WEB.value, "desktop-app", client_id="desktop-app"),
            session_id="client-session-1",
            metadata={
                "thread_id": "thr_recent",
                "workspace_id": "desktop-main",
                "client_id": "desktop-app",
            },
        )

        payload = await App.inject_client_connection_event(
            app,
            client_id="desktop-main-client",
            client_type="desktop",
            display_name="Desktop Main Client",
            transport_profile="desktop_wss",
            workspace_ids=["personal", "desktop-main"],
        )

        event = app.event_bus.inbound_queue.get_nowait()
        self.assertIsInstance(event, InboundEvent)
        self.assertEqual(event.session_id, "system:client:desktop-main-client")
        self.assertEqual(event.source.kind, SourceKind.SYSTEM.value)
        self.assertEqual(event.target.kind, TargetKind.INTERNAL.value)
        self.assertEqual(event.target.id, "desktop-main-client")
        self.assertEqual(event.metadata["trigger"], "client_connected")
        self.assertEqual(event.metadata["connection_prompt"]["prompt_name"], "client_connected")
        self.assertEqual(event.metadata["bridge_thread_id"], "thr_recent")
        self.assertIn("desktop-main-client", event.content)
        self.assertEqual(payload["prompt_name"], "client_connected")
        bridge_binding = app.session_manager.get_binding("system:client:desktop-main-client")
        self.assertIsNotNone(bridge_binding)
        self.assertEqual(bridge_binding.metadata["thread_id"], "thr_recent")
        self.assertEqual(bridge_binding.metadata["workspace_id"], "desktop-main")
        self.assertEqual(bridge_binding.metadata["bridged_session_id"], "client-session-1")

    def test_client_connection_event_resolves_as_transient_internal_reply(self):
        app = App.__new__(App)
        event = InboundEvent(
            session_id="system:client:desktop-main-client",
            type="message",
            role="user",
            content="hello",
            source=SimpleNamespace(kind=SourceKind.SYSTEM.value),
            target=SimpleNamespace(kind=TargetKind.INTERNAL.value, id="desktop-main-client"),
            metadata={"trigger": "client_connected", "transient": True, "client_id": "desktop-main-client"},
        )

        request = App._resolve_session_execution_request(app, event)

        self.assertIsNotNone(request)
        self.assertEqual(request.target.kind, TargetKind.INTERNAL.value)
        self.assertEqual(request.target.id, "desktop-main-client")
        self.assertTrue(request.is_boot)


class _SetupConfig:
    def get(self, key: str, default=None):
        values = {
            "tools_schema_path": "user/tools.json",
            "gateway_host": "127.0.0.1",
            "gateway_port": 8000,
            "gateway_access_token": "",
            "client_access_token": "",
            "gateway_cors_origins": [],
        }
        return values.get(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        if key == "enable_feishu_bot":
            return False
        return default

    def get_mcp_servers(self):
        return []

    def get_mcp_server_config_diagnostic(self):
        return {"message": "ok"}


class _FakeGateway:
    def __init__(self):
        self.output_adapter = object()
        self.agent_output_adapter = object()
        self.dispatch_agent_call = AsyncMock()
        self.start = AsyncMock()


class AppSetupGatewayPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_registers_agent_connection_prompt_getter_on_gateway(self):
        app = App.__new__(App)
        setup_runtime = AsyncMock()

        with patch("core.app.setup_app_runtime", setup_runtime):
            await App.setup(app)

        setup_runtime.assert_awaited_once_with(app)


if __name__ == "__main__":
    unittest.main()
