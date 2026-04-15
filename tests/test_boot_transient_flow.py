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
        if prompt_name in {"agent_connected", "agent_connection"}:
            return self._start_prompt
        if prompt_name == "start":
            return self._start_prompt
        raise AssertionError(prompt_name)


class AgentConnectionPromptTests(unittest.IsolatedAsyncioTestCase):
    def test_build_agent_connection_prompt_includes_runtime_context(self):
        app = App.__new__(App)
        app.config = _PromptConfig("agent connect prompt")

        payload = App.build_agent_connection_prompt(
            app,
            agent_id="desktop-main-agent",
            agent_type="desktop",
            display_name="Desktop Main Agent",
            transport_profile="desktop_wss",
            workspace_ids=["personal", "desktop-main"],
        )

        self.assertEqual(payload["prompt_name"], "agent_connected")
        self.assertEqual(payload["context"]["trigger"], "agent_connected")
        self.assertEqual(payload["context"]["agent_id"], "desktop-main-agent")
        self.assertEqual(payload["context"]["workspace_ids"], ["personal", "desktop-main"])
        self.assertIn("agent connect prompt", payload["prompt"])
        self.assertIn("desktop-main-agent", payload["prompt"])
        self.assertIn("desktop_wss", payload["prompt"])

    async def test_inject_agent_connection_event_enqueues_internal_message(self):
        app = App.__new__(App)
        app.config = _PromptConfig("agent connect prompt")
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

        payload = await App.inject_agent_connection_event(
            app,
            agent_id="desktop-main-agent",
            agent_type="desktop",
            display_name="Desktop Main Agent",
            transport_profile="desktop_wss",
            workspace_ids=["personal", "desktop-main"],
        )

        event = app.event_bus.inbound_queue.get_nowait()
        self.assertIsInstance(event, InboundEvent)
        self.assertEqual(event.session_id, "system:agent:desktop-main-agent")
        self.assertEqual(event.source.kind, SourceKind.SYSTEM.value)
        self.assertEqual(event.target.kind, TargetKind.INTERNAL.value)
        self.assertEqual(event.target.id, "desktop-main-agent")
        self.assertEqual(event.metadata["trigger"], "agent_connected")
        self.assertEqual(event.metadata["connection_prompt"]["prompt_name"], "agent_connected")
        self.assertEqual(event.metadata["bridge_thread_id"], "thr_recent")
        self.assertIn("desktop-main-agent", event.content)
        self.assertEqual(payload["prompt_name"], "agent_connected")
        bridge_binding = app.session_manager.get_binding("system:agent:desktop-main-agent")
        self.assertIsNotNone(bridge_binding)
        self.assertEqual(bridge_binding.metadata["thread_id"], "thr_recent")
        self.assertEqual(bridge_binding.metadata["workspace_id"], "desktop-main")
        self.assertEqual(bridge_binding.metadata["bridged_session_id"], "client-session-1")

    def test_agent_connection_event_resolves_as_transient_internal_reply(self):
        app = App.__new__(App)
        event = InboundEvent(
            session_id="system:agent:desktop-main-agent",
            type="message",
            role="user",
            content="hello",
            source=SimpleNamespace(kind=SourceKind.SYSTEM.value),
            target=SimpleNamespace(kind=TargetKind.INTERNAL.value, id="desktop-main-agent"),
            metadata={"trigger": "agent_connected", "transient": True, "agent_id": "desktop-main-agent"},
        )

        request = App._resolve_session_execution_request(app, event)

        self.assertIsNotNone(request)
        self.assertEqual(request.target.kind, TargetKind.INTERNAL.value)
        self.assertEqual(request.target.id, "desktop-main-agent")
        self.assertTrue(request.is_boot)


class _SetupConfig:
    def get(self, key: str, default=None):
        values = {
            "tools_schema_path": "user/tools.json",
            "gateway_host": "127.0.0.1",
            "gateway_port": 8000,
            "gateway_access_token": "",
            "agent_access_token": "",
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
        app.config = _SetupConfig()
        app.event_bus = EventBus()
        app.session_manager = SimpleNamespace()
        app.status_manager = SimpleNamespace(set_global=lambda *args, **kwargs: None)
        app.memory = SimpleNamespace(
            init_memory=AsyncMock(),
            set_store_backend=lambda *args, **kwargs: None,
            _store_layer=SimpleNamespace(empty_store=dict),
        )
        app.task_manager = SimpleNamespace(
            set_store_backend=lambda *args, **kwargs: None,
            _empty_store=dict,
        )
        app.tools_manager = SimpleNamespace(
            set_state_backends=lambda **kwargs: None,
            set_core_domain=lambda *args, **kwargs: None,
            set_agent_dispatcher=lambda dispatcher: None,
            init_tools=AsyncMock(),
        )
        app.mode_manager = SimpleNamespace(set_source_catalog_backend=lambda *args, **kwargs: None)
        app.heart = SimpleNamespace(
            init_heart=AsyncMock(),
            get_background_status=AsyncMock(),
            set_core_services=lambda services: None,
        )
        app.speaker = SimpleNamespace(register_adapter=lambda *args, **kwargs: None)
        app._health_getter = None
        app._telemetry_recorder = None

        gateway = _FakeGateway()
        agent_dispatch = SimpleNamespace(set_transport=lambda transport: None)
        core_domain = SimpleNamespace(
            engine=object(),
            session_factory=object(),
            services=SimpleNamespace(state_blob=object()),
            principal=SimpleNamespace(id="principal-1"),
            agent_dispatch=agent_dispatch,
        )

        with (
            patch("core.app.bootstrap_core_domain", return_value=core_domain),
            patch("core.app.FastAPIGateway", return_value=gateway) as gateway_cls,
            patch.object(App, "_sync_config_state_to_db", AsyncMock()),
            patch.object(App, "_refresh_brain_runtime", AsyncMock()),
        ):
            await App.setup(app)

        gateway.start.assert_awaited_once()
        prompt_getter = gateway_cls.call_args.kwargs["agent_connection_prompt_getter"]
        event_handler = gateway_cls.call_args.kwargs["agent_connection_event_handler"]
        self.assertIs(prompt_getter.__self__, app)
        self.assertIs(prompt_getter.__func__, App.build_agent_connection_prompt)
        self.assertIs(event_handler.__self__, app)
        self.assertIs(event_handler.__func__, App.inject_agent_connection_event)


if __name__ == "__main__":
    unittest.main()
