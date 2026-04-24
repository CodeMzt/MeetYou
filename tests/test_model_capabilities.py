import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.openai_adapter import OpenAIAdapter
from core.model_capabilities.resolver import ModelCapabilityResolver


class ModelCapabilitiesTests(unittest.IsolatedAsyncioTestCase):
    def _resolver(self) -> ModelCapabilityResolver:
        return ModelCapabilityResolver(
            registry_path="core/model_capabilities/default_registry.json",
            cache_path=str(Path(tempfile.gettempdir()) / "meetyou-model-cap-test-cache.json"),
            cache_ttl_seconds=3600,
        )

    def test_deepseek_v4_limits_and_compat_mapping(self):
        resolver = self._resolver()

        flash, _ = resolver.resolve(provider="deepseek", model="deepseek-v4-flash")
        pro, _ = resolver.resolve(provider="deepseek", model="deepseek-v4-pro")
        chat, _ = resolver.resolve(provider="deepseek", model="deepseek-chat")
        reasoner, _ = resolver.resolve(provider="deepseek", model="deepseek-reasoner")

        self.assertEqual(flash.context_window, 1_000_000)
        self.assertEqual(pro.context_window, 1_000_000)
        self.assertEqual(flash.max_output_tokens, 384_000)
        self.assertEqual(pro.max_output_tokens, 384_000)
        self.assertEqual(chat.context_window, 1_000_000)
        self.assertEqual(reasoner.context_window, 1_000_000)

    def test_unknown_model_has_diagnostic_instead_of_silent_8192(self):
        resolver = self._resolver()
        capability, diagnostic = resolver.resolve(provider="openai", model="unknown-new-model")
        self.assertEqual(capability.context_window, 8192)
        self.assertIn("Unknown model capability", diagnostic["diagnostic"])
        self.assertEqual(diagnostic["source"], "fallback_default")

    async def test_gemini_models_get_refresh_updates_input_output(self):
        resolver = self._resolver()

        async def fake_fetcher(*, method, url, headers):
            self.assertEqual(method, "GET")
            self.assertIn("models/gemini-2.5-pro", url)
            return {"inputTokenLimit": 2_097_152, "outputTokenLimit": 65_536}

        refreshed = await resolver.refresh_model_capabilities(
            provider="gemini",
            model="gemini-2.5-pro",
            api_base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key="fake",
            fetcher=fake_fetcher,
        )
        self.assertEqual(refreshed["new"]["context_window"], 2_097_152)
        self.assertEqual(refreshed["new"]["max_output_tokens"], 65_536)

    def test_openai_registry_fallback_covers_gpt_5_4_variants(self):
        resolver = self._resolver()
        for model in ("gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"):
            capability, diagnostic = resolver.resolve(provider="openai", model=model)
            self.assertEqual(capability.context_window, 400_000)
            self.assertEqual(diagnostic["source"], "registry")

    def test_adapter_get_context_limit_uses_resolver(self):
        adapter = OpenAIAdapter()
        self.assertEqual(adapter.get_context_limit("gpt-5.4-mini"), 400_000)


if __name__ == "__main__":
    unittest.main()
