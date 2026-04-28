import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import App
from core.exceptions import ConfigError


class _FakeBrain:
    def __init__(self, snapshot=None, debug_snapshot=None, *, debug_raises: bool = False):
        self._snapshot = snapshot
        self._debug_raises = debug_raises
        self._debug_snapshot = debug_snapshot or {
            "session_id": "desktop-1",
            "route": {"current_mode": "general", "tool_bundle": ["research_topic"]},
            "route_history": [{"round": 0, "mode": "general"}],
            "context_plan": {"layers": {"memory_recall": True}},
            "memory_scope": {"prefetched": True, "found": True},
            "authorization": {"recent_decisions": [{"tool_name": "research_topic", "ok": True}]},
            "runtime_state": {"session_id": "desktop-1", "status": "thinking"},
            "usage": {"session_id": "desktop-1", "usage_ready": True},
            "updated_at": "2026-04-02T00:00:00Z",
        }

    def get_session_usage_snapshot(self, session_id: str):
        del session_id
        return self._snapshot

    def get_session_runtime_snapshot(self, session_id: str):
        return {
            "session_id": session_id,
            "status": "idle",
            "detail": "",
        }

    def get_session_debug_snapshot(self, session_id: str):
        if self._debug_raises:
            raise ValueError(f"Session not found: {session_id}")
        payload = dict(self._debug_snapshot)
        payload["session_id"] = session_id
        payload["runtime_state"] = {**dict(payload.get("runtime_state") or {}), "session_id": session_id}
        payload["usage"] = {**dict(payload.get("usage") or {}), "session_id": session_id}
        payload["memory_scope"] = {**dict(payload.get("memory_scope") or {}), "session_id": session_id}
        return payload


class _FakeSessionManager:
    def __init__(self, has_binding: bool):
        self._has_binding = has_binding

    def get_binding(self, session_id: str):
        del session_id
        return object() if self._has_binding else None


class _FakeSessionService:
    def __init__(self, existing_session_ids=None):
        self._existing_session_ids = set(existing_session_ids or [])

    def get_by_session_id(self, session_id: str):
        return object() if session_id in self._existing_session_ids else None


class _FakeModeManager:
    async def resolve_context_limit(self, *, provider_name: str, api_url: str, model_name: str, adapter):
        del provider_name, api_url, model_name, adapter
        return {
            "context_limit_tokens": 128000,
            "context_limit_source": "config_override",
            "context_limit_model": "deepseek-reasoner",
            "context_limit_confidence": "high",
        }


class _FakeAdapter:
    def get_context_limit(self, model_name: str) -> int:
        del model_name
        return 8192


class _FakeBrainRuntime:
    def __init__(self):
        self.mode_manager = None

    def set_mode_manager(self, mode_manager):
        self.mode_manager = mode_manager


class _FakeToolsManager:
    def __init__(self):
        self.mode_manager = None

    def set_mode_manager(self, mode_manager):
        self.mode_manager = mode_manager

    def get_route_debug_snapshot(self, route_context):
        del route_context
        return {
            "visible_tools": ["research_topic"],
            "candidate_tools": ["research_topic"],
            "authorization_preview": [{"tool_name": "research_topic", "allowed": True}],
        }


class _FakeConfig:
    def __init__(self, values=None):
        self._values = values or {}
        self.rollback_calls = 0
        self.reload_calls = 0
        self.applied_updates: list[dict[str, object]] = []
        self.snapshots: list[dict[str, object]] = []

    def get(self, key: str, default=None):
        return self._values.get(key, default)

    def get_mcp_servers(self):
        return {}

    def get_mcp_server_config_diagnostic(self):
        return {"status": "not_configured", "server_count": 0}

    def begin_transaction(self):
        snapshot = {"values": dict(self._values)}
        self.snapshots.append(snapshot)
        return snapshot

    def rollback_transaction(self, snapshot):
        self.rollback_calls += 1
        self._values = dict(snapshot["values"])

    def reload(self):
        self.reload_calls += 1


