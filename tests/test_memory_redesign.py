import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from core.context import ContextManager
from tools.memory import Memory


class DummyConfig:
    def __init__(self, memory_file_path: str, model: str = "test-embedding"):
        self._values = {
            "memory_file_path": memory_file_path,
            "embedding_model": model,
            "embedding_api_key": "test-key",
            "embedding_api_url": "https://example.invalid/embeddings",
        }

    def get(self, key: str):
        return self._values.get(key)


class DummySource:
    def __init__(self, kind: str = "cli", source_id: str = "user-1"):
        self.kind = kind
        self.id = source_id


class FakeAdapter:
    def __init__(self):
        self.responses: list[str] = []
        self.last_messages = None

    async def chat(self, session, api_url, api_key, model, messages, tools=None, **kwargs):
        self.last_messages = messages
        if not self.responses:
            return {"content": '{"profile_upserts": [], "task_upserts": [], "links": []}'}
        return {"content": self.responses.pop(0)}


class TestMemory(Memory):
    async def _get_embedding(self, text: str) -> list[float]:
        raw = str(text or "")
        lowered = raw.lower()
        vec = [0.0] * 6
        mapping = [
            (("name", "who am i", "阿明"), 0),
            (("payment", "project", "task", "todo", "fix"), 1),
            (("coffee", "preference", "like"), 2),
            (("shanghai", "hangzhou", "location", "city"), 3),
            (("recent", "event"), 4),
        ]
        for words, idx in mapping:
            if any(word in lowered or word in raw for word in words):
                vec[idx] += 1.0
        if sum(vec) == 0:
            digest = hashlib.sha256(raw.encode("utf-8")).digest()
            for idx in range(6):
                vec[idx] = digest[idx] / 255.0
        return vec


class MemoryRedesignTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.memory_path = Path(self.tmpdir.name) / "memory.json"
        self.config = DummyConfig(str(self.memory_path))
        self.memory = TestMemory()
        await self.memory.init_memory(self.config)
        self.source = DummySource()

    async def asyncTearDown(self):
        await self.memory.close_memory()
        self.tmpdir.cleanup()

    async def test_save_memory_is_episode_only_and_idempotent(self):
        first = await self.memory.save_memory("payment project needs callback fix", 0.8, session_id="s1", source=self.source)
        second = await self.memory.save_memory("payment project needs callback fix", 0.8, session_id="s1", source=self.source)

        self.assertIn("保存", first)
        self.assertIn("更新", second)
        self.assertEqual(len(self.memory._store["records"]), 1)
        self.assertEqual(self.memory._store["records"][0]["type"], "episode")

    async def test_context_summary_prefers_session_over_global(self):
        context_manager = ContextManager(self.memory, adapter=None, event_bus=None)
        await context_manager.update_context("global summary")
        await context_manager.update_context("session summary", session_id="s1")

        self.assertEqual(await context_manager.load_context("s1"), "session summary")
        self.assertEqual(await context_manager.load_context("other"), "global summary")

    async def test_housekeeping_consolidates_and_recall_groups(self):
        texts = [
            "payment project continues fixing callback",
            "payment project still has one bug",
            "user name is 阿明",
            "payment project needs more tests",
            "recently I am busy with the payment project",
        ]
        for text in texts:
            await self.memory.save_memory(text, 0.8, session_id="s1", source=self.source)

        batch_ids = [record["id"] for record in self.memory._store["records"]]
        adapter = FakeAdapter()
        adapter.responses.append(json.dumps({
            "profile_upserts": [
                {
                    "fact_key": "name",
                    "fact_value": "阿明",
                    "confidence": 0.95,
                    "source_record_ids": [batch_ids[2]],
                }
            ],
            "task_upserts": [
                {
                    "task_key": "pay_fix",
                    "summary": "payment project fix callback",
                    "task_status": "open",
                    "project": "payment project",
                    "deadline": "",
                    "confidence": 0.88,
                    "source_record_ids": [batch_ids[0], batch_ids[1], batch_ids[3], batch_ids[4]],
                }
            ],
            "links": [
                {"from_id": batch_ids[0], "to_id": batch_ids[1], "relation": "same_project"}
            ],
        }, ensure_ascii=False))
        self.memory.set_housekeeping_adapter(adapter)

        await self.memory.run_housekeeping(None, "https://example.invalid/chat", "k", "m")

        recall_task = await self.memory.recall_memory("what am I busy with recently", session_id="s1", source=self.source)
        recall_profile = await self.memory.recall_memory("who am I", session_id="s1", source=self.source)
        structured_task = json.loads(
            await self.memory.recall_memory_structured("what am I busy with recently", session_id="s1", source=self.source)
        )

        self.assertIn("payment project", recall_task)
        self.assertIn("阿明", recall_profile)
        self.assertTrue(structured_task["tasks"])
        self.assertEqual(structured_task["tasks"][0]["task_key"], "pay_fix")

    async def test_conflicting_profile_invalidates_old_value(self):
        ep1 = await self.memory.save_memory("user is in shanghai", 0.7, session_id="s1", source=self.source)
        ep2 = await self.memory.save_memory("user is in hangzhou", 0.9, session_id="s1", source=self.source)
        self.assertIn("保存", ep1)
        self.assertIn("保存", ep2)

        source_ids = [record["id"] for record in self.memory._store["records"]]
        await self.memory._apply_profile_upsert("user-1", {
            "fact_key": "location",
            "fact_value": "shanghai",
            "confidence": 0.8,
            "source_record_ids": [source_ids[0]],
        })
        await self.memory._apply_profile_upsert("user-1", {
            "fact_key": "location",
            "fact_value": "hangzhou",
            "confidence": 0.9,
            "source_record_ids": [source_ids[1]],
        })

        active_locations = [
            record for record in self.memory._store["records"]
            if record.get("type") == "profile_fact" and record.get("fact_key") == "location" and record.get("status") == "active"
        ]
        invalidated_locations = [
            record for record in self.memory._store["records"]
            if record.get("type") == "profile_fact" and record.get("fact_key") == "location" and record.get("status") == "invalidated"
        ]
        recall = await self.memory.recall_memory("what city am I in", session_id="s1", source=self.source)
        payload = json.loads(
            await self.memory.recall_memory_structured("what city am I in", session_id="s1", source=self.source)
        )

        self.assertEqual(len(active_locations), 1)
        self.assertEqual(active_locations[0]["fact_value"], "hangzhou")
        self.assertEqual(len(invalidated_locations), 1)
        self.assertIn("hangzhou", recall)
        self.assertEqual(payload["profile"][0]["fact_value"], "hangzhou")

    async def test_invalid_file_is_reset_to_empty_store(self):
        await self.memory.close_memory()
        self.memory_path.write_text('{"nodes": [], "edges": []}', encoding="utf-8")

        fresh_memory = TestMemory()
        await fresh_memory.init_memory(self.config)
        try:
            self.assertEqual(fresh_memory._store["records"], [])
            self.assertEqual(fresh_memory._store["edges"], [])
            self.assertEqual(fresh_memory._store["working_summaries"]["global"], "")
        finally:
            await fresh_memory.close_memory()

    async def test_embedding_model_switch_isolated_from_old_records(self):
        await self.memory.save_memory("payment project needs callback fix", 0.8, session_id="s1", source=self.source)
        self.memory.refresh_config(DummyConfig(str(self.memory_path), model="new-embedding"))

        payload = json.loads(
            await self.memory.recall_memory_structured("what am I busy with recently", session_id="s1", source=self.source)
        )
        self.assertFalse(payload["profile"])
        self.assertFalse(payload["tasks"])
        self.assertFalse(payload["recent_events"])

    async def test_memory_views_expose_frontend_snapshot_and_graph(self):
        await self.memory.save_memory("payment project fixed callback flow", 0.8, session_id="s1", source=self.source)
        await self.memory.update_working_summary("session summary", session_id="s1")

        source_ids = [record["id"] for record in self.memory._store["records"]]
        await self.memory._apply_profile_upsert("user-1", {
            "fact_key": "name",
            "fact_value": "阿明",
            "confidence": 0.9,
            "source_record_ids": [source_ids[0]],
        })
        await self.memory._apply_task_upsert("user-1", {
            "task_key": "pay_fix",
            "summary": "payment project fix callback flow",
            "task_status": "open",
            "project": "payment project",
            "deadline": "",
            "confidence": 0.88,
            "source_record_ids": [source_ids[0]],
        })

        snapshot = self.memory.get_memory_snapshot(source_id="user-1", session_id="s1")
        graph = self.memory.get_memory_graph_view(source_id="user-1", session_id="s1")

        self.assertEqual(snapshot["working_summaries"]["session_summary"], "session summary")
        self.assertEqual(snapshot["scope"]["source_id"], "user-1")
        self.assertGreaterEqual(snapshot["stats"]["record_count"], 3)
        self.assertTrue(any(record["type"] == "profile_fact" for record in snapshot["records"]))
        self.assertTrue(any(node["type"] == "task" for node in graph["nodes"]))
        self.assertTrue(all("embedding" not in node for node in graph["nodes"]))
        self.assertTrue(all("source" in edge and "target" in edge for edge in graph["edges"]))

    async def test_structured_recall_returns_json_groups(self):
        await self.memory.save_memory("user name is 阿明", 0.8, session_id="s1", source=self.source)
        source_ids = [record["id"] for record in self.memory._store["records"]]
        await self.memory._apply_profile_upsert("user-1", {
            "fact_key": "name",
            "fact_value": "阿明",
            "confidence": 0.95,
            "source_record_ids": [source_ids[0]],
        })

        payload = json.loads(
            await self.memory.recall_memory_structured("who am I", session_id="s1", source=self.source)
        )

        self.assertEqual(payload["query_text"], "who am I")
        self.assertTrue(payload["profile"])
        self.assertEqual(payload["profile"][0]["fact_value"], "阿明")
        self.assertIn("score", payload["profile"][0])


    """
    async def test_housekeeping_prompt_receives_existing_memory_and_summary_context(self):
        await self.memory.update_working_summary("session summary for payment work", session_id="s1")
        first_episode = await self.memory.save_memory("user likes black coffee", 0.8, session_id="s1", source=self.source)
        self.assertIn("淇濆瓨", first_episode)

        source_ids = [record["id"] for record in self.memory._store["records"]]
        await self.memory._apply_profile_upsert("user-1", {
            "fact_key": "coffee_preference",
            "fact_value": "black coffee",
            "confidence": 0.92,
            "source_record_ids": [source_ids[0]],
        })
        await self.memory._apply_task_upsert("user-1", {
            "task_key": "pay_fix",
            "summary": "payment project callback cleanup",
            "task_status": "open",
            "project": "payment project",
            "deadline": "",
            "confidence": 0.86,
            "source_record_ids": [source_ids[0]],
        })

        for text in [
            "payment project still needs tests",
            "payment project callback bug is open",
            "user name is 闃挎槑",
            "I am still working on payment project",
        ]:
            await self.memory.save_memory(text, 0.8, session_id="s1", source=self.source)

        adapter = FakeAdapter()
        self.memory.set_housekeeping_adapter(adapter)

        await self.memory.run_housekeeping(None, "https://example.invalid/chat", "k", "m")

        self.assertIsNotNone(adapter.last_messages)
        self.assertEqual(adapter.last_messages[0]["role"], "system")
        self.assertIn("long-term memory consolidation engine", adapter.last_messages[0]["content"])
        payload = json.loads(adapter.last_messages[1]["content"])

        self.assertEqual(payload["user_id"], "user-1")
        self.assertIn("current_time", payload)
        self.assertEqual(payload["working_summary"]["session_summaries"]["s1"], "session summary for payment work")
        self.assertTrue(payload["existing_profile_facts"])
        self.assertEqual(payload["existing_profile_facts"][0]["fact_key"], "coffee_preference")
        self.assertTrue(payload["existing_tasks"])
        self.assertEqual(payload["existing_tasks"][0]["task_key"], "pay_fix")
        self.assertGreaterEqual(len(payload["episodes"]), 5)

    """

    async def test_housekeeping_prompt_receives_existing_memory_and_summary_context_v2(self):
        await self.memory.update_working_summary("session summary for payment work", session_id="s1")
        first_episode = await self.memory.save_memory("user likes black coffee", 0.8, session_id="s1", source=self.source)
        self.assertTrue(first_episode)

        source_ids = [record["id"] for record in self.memory._store["records"]]
        await self.memory._apply_profile_upsert("user-1", {
            "fact_key": "coffee_preference",
            "fact_value": "black coffee",
            "confidence": 0.92,
            "source_record_ids": [source_ids[0]],
        })
        await self.memory._apply_task_upsert("user-1", {
            "task_key": "pay_fix",
            "summary": "payment project callback cleanup",
            "task_status": "open",
            "project": "payment project",
            "deadline": "",
            "confidence": 0.86,
            "source_record_ids": [source_ids[0]],
        })

        for text in [
            "payment project still needs tests",
            "payment project callback bug is open",
            "user name is alex",
            "I am still working on payment project",
        ]:
            await self.memory.save_memory(text, 0.8, session_id="s1", source=self.source)

        adapter = FakeAdapter()
        self.memory.set_housekeeping_adapter(adapter)

        await self.memory.run_housekeeping(None, "https://example.invalid/chat", "k", "m")

        self.assertIsNotNone(adapter.last_messages)
        self.assertEqual(adapter.last_messages[0]["role"], "system")
        self.assertIn("long-term memory consolidation engine", adapter.last_messages[0]["content"])
        payload = json.loads(adapter.last_messages[1]["content"])

        self.assertEqual(payload["user_id"], "user-1")
        self.assertIn("current_time", payload)
        self.assertEqual(payload["working_summary"]["session_summaries"]["s1"], "session summary for payment work")
        self.assertTrue(payload["existing_profile_facts"])
        self.assertEqual(payload["existing_profile_facts"][0]["fact_key"], "coffee_preference")
        self.assertTrue(payload["existing_tasks"])
        self.assertEqual(payload["existing_tasks"][0]["task_key"], "pay_fix")
        self.assertGreaterEqual(len(payload["episodes"]), 5)

    async def test_memory_views_without_source_filter_return_all_records(self):
        source_a = DummySource(source_id="feishu-user")
        source_b = DummySource(source_id="desktop-app")
        await self.memory.save_memory("payment project fixed callback flow", 0.8, session_id="s1", source=source_a)
        await self.memory.save_memory("user likes pour over coffee", 0.7, session_id="s2", source=source_b)

        snapshot = self.memory.get_memory_snapshot()
        graph = self.memory.get_memory_graph_view()
        user_ids = {record["scope"]["user_id"] for record in snapshot["records"]}

        self.assertEqual(snapshot["scope"]["source_id"], "")
        self.assertGreaterEqual(snapshot["stats"]["record_count"], 2)
        self.assertIn("feishu-user", user_ids)
        self.assertIn("desktop-app", user_ids)
        self.assertEqual(len(graph["nodes"]), snapshot["stats"]["record_count"])

    async def test_explicit_remember_batch_falls_back_to_profile_memory_when_patch_is_empty(self):
        result = await self.memory.save_memory(
            "Durable relationship fact: User is my developer and friend.",
            0.8,
            session_id="s1",
            source=self.source,
            tags=["remember_knowledge", "remember_category:relationship"],
        )
        self.assertTrue(result)
        for idx in range(4):
            await self.memory.save_memory(f"filler episode {idx}", 0.3, session_id="s1", source=self.source)

        explicit_record = next(
            record for record in self.memory._store["records"]
            if "remember_knowledge" in record.get("tags", [])
        )
        adapter = FakeAdapter()
        adapter.responses.append(json.dumps({
            "profile_upserts": [],
            "task_upserts": [],
            "links": [],
        }, ensure_ascii=False))
        self.memory.set_housekeeping_adapter(adapter)

        await self.memory.run_housekeeping(None, "https://example.invalid/chat", "k", "m")

        profile_records = [
            record for record in self.memory._store["records"]
            if record.get("type") == "profile_fact" and explicit_record["id"] in record.get("source_record_ids", [])
        ]
        self.assertTrue(profile_records)
        self.assertNotIn("pending_consolidation", explicit_record["tags"])
        payload = json.loads(adapter.last_messages[1]["content"])
        episode_payload = next(item for item in payload["episodes"] if item["id"] == explicit_record["id"])
        self.assertTrue(episode_payload["hints"]["remember_requested"])
        self.assertEqual(episode_payload["hints"]["remember_category"], "relationship")

    async def test_relationship_memory_rejects_task_upsert_and_uses_profile_fallback(self):
        await self.memory.save_memory(
            "Durable relationship fact: User is my developer and friend.",
            0.8,
            session_id="s1",
            source=self.source,
            tags=["remember_knowledge", "remember_category:relationship"],
        )
        for idx in range(4):
            await self.memory.save_memory(f"filler episode {idx}", 0.3, session_id="s1", source=self.source)

        explicit_record = next(
            record for record in self.memory._store["records"]
            if "remember_knowledge" in record.get("tags", [])
        )
        adapter = FakeAdapter()
        adapter.responses.append(json.dumps({
            "profile_upserts": [],
            "task_upserts": [
                {
                    "task_key": "task",
                    "summary": "personal profile: developer and friend",
                    "task_status": "open",
                    "project": "memory",
                    "deadline": "",
                    "confidence": 0.99,
                    "source_record_ids": [explicit_record["id"]],
                }
            ],
            "links": [],
        }, ensure_ascii=False))
        self.memory.set_housekeeping_adapter(adapter)

        await self.memory.run_housekeeping(None, "https://example.invalid/chat", "k", "m")

        task_records = [
            record for record in self.memory._store["records"]
            if record.get("type") == "task" and record.get("scope", {}).get("user_id") == "user-1"
        ]
        profile_records = [
            record for record in self.memory._store["records"]
            if record.get("type") == "profile_fact" and explicit_record["id"] in record.get("source_record_ids", [])
        ]
        self.assertEqual(task_records, [])
        self.assertTrue(profile_records)
        self.assertNotIn("pending_consolidation", explicit_record["tags"])

if __name__ == "__main__":
    unittest.main()
