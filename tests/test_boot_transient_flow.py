import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from core.app import App
from core.event_bus import EventBus
from core.io_protocol import EventType, SourceKind, TargetKind, make_source


class BootTransientFlowTests(unittest.TestCase):
    def test_build_boot_event_marks_boot_turn_as_transient(self):
        event = App._build_boot_event(
            "start prompt",
            make_source(SourceKind.SYSTEM.value, "boot"),
        )

        self.assertEqual(event.session_id, "system:boot")
        self.assertEqual(event.type, EventType.MESSAGE.value)
        self.assertEqual(event.role, "user")
        self.assertEqual(event.target.kind, TargetKind.BROADCAST.value)
        self.assertTrue(event.metadata["transient"])
        self.assertTrue(event.metadata["boot_event"])


class _PromptConfig:
    def __init__(self, start_prompt: str):
        self._start_prompt = start_prompt

    def get_prompt(self, prompt_name: str) -> str:
        if prompt_name != "start":
            raise AssertionError(prompt_name)
        return self._start_prompt


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
        self.dispatch_agent_call = AsyncMock()
        self.start = AsyncMock()


class BootStartupInjectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_inject_core_startup_boot_event_enqueues_transient_boot_message(self):
        app = App.__new__(App)
        app.config = _PromptConfig("start prompt")
        app.event_bus = EventBus()

        await App._inject_core_startup_boot_event(app)

        event = await asyncio.wait_for(app.event_bus.inbound_queue.get(), timeout=0.1)
        self.assertEqual(event.session_id, "system:boot")
        self.assertEqual(event.type, EventType.MESSAGE.value)
        self.assertEqual(event.role, "user")
        self.assertEqual(event.content, "start prompt")
        self.assertEqual(event.source.kind, SourceKind.SYSTEM.value)
        self.assertEqual(event.source.id, "boot")
        self.assertEqual(event.target.kind, TargetKind.BROADCAST.value)
        self.assertTrue(event.metadata["transient"])
        self.assertTrue(event.metadata["boot_event"])

    async def test_setup_treats_boot_injection_as_core_startup_step(self):
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
            set_agent_dispatcher=lambda dispatcher: None,
            init_tools=AsyncMock(),
        )
        app.mode_manager = SimpleNamespace(set_source_catalog_backend=lambda *args, **kwargs: None)
        app.heart = SimpleNamespace(init_heart=AsyncMock(), get_background_status=AsyncMock())
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
            patch("core.app.FastAPIGateway", return_value=gateway),
            patch.object(App, "_sync_config_state_to_db", AsyncMock()),
            patch.object(App, "_refresh_brain_runtime", AsyncMock()),
            patch.object(App, "_inject_core_startup_boot_event", AsyncMock()) as inject_boot,
        ):
            await App.setup(app)

        inject_boot.assert_awaited_once_with()
        gateway.start.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
