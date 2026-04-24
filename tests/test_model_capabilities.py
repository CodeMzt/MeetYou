import json
import os
import tempfile
import unittest

from core.model_capabilities.resolver import ModelCapabilityResolver


class _FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = payload or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, get_payload=None):
        self._get_payload = get_payload or {}

    def get(self, url, **kwargs):
        return _FakeResponse(status=200, payload=self._get_payload)

    def post(self, url, **kwargs):
        return _FakeResponse(status=404, payload={})


class ModelCapabilityResolverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        cache_path = os.path.join(self._tmpdir.name, "cap_cache.json")
        self.resolver = ModelCapabilityResolver(cache_path=cache_path)

    def test_deepseek_v4_capability_mapping(self):
        flash = self.resolver.resolve("deepseek", "deepseek-v4-flash")
        self.assertEqual(flash.context_window, 1_000_000)
        self.assertEqual(flash.max_output_tokens, 384_000)

        pro = self.resolver.resolve("deepseek", "deepseek-v4-pro")
        self.assertEqual(pro.context_window, 1_000_000)
        self.assertEqual(pro.max_output_tokens, 384_000)

        compat_chat = self.resolver.resolve("deepseek", "deepseek-chat")
        compat_reasoner = self.resolver.resolve("deepseek", "deepseek-reasoner")
        self.assertEqual(compat_chat.context_window, 1_000_000)
        self.assertEqual(compat_reasoner.context_window, 1_000_000)

    def test_unknown_model_has_diagnostic(self):
        capability = self.resolver.resolve("openai", "unknown-model-xyz")
        self.assertEqual(capability.context_window, 8192)
        self.assertIn("Unknown model capability", capability.diagnostic)

    async def test_gemini_refresh_uses_models_get_limits(self):
        fake_session = _FakeSession(
            get_payload={
                "name": "models/gemini-2.5-flash",
                "inputTokenLimit": 222222,
                "outputTokenLimit": 77777,
            }
        )
        result = await self.resolver.refresh_model_capabilities(
            provider="gemini",
            model="gemini-2.5-flash",
            api_url="https://generativelanguage.googleapis.com/v1beta",
            api_key="k",
            session=fake_session,
        )
        self.assertEqual(result["source"], "provider_api")
        self.assertEqual(result["new"]["context_window"], 222222)
        self.assertEqual(result["new"]["max_output_tokens"], 77777)

    def test_openai_registry_fallback_for_gpt_5_4_family(self):
        for model_name in ("gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"):
            capability = self.resolver.resolve("openai", model_name)
            self.assertEqual(capability.context_window, 400000)
            self.assertGreater(capability.max_output_tokens, 0)


if __name__ == "__main__":
    unittest.main()