class AppRuntimeUsageTests(unittest.IsolatedAsyncioTestCase):
    def _make_app(self, *, snapshot=None, debug_snapshot=None, debug_raises=False, has_binding=True, existing_session_ids=None):
        app = App.__new__(App)
        app.brain = _FakeBrain(snapshot=snapshot, debug_snapshot=debug_snapshot, debug_raises=debug_raises)
        app.session_manager = _FakeSessionManager(has_binding=has_binding)
        app.core_services = SimpleNamespace(session=_FakeSessionService(existing_session_ids=existing_session_ids or []))
        app.mode_manager = _FakeModeManager()
        app.main_adapter = _FakeAdapter()
        app.tools_manager = _FakeToolsManager()
        async def _get_background_status():
            return {
                "schedule": {"due_task_count": 1},
                "execution": {"awaiting_completion_count": 0},
                "delivery": {"pending_redelivery_count": 0},
                "system": {},
                "background_status_sources": ["task_manager.schedule"],
            }
        app.heart = SimpleNamespace(get_background_status=_get_background_status)
        app.config = _FakeConfig(
            {
                "api_provider": "openai",
                "api_url": "https://api.deepseek.com/chat/completions",
                "model": "deepseek-reasoner",
            }
        )
        return app

    async def test_returns_existing_usage_snapshot_when_ready(self):
        expected = {
            "session_id": "desktop-1",
            "usage_ready": True,
            "context_limit_tokens": 128000,
            "context_limit_source": "config_override",
            "context_limit_model": "deepseek-reasoner",
            "context_limit_confidence": "high",
            "current_context_tokens_estimated": 1024,
            "context_breakdown": {
                "system": 0,
                "history": 0,
                "tool_history": 0,
                "memory_context": 0,
                "policy": 0,
                "current_input": 0,
                "proprioception": 0,
                "total": 1024,
            },
            "last_turn_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "reasoning_tokens": 2,
                "total_tokens": 17,
            },
            "session_totals": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "reasoning_tokens": 2,
                "total_tokens": 17,
                "turn_count": 1,
            },
            "usage_source": "provider",
            "updated_at": "2026-04-02T00:00:00Z",
        }
        app = self._make_app(snapshot=expected)

        payload = await App.get_runtime_usage(app, "desktop-1")

        self.assertEqual(payload, expected)

    async def test_returns_bootstrap_snapshot_for_bound_session(self):
        app = self._make_app(snapshot=None, has_binding=True)

        payload = await App.get_runtime_usage(app, "desktop-1")

        self.assertFalse(payload["usage_ready"])
        self.assertEqual(payload["session_id"], "desktop-1")
        self.assertEqual(payload["context_limit_tokens"], 128000)
        self.assertEqual(payload["context_limit_source"], "config_override")
        self.assertEqual(payload["session_totals"]["turn_count"], 0)
        self.assertEqual(payload["current_context_tokens_estimated"], 0)

    async def test_merges_unready_snapshot_with_resolved_context_limit(self):
        app = self._make_app(
            snapshot={
                "session_id": "desktop-1",
                "usage_ready": False,
                "current_context_tokens_estimated": 512,
                "context_breakdown": {
                    "system": 64,
                    "history": 320,
                    "tool_history": 32,
                    "memory_context": 48,
                    "policy": 16,
                    "current_input": 24,
                    "proprioception": 8,
                    "total": 512,
                },
                "last_turn_usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "reasoning_tokens": 0,
                    "total_tokens": 0,
                },
                "session_totals": {
                    "prompt_tokens": 90,
                    "completion_tokens": 10,
                    "reasoning_tokens": 5,
                    "total_tokens": 105,
                    "turn_count": 3,
                },
                "usage_source": "estimated",
                "updated_at": "2026-04-09T00:00:00Z",
            }
        )

        payload = await App.get_runtime_usage(app, "desktop-1")

        self.assertFalse(payload["usage_ready"])
        self.assertEqual(payload["context_limit_tokens"], 128000)
        self.assertEqual(payload["context_limit_model"], "deepseek-reasoner")
        self.assertEqual(payload["current_context_tokens_estimated"], 512)
        self.assertEqual(payload["session_totals"]["turn_count"], 3)
        self.assertEqual(payload["context_breakdown"]["history"], 320)

    async def test_unknown_session_still_raises(self):
        app = self._make_app(snapshot=None, has_binding=False, existing_session_ids=[])

        with self.assertRaisesRegex(ValueError, "Session not found"):
            await App.get_runtime_usage(app, "missing-session")

    async def test_database_session_without_runtime_binding_returns_estimated_usage(self):
        app = self._make_app(snapshot=None, has_binding=False, existing_session_ids=["sess_db_only"])

        payload = await App.get_runtime_usage(app, "sess_db_only")

        self.assertEqual(payload["session_id"], "sess_db_only")
        self.assertFalse(payload["usage_ready"])
        self.assertEqual(payload["context_limit_tokens"], 128000)

    async def test_runtime_debug_snapshot_merges_route_and_background(self):
        app = self._make_app()

        payload = await App.get_runtime_debug(app, "desktop-1")

        self.assertEqual(payload["session_id"], "desktop-1")
        self.assertEqual(payload["route"]["current_mode"], "general")
        self.assertEqual(payload["authorization"]["route_preview"]["visible_tools"], ["research_topic"])
        self.assertEqual(payload["task_state"]["background"]["schedule"]["due_task_count"], 1)
        self.assertEqual(payload["memory_scope"]["session_id"], "desktop-1")

    async def test_runtime_debug_returns_bootstrap_payload_for_existing_session_without_brain_snapshot(self):
        app = self._make_app(debug_raises=True, has_binding=False, existing_session_ids=["sess_db_only"])

        payload = await App.get_runtime_debug(app, "sess_db_only")

        self.assertEqual(payload["session_id"], "sess_db_only")
        self.assertEqual(payload["route"], {})
        self.assertEqual(payload["route_history"], [])
        self.assertEqual(payload["memory_scope"]["session_id"], "sess_db_only")
        self.assertFalse(payload["memory_scope"]["prefetched"])
        self.assertEqual(payload["reply_control"]["checkpoint_count"], 0)
        self.assertEqual(payload["authorization"]["confirmation"]["request_id"], "")

    async def test_apply_config_updates_refreshes_mode_manager_bindings(self):
        class _ConfigWithUpdates(_FakeConfig):
            def apply_updates(self, updates):
                self.applied_updates.append(dict(updates))
                return sorted(updates.keys()), []

        app = App.__new__(App)
        app.config = _ConfigWithUpdates()
        app.brain = _FakeBrainRuntime()
        app.tools_manager = _FakeToolsManager()
        app.memory = SimpleNamespace(refresh_config=lambda config: None)

        async def _refresh_brain_runtime():
            return None

        async def _refresh_heart_runtime():
            return None

        app._refresh_brain_runtime = _refresh_brain_runtime
        app._refresh_heart_runtime = _refresh_heart_runtime

        created_manager = object()
        with patch("core.app.AssistantModeManager", return_value=created_manager):
            payload = await App.apply_config_updates(app, {"mode_router": '{"semantic_routing_enabled": true}'})

        self.assertIs(app.mode_manager, created_manager)
        self.assertIs(app.brain.mode_manager, created_manager)
        self.assertIs(app.tools_manager.mode_manager, created_manager)
        self.assertEqual(payload["reloaded_components"], ["mode_manager"])

    async def test_apply_config_updates_rolls_back_when_refresh_fails(self):
        class _ConfigWithUpdates(_FakeConfig):
            def apply_updates(self, updates):
                self.applied_updates.append(dict(updates))
                self._values.update(updates)
                return sorted(updates.keys()), []

        app = App.__new__(App)
        app.config = _ConfigWithUpdates({"api_provider": "openai"})
        app.brain = _FakeBrainRuntime()
        app.tools_manager = _FakeToolsManager()
        app.memory = SimpleNamespace(refresh_config=lambda config: None)

        async def _refresh_brain_runtime():
            raise RuntimeError("boom")

        async def _refresh_heart_runtime():
            return None

        async def _refresh_mode_runtime():
            return None

        app._refresh_brain_runtime = _refresh_brain_runtime
        app._refresh_heart_runtime = _refresh_heart_runtime
        app._refresh_mode_runtime = _refresh_mode_runtime

        with self.assertRaisesRegex(ConfigError, "已回滚"):
            await App.apply_config_updates(app, {"api_provider": "anthropic"})

        self.assertEqual(app.config.rollback_calls, 1)
        self.assertEqual(app.config.get("api_provider"), "openai")


if __name__ == "__main__":
    unittest.main()
