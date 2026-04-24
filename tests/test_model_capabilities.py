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

    def test_deepseek_models_match_when_openai_compatible_adapter_is_used(self):
        capability = self.resolver.resolve("openai", "deepseek-v4-flash")
        self.assertEqual(capability.provider, "deepseek")
        self.assertEqual(capability.context_window, 1_000_000)
        self.assertEqual(capability.max_output_tokens, 384_000)

    def test_unknown_model_has_diagnostic(self):
        capability = self.resolver.resolve("openai", "unknown-model-xyz")
        self.assertEqual(capability.context_window, 8192)
        self.assertIn("Unknown model capability", capability.diagnostic)
        self.assertTrue(capability.requires_manual_confirmation)

    async def test_cached_fallback_preserves_manual_confirmation_flag(self):
        await self.resolver.refresh_model_capabilities(
            provider="openai",
            model="unknown-model-xyz",
            session=_FakeSession(),
        )
        cached = self.resolver.resolve("openai", "unknown-model-xyz")
        self.assertEqual(cached.source, "cache")
        self.assertTrue(cached.requires_manual_confirmation)

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

    def test_legacy_known_model_limits_remain_available(self):
        expected = {
            "gpt-4o": 128000,
            "claude-3.5-sonnet": 200000,
            "gemini-2.5-pro": 1048576,
            "llama3.1": 131072,
        }
        for model_name, context_window in expected.items():
            with self.subTest(model=model_name):
                provider = "ollama" if model_name.startswith(("llama", "mistral", "qwen")) else "openai"
                if model_name.startswith("claude"):
                    provider = "anthropic"
                if model_name.startswith("gemini"):
                    provider = "gemini"
                capability = self.resolver.resolve(provider, model_name)
                self.assertEqual(capability.context_window, context_window)

    def test_registry_loads_from_module_path_when_cwd_changes(self):
        previous_cwd = os.getcwd()
        try:
            os.chdir(self._tmpdir.name)
            resolver = ModelCapabilityResolver(cache_path=os.path.join(self._tmpdir.name, "other_cache.json"))
            capability = resolver.resolve("openai", "gpt-5.4")
        finally:
            os.chdir(previous_cwd)
        self.assertEqual(capability.context_window, 400000)


if __name__ == "__main__":
    unittest.main()
