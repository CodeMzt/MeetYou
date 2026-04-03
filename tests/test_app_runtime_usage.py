import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import App


class _FakeBrain:
    def __init__(self, snapshot=None):
        self._snapshot = snapshot

    def get_session_usage_snapshot(self, session_id: str):
        del session_id
        return self._snapshot


class _FakeSessionManager:
    def __init__(self, has_binding: bool):
        self._has_binding = has_binding

    def get_binding(self, session_id: str):
        del session_id
        return object() if self._has_binding else None


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


class _FakeConfig:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key: str, default=None):
        return self._values.get(key, default)


class AppRuntimeUsageTests(unittest.IsolatedAsyncioTestCase):
    def _make_app(self, *, snapshot=None, has_binding=True):
        app = App.__new__(App)
        app.brain = _FakeBrain(snapshot=snapshot)
        app.session_manager = _FakeSessionManager(has_binding=has_binding)
        app.mode_manager = _FakeModeManager()
        app.main_adapter = _FakeAdapter()
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

    async def test_unknown_session_still_raises(self):
        app = self._make_app(snapshot=None, has_binding=False)

        with self.assertRaisesRegex(ValueError, "Session not found"):
            await App.get_runtime_usage(app, "missing-session")


if __name__ == "__main__":
    unittest.main()
