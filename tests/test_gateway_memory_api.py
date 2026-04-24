import unittest

from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway


class GatewayMemoryApiTests(unittest.TestCase):
    def setUp(self):
        self.access_token = "memory-token"
        self.clear_calls = []
        self.status_updates = []
        self.delete_calls = []

        def snapshot_getter(source_id="", session_id="", include_invalidated=False):
            del include_invalidated
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
                        "type": "profile",
                        "scope": {"user_id": source_id or "global", "session_id": ""},
                        "content": "name: demo",
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
                        "fact_value": "demo",
                    }
                ],
                "edges": [],
                "stats": {
                    "record_count": 1,
                    "edge_count": 0,
                    "by_type": {"profile": 1, "fact": 0, "episode": 0},
                },
            }

        def graph_getter(source_id="", session_id="", include_invalidated=False):
            del session_id, include_invalidated
            return {
                "metadata": {
                    "embedding_model": "text-embedding-3-small",
                    "embedding_api_url": "https://example.invalid/embeddings",
                    "updated_at": "2026-03-31T00:00:00Z",
                },
                "scope": {
                    "source_id": source_id,
                    "session_id": "",
                },
                "working_summaries": {
                    "global_summary": "global summary",
                    "session_summary": "",
                    "session_id": "",
                },
                "nodes": [
                    {
                        "id": "pf_1",
                        "type": "profile",
                        "label": "demo",
                        "content": "name: demo",
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
                        "fact_value": "demo",
                    }
                ],
                "edges": [],
                "stats": {
                    "record_count": 1,
                    "edge_count": 0,
                    "by_type": {"profile": 1, "fact": 0, "episode": 0},
                },
            }

        async def memory_clearer():
            self.clear_calls.append(True)
            return {
                "ok": True,
                "cleared_record_count": 1,
                "cleared_edge_count": 0,
                "cleared_session_summary_count": 1,
                "cleared_global_summary": True,
                "cleared_session_count": 2,
                "active_session_count": 0,
                "updated_at": "2026-04-23T00:00:00Z",
            }

        async def memory_record_status_updater(memory_id, status):
            self.status_updates.append({"memory_id": memory_id, "status": status})
            if memory_id == "missing":
                raise KeyError(memory_id)
            if status not in {"active", "invalidated"}:
                raise ValueError("memory_status_invalid")
            return {
                "ok": True,
                "memory_id": memory_id,
                "status": status,
                "deleted": False,
                "updated_at": "2026-04-24T00:00:00Z",
                "record": {
                    "id": memory_id,
                    "type": "profile",
                    "scope": {"user_id": "global", "session_id": ""},
                    "content": "name: demo",
                    "strength": 0.72,
                    "importance": 0.9,
                    "confidence": 0.95,
                    "created_at": "2026-03-31T00:00:00Z",
                    "last_accessed_at": "2026-03-31T00:00:00Z",
                    "last_updated_at": "2026-04-24T00:00:00Z",
                    "access_count": 1,
                    "status": status,
                    "tags": [],
                    "entity_keys": [],
                    "source_record_ids": [],
                    "fact_key": "name",
                    "fact_value": "demo",
                },
            }

        async def memory_record_deleter(memory_id):
            self.delete_calls.append(memory_id)
            if memory_id == "missing":
                raise KeyError(memory_id)
            return {
                "ok": True,
                "memory_id": memory_id,
                "status": "deleted",
                "deleted": True,
                "updated_at": "2026-04-24T00:00:00Z",
                "record": None,
            }

        self.gateway = FastAPIGateway(
            EventBus(),
            SessionManager(),
            memory_snapshot_getter=snapshot_getter,
            memory_graph_getter=graph_getter,
            memory_clearer=memory_clearer,
            memory_record_status_updater=memory_record_status_updater,
            memory_record_deleter=memory_record_deleter,
            access_token=self.access_token,
        )
        self.client = TestClient(self.gateway.app)
        self.addCleanup(self.client.close)

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    def test_get_memory_snapshot(self):
        response = self.client.get(
            "/memory",
            params={"source_id": "browser-tab-a", "session_id": "s1"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["scope"]["source_id"], "browser-tab-a")
        self.assertEqual(payload["working_summaries"]["session_summary"], "session summary")
        self.assertEqual(payload["records"][0]["fact_value"], "demo")

    def test_get_memory_graph(self):
        response = self.client.get(
            "/memory/graph",
            params={"source_id": "browser-tab-a"},
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["nodes"][0]["label"], "demo")
        self.assertIn("stats", payload)
        self.assertEqual(payload["stats"]["record_count"], 1)

    def test_operator_memory_routes(self):
        snapshot_response = self.client.get(
            "/operator/memory",
            params={"source_id": "browser-tab-a", "session_id": "s1"},
            headers=self._auth_headers(),
        )
        graph_response = self.client.get(
            "/operator/memory/graph",
            params={"source_id": "browser-tab-a"},
            headers=self._auth_headers(),
        )

        self.assertEqual(snapshot_response.status_code, 200)
        self.assertEqual(graph_response.status_code, 200)
        self.assertEqual(snapshot_response.json()["scope"]["source_id"], "browser-tab-a")
        self.assertEqual(graph_response.json()["nodes"][0]["label"], "demo")

    def test_clear_memory_route(self):
        response = self.client.delete("/memory", headers=self._auth_headers())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cleared_record_count"], 1)
        self.assertEqual(payload["cleared_session_count"], 2)
        self.assertEqual(len(self.clear_calls), 1)

    def test_clear_operator_memory_route(self):
        response = self.client.delete("/operator/memory", headers=self._auth_headers())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["cleared_global_summary"])
        self.assertEqual(len(self.clear_calls), 1)

    def test_update_memory_record_status_routes(self):
        response = self.client.patch(
            "/memory/records/pf_1",
            json={"status": "invalidated"},
            headers=self._auth_headers(),
        )
        operator_response = self.client.patch(
            "/operator/memory/records/pf_1",
            json={"status": "active"},
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "invalidated")
        self.assertEqual(operator_response.status_code, 200)
        self.assertEqual(operator_response.json()["record"]["status"], "active")
        self.assertEqual(
            self.status_updates,
            [
                {"memory_id": "pf_1", "status": "invalidated"},
                {"memory_id": "pf_1", "status": "active"},
            ],
        )

    def test_update_memory_record_status_not_found(self):
        response = self.client.patch(
            "/operator/memory/records/missing",
            json={"status": "invalidated"},
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "memory_record_not_found")

    def test_delete_memory_record_routes(self):
        response = self.client.delete("/memory/records/pf_1", headers=self._auth_headers())
        operator_response = self.client.delete("/operator/memory/records/pf_2", headers=self._auth_headers())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertEqual(operator_response.status_code, 200)
        self.assertEqual(self.delete_calls, ["pf_1", "pf_2"])

    def test_delete_memory_record_not_found(self):
        response = self.client.delete("/operator/memory/records/missing", headers=self._auth_headers())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "memory_record_not_found")

    def test_get_memory_requires_auth(self):
        response = self.client.get("/memory")

        self.assertEqual(response.status_code, 401)
        payload = response.json()
        self.assertEqual(payload["kind"], "error")
        self.assertEqual(payload["error"]["code"], "unauthorized")


if __name__ == "__main__":
    unittest.main()
