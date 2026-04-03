import unittest

from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway


class GatewayMemoryApiTests(unittest.TestCase):
    def setUp(self):
        def snapshot_getter(source_id="", session_id="", include_invalidated=False):
            return {
                "metadata": {
                    "embedding_model": "text-embedding-3-small",
                    "embedding_api_url": "https://example.invalid/embeddings",
                    "updated_at": "2026-03-31T00:00:00Z",
                },
                "scope": {
                    "source_id": source_id,
                    "session_id": session_id,
                },
                "working_summaries": {
                    "global_summary": "global summary",
                    "session_summary": "session summary" if session_id else "",
                    "session_id": session_id,
                },
                "records": [
                    {
                        "id": "pf_1",
                        "type": "profile_fact",
                        "scope": {"user_id": source_id or "global", "session_id": ""},
                        "content": "name: 阿明",
                        "canonical_text": "name: 阿明",
                        "embedding": [0.1, 0.2],
                        "embedding_model": "text-embedding-3-small",
                        "strength": 0.72,
                        "importance": 0.9,
                        "confidence": 0.95,
                        "created_at": "2026-03-31T00:00:00Z",
                        "last_accessed_at": "2026-03-31T00:00:00Z",
                        "last_updated_at": "2026-03-31T00:00:00Z",
                        "access_count": 1,
                        "status": "active",
                        "tags": [],
                        "entity_keys": [],
                        "source_record_ids": [],
                        "fact_key": "name",
                        "fact_value": "阿明",
                        "task_key": None,
                        "project": None,
                        "task_status": None,
                        "deadline": None,
                    }
                ],
                "edges": [],
                "stats": {
                    "record_count": 1,
                    "edge_count": 0,
                    "by_type": {"profile_fact": 1, "task": 0, "episode": 0},
                },
            }

        def graph_getter(source_id="", session_id="", include_invalidated=False):
            return {
                "metadata": {
                    "embedding_model": "text-embedding-3-small",
                    "embedding_api_url": "https://example.invalid/embeddings",
                    "updated_at": "2026-03-31T00:00:00Z",
                },
                "scope": {
                    "source_id": source_id,
                    "session_id": session_id,
                },
                "working_summaries": {
                    "global_summary": "global summary",
                    "session_summary": "session summary" if session_id else "",
                    "session_id": session_id,
                },
                "nodes": [
                    {
                        "id": "pf_1",
                        "type": "profile_fact",
                        "label": "阿明",
                        "content": "name: 阿明",
                        "status": "active",
                        "scope": {"user_id": source_id or "global", "session_id": ""},
                        "strength": 0.72,
                        "importance": 0.9,
                        "confidence": 0.95,
                        "created_at": "2026-03-31T00:00:00Z",
                        "last_accessed_at": "2026-03-31T00:00:00Z",
                        "last_updated_at": "2026-03-31T00:00:00Z",
                        "access_count": 1,
                        "tags": [],
                        "entity_keys": [],
                        "source_record_ids": [],
                        "fact_key": "name",
                        "fact_value": "阿明",
                        "task_key": None,
                        "project": None,
                        "task_status": None,
                        "deadline": None,
                    }
                ],
                "edges": [],
                "stats": {
                    "record_count": 1,
                    "edge_count": 0,
                    "by_type": {"profile_fact": 1, "task": 0, "episode": 0},
                },
            }

        self.gateway = FastAPIGateway(
            EventBus(),
            SessionManager(),
            memory_snapshot_getter=snapshot_getter,
            memory_graph_getter=graph_getter,
        )
        self.client = TestClient(self.gateway.app)
        self.addCleanup(self.client.close)

    def test_get_memory_snapshot(self):
        response = self.client.get("/memory", params={"source_id": "browser-tab-a", "session_id": "s1"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["scope"]["source_id"], "browser-tab-a")
        self.assertEqual(payload["working_summaries"]["session_summary"], "session summary")
        self.assertEqual(payload["records"][0]["fact_value"], "阿明")

    def test_get_memory_graph(self):
        response = self.client.get("/memory/graph", params={"source_id": "browser-tab-a"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["nodes"][0]["label"], "阿明")
        self.assertIn("stats", payload)
        self.assertEqual(payload["stats"]["record_count"], 1)


if __name__ == "__main__":
    unittest.main()
