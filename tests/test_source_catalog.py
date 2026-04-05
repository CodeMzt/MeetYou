import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source_catalog import SourceCatalogManager


class _FakeConfig:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key: str, default=None):
        return self._values.get(key, default)


class _ProbeAdapter:
    async def query_model_context_limit(self, session, base_url: str, model: str) -> int | None:
        del session, base_url, model
        return 262144


class _StaticAdapter:
    pass


class SourceCatalogManagerTests(unittest.IsolatedAsyncioTestCase):
    def _write_catalog(self, payload: dict) -> str:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        path = os.path.join(tmp_dir.name, "source_catalog.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return path

    async def test_loads_catalog_and_orders_preferred_sources(self):
        path = self._write_catalog(
            {
                "version": "1",
                "default_source_profiles": {
                    "academic_research": {
                        "preferred_source_ids": ["source_b"],
                        "official_only": True,
                        "primary_domains": [],
                    }
                },
                "context_limits": [],
                "sources": [
                    {
                        "id": "source_a",
                        "enabled": True,
                        "domain": "a.example.com",
                        "label": "A",
                        "connector_type": "whitelist_page_reader",
                        "profiles": ["academic_research"],
                        "priority": 50,
                        "primary_source": True,
                    },
                    {
                        "id": "source_b",
                        "enabled": True,
                        "domain": "b.example.com",
                        "label": "B",
                        "connector_type": "rss_atom_feed",
                        "profiles": ["academic_research"],
                        "priority": 10,
                        "primary_source": True,
                    },
                    {
                        "id": "source_c",
                        "enabled": False,
                        "domain": "c.example.com",
                        "label": "C",
                        "connector_type": "whitelist_page_reader",
                        "profiles": ["academic_research"],
                        "priority": 100,
                        "primary_source": True,
                    },
                    {
                        "id": "bad_connector",
                        "enabled": True,
                        "domain": "bad.example.com",
                        "label": "Bad",
                        "connector_type": "not_real",
                        "profiles": ["academic_research"],
                        "priority": 100,
                        "primary_source": True,
                    }
                ],
            }
        )
        manager = SourceCatalogManager(_FakeConfig({"source_catalog_path": path}))

        status = manager.get_catalog_status()
        ordered = manager.get_sources("academic_research")

        self.assertTrue(status["available"])
        self.assertEqual(status["source_count"], 3)
        self.assertEqual([item["id"] for item in ordered], ["source_b", "source_a"])

    async def test_invalid_json_marks_catalog_unavailable(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        path = os.path.join(tmp_dir.name, "source_catalog.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{bad json")

        manager = SourceCatalogManager(_FakeConfig({"source_catalog_path": path}))
        status = manager.get_catalog_status()

        self.assertFalse(status["available"])
        self.assertIn("invalid_json", status["error"])

    async def test_context_limit_uses_catalog_override(self):
        path = self._write_catalog(
            {
                "version": "1",
                "default_source_profiles": {},
                "context_limits": [
                    {
                        "provider": "openai",
                        "host_patterns": ["api.deepseek.com"],
                        "model_patterns": ["deepseek-reasoner"],
                        "context_limit_tokens": 128000,
                        "source": "config_override",
                        "confidence": "high",
                        "probe": False,
                    }
                ],
                "sources": [],
            }
        )
        manager = SourceCatalogManager(_FakeConfig({"source_catalog_path": path}))

        resolved = await manager.resolve_context_limit(
            provider_name="openai",
            api_url="https://api.deepseek.com/chat/completions",
            model_name="deepseek-reasoner",
            adapter=_StaticAdapter(),
        )

        self.assertEqual(resolved.context_limit_tokens, 128000)
        self.assertEqual(resolved.context_limit_source, "config_override")
        self.assertEqual(resolved.context_limit_confidence, "high")

    async def test_context_limit_probe_wins_when_enabled(self):
        path = self._write_catalog(
            {
                "version": "1",
                "default_source_profiles": {},
                "context_limits": [
                    {
                        "provider": "ollama",
                        "host_patterns": ["localhost"],
                        "model_patterns": ["llama3.1"],
                        "context_limit_tokens": 131072,
                        "source": "config_override",
                        "confidence": "medium",
                        "probe": True,
                    }
                ],
                "sources": [],
            }
        )
        manager = SourceCatalogManager(_FakeConfig({"source_catalog_path": path}))

        resolved = await manager.resolve_context_limit(
            provider_name="ollama",
            api_url="http://localhost:11434/api/chat",
            model_name="llama3.1",
            adapter=_ProbeAdapter(),
        )

        self.assertEqual(resolved.context_limit_tokens, 262144)
        self.assertEqual(resolved.context_limit_source, "provider_probe")
        self.assertEqual(resolved.context_limit_confidence, "high")


if __name__ == "__main__":
    unittest.main()
