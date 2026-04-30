import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.state_backends import RuntimeStateBlobBackend
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


class _InMemoryStateBlobService:
    def __init__(self):
        self.state = {}

    def load_state(self, *, principal_id, state_key: str, default_factory):
        return self.state.get((str(principal_id), state_key), default_factory())

    def save_state(self, *, principal_id, state_key: str, payload: dict, meta: dict | None = None):
        self.state[(str(principal_id), state_key)] = dict(payload or {})
        return None


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
        self.assertIn("profile_alias:academic_research->academic_biomed", status["warnings"])
        self.assertIn("unsupported_connector:bad_connector", status["warnings"])
        self.assertEqual([item["id"] for item in ordered], ["source_b", "source_a"])
        self.assertEqual(manager.get_source_profile("academic_research")["name"], "academic_biomed")

    async def test_profile_alias_and_empty_official_diagnostics(self):
        path = self._write_catalog(
            {
                "version": "1",
                "default_source_profiles": {
                    "tech_global": {
                        "preferred_source_ids": [],
                        "official_only": True,
                        "primary_domains": [],
                    }
                },
                "context_limits": [],
                "sources": [
                    {
                        "id": "community_blog",
                        "enabled": True,
                        "domain": "blog.example.com",
                        "label": "Blog",
                        "connector_type": "whitelist_page_reader",
                        "profiles": ["tech_global"],
                        "priority": 10,
                        "primary_source": False,
                    }
                ],
            }
        )
        manager = SourceCatalogManager(_FakeConfig({"source_catalog_path": path}))

        status = manager.get_catalog_status()

        self.assertEqual(manager.get_source_profile("tech_global")["name"], "tech_updates")
        self.assertEqual(manager.get_sources("tech_global"), [])
        self.assertIn("profile_alias:tech_global->tech_updates", status["warnings"])
        self.assertIn("profile_empty_official_sources:tech_updates", status["warnings"])

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

    async def test_reads_catalog_from_blob_backend_when_available(self):
        path = self._write_catalog({"version": "1", "default_source_profiles": {}, "context_limits": [], "sources": []})
        service = _InMemoryStateBlobService()
        service.state[("self", "source_catalog")] = {
            "version": "2",
            "default_source_profiles": {
                "academic_research": {
                    "preferred_source_ids": ["source_db"],
                    "official_only": True,
                    "primary_domains": [],
                }
            },
            "context_limits": [],
            "sources": [
                {
                    "id": "source_db",
                    "enabled": True,
                    "domain": "db.example.com",
                    "label": "DB",
                    "connector_type": "rss_atom_feed",
                    "profiles": ["academic_research"],
                    "priority": 20,
                    "primary_source": True,
                }
            ],
        }
        manager = SourceCatalogManager(_FakeConfig({"source_catalog_path": path}))
        manager.set_store_backend(
            RuntimeStateBlobBackend(service, principal_id="self", state_key="source_catalog", default_factory=dict)
        )

        status = manager.get_catalog_status()

        self.assertTrue(status["available"])
        self.assertEqual(status["storage"], "database")
        self.assertEqual(manager.get_sources("academic_research")[0]["id"], "source_db")

    async def test_migrates_file_catalog_into_blob_backend(self):
        path = self._write_catalog(
            {
                "version": "1",
                "default_source_profiles": {"academic_research": {"preferred_source_ids": [], "official_only": True}},
                "context_limits": [],
                "sources": [
                    {
                        "id": "source_file",
                        "enabled": True,
                        "domain": "file.example.com",
                        "label": "File",
                        "connector_type": "whitelist_page_reader",
                        "profiles": ["academic_research"],
                        "priority": 30,
                        "primary_source": True,
                    }
                ],
            }
        )
        service = _InMemoryStateBlobService()
        manager = SourceCatalogManager(_FakeConfig({"source_catalog_path": path}))
        manager.set_store_backend(
            RuntimeStateBlobBackend(service, principal_id="self", state_key="source_catalog", default_factory=dict),
            migrate_current=True,
        )

        stored = service.state[("self", "source_catalog")]

        self.assertEqual(stored["version"], "1")
        self.assertEqual(stored["sources"][0]["id"], "source_file")

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
