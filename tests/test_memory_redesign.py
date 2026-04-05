import hashlib
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from core.context import ContextManager
from tools.memory import Memory
from tools.memory_layers import dt_to_iso, utcnow


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
            return {"content": '{"profile_upserts": [], "fact_upserts": [], "links": []}'}
        return {"content": self.responses.pop(0)}


class DummyMemory(Memory):
    async def _get_embedding(self, text: str) -> list[float]:
        raw = str(text or "")
        lowered = raw.lower()
        vec = [0.0] * 6
        mapping = [
            (("name", "who am i", "阿明"), 0),
            (("payment", "callback", "billing", "fix"), 1),
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
        self.memory = DummyMemory()
        await self.memory.init_memory(self.config)
        self.source = DummySource()

    async def asyncTearDown(self):
        await self.memory.close_memory()
        self.tmpdir.cleanup()

    def _age_oldest_pending_episode(self, minutes: int = 31) -> None:
        oldest = self.memory._store["records"][0]
        aged = dt_to_iso(utcnow() - timedelta(minutes=minutes))
        oldest["created_at"] = aged
        oldest["last_updated_at"] = aged

    async def test_save_memory_is_episode_only_and_idempotent(self):
        first = await self.memory.save_memory("payment callback needs fix", 0.8, session_id="s1", source=self.source)
        second = await self.memory.save_memory("payment callback needs fix", 0.8, session_id="s1", source=self.source)

        self.assertIn("保存", first)
        self.assertIn("更新", second)
        self.assertEqual(len(self.memory._store["records"]), 1)
        self.assertEqual(self.memory._store["records"][0]["type"], "episode")

    async def test_init_memory_drops_legacy_task_records_and_task_edges(self):
        task_record = {
            "id": "task_legacy_follow_up",
            "type": "task",
            "scope": {"user_id": "user-1", "session_id": ""},
            "content": "legacy follow-up",
            "canonical_text": "legacy follow-up",
            "embedding": [0.1, 0.2],
            "embedding_model": "test-embedding",
            "strength": 0.7,
            "importance": 0.7,
            "confidence": 0.9,
            "created_at": "2026-04-04T03:16:31Z",
            "last_accessed_at": "2026-04-04T03:16:31Z",
            "last_updated_at": "2026-04-04T03:16:31Z",
            "access_count": 0,
            "status": "active",
            "tags": [],
            "entity_keys": [],
            "source_record_ids": [],
            "task_key": "legacy-follow-up",
        }
        fact_record = {
            "id": "fact_payment_callback",
            "type": "fact",
            "scope": {"user_id": "user-1", "session_id": ""},
            "content": "payment callback still needs retry handling",
            "canonical_text": "payment callback still needs retry handling",
            "embedding": [0.2, 0.4],
            "embedding_model": "test-embedding",
            "strength": 0.8,
            "importance": 0.7,
            "confidence": 0.9,
            "created_at": "2026-04-04T03:16:31Z",
            "last_accessed_at": "2026-04-04T03:16:31Z",
            "last_updated_at": "2026-04-04T03:16:31Z",
            "access_count": 0,
            "status": "active",
            "tags": [],
            "entity_keys": [],
            "source_record_ids": [],
        }
        self.memory_path.write_text(
            json.dumps(
                {
                    "metadata": {
                        "embedding_model": "test-embedding",
                        "embedding_api_url": "https://example.invalid/embeddings",
                        "updated_at": "2026-04-04T03:16:31Z",
                    },
                    "records": [task_record, fact_record],
                    "edges": [{"from_id": task_record["id"], "to_id": fact_record["id"], "derived_from": True}],
                    "working_summaries": {"global": "", "by_session": {}},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        reloaded = DummyMemory()
        await reloaded.init_memory(self.config)
        try:
            self.assertEqual([record["type"] for record in reloaded._store["records"]], ["fact"])
            self.assertEqual(reloaded._store["edges"], [])
        finally:
            await reloaded.close_memory()

    async def test_context_summary_prefers_session_over_global(self):
        context_manager = ContextManager(self.memory, adapter=None, event_bus=None)
        await context_manager.update_context("global summary")
        await context_manager.update_context("session summary", session_id="s1")

        self.assertEqual(await context_manager.load_context("s1"), "session summary")
        self.assertEqual(await context_manager.load_context("other"), "global summary")

    async def test_housekeeping_consolidates_into_profile_and_fact(self):
        texts = [
            "payment callback bug is still open",
            "billing callback still needs tests",
            "user name is 阿明",
            "payment callback retry logic is broken",
            "recently I am busy with payment callback work",
        ]
        for text in texts:
            await self.memory.save_memory(text, 0.8, session_id="s1", source=self.source)
        self._age_oldest_pending_episode()

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
            "fact_upserts": [
                {
                    "content": "payment callback bug remains open in billing",
                    "fact_key": "payment_callback",
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

        recall_fact = await self.memory.recall_memory("what am I busy with recently", session_id="s1", source=self.source)
        recall_profile = await self.memory.recall_memory("who am I", session_id="s1", source=self.source)
        structured = json.loads(
            await self.memory.recall_memory_structured("what am I busy with recently", session_id="s1", source=self.source)
        )

        self.assertIn("payment callback", recall_fact)
        self.assertIn("阿明", recall_profile)
        self.assertTrue(structured["facts"])
        self.assertEqual(structured["facts"][0]["fact_key"], "payment_callback")
        self.assertFalse(any(record["type"] == "episode" for record in self.memory._store["records"]))

    async def test_second_stage_merges_similar_long_term_facts(self):
        for text in [
            "payment callback bug still blocks release",
            "billing callback bug still blocks release",
        ]:
            await self.memory.save_memory(text, 0.8, session_id="s1", source=self.source)
        self._age_oldest_pending_episode()

        batch_ids = [record["id"] for record in self.memory._store["records"]]
        adapter = FakeAdapter()
        adapter.responses.append(json.dumps({
            "profile_upserts": [],
            "fact_upserts": [
                {
                    "content": "payment callback bug blocks release",
                    "fact_key": "payment_callback_release",
                    "confidence": 0.9,
                    "source_record_ids": [batch_ids[0]],
                },
                {
                    "content": "billing callback bug blocks release",
                    "fact_key": "billing_callback_release",
                    "confidence": 0.88,
                    "source_record_ids": [batch_ids[1]],
                }
            ],
            "links": [],
        }, ensure_ascii=False))
        self.memory.set_housekeeping_adapter(adapter)

        await self.memory.run_housekeeping(None, "https://example.invalid/chat", "k", "m")

        active_facts = [
            record for record in self.memory._store["records"]
            if record.get("type") == "fact" and record.get("status") == "active"
        ]
        self.assertEqual(len(active_facts), 1)
        self.assertGreaterEqual(len(active_facts[0].get("source_record_ids", [])), 2)

    async def test_conflicting_profile_invalidates_old_value(self):
        await self.memory.save_memory("user is in shanghai", 0.7, session_id="s1", source=self.source)
        await self.memory.save_memory("user is in hangzhou", 0.9, session_id="s1", source=self.source)

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
            if record.get("type") == "profile" and record.get("fact_key") == "location" and record.get("status") == "active"
        ]
        invalidated_locations = [
            record for record in self.memory._store["records"]
            if record.get("type") == "profile" and record.get("fact_key") == "location" and record.get("status") == "invalidated"
        ]
        payload = json.loads(
            await self.memory.recall_memory_structured("what city am I in", session_id="s1", source=self.source)
        )

        self.assertEqual(len(active_locations), 1)
        self.assertEqual(active_locations[0]["fact_value"], "hangzhou")
        self.assertEqual(len(invalidated_locations), 1)
        self.assertEqual(payload["profile"][0]["fact_value"], "hangzhou")

    async def test_invalid_file_is_reset_to_empty_store(self):
        await self.memory.close_memory()
        self.memory_path.write_text('{"nodes": [], "edges": []}', encoding="utf-8")

        fresh_memory = DummyMemory()
        await fresh_memory.init_memory(self.config)
        try:
            self.assertEqual(fresh_memory._store["records"], [])
            self.assertEqual(fresh_memory._store["edges"], [])
            self.assertEqual(fresh_memory._store["working_summaries"]["global"], "")
        finally:
            await fresh_memory.close_memory()

    async def test_embedding_model_switch_isolated_from_old_records(self):
        await self.memory.save_memory("payment callback needs fix", 0.8, session_id="s1", source=self.source)
        self.memory.refresh_config(DummyConfig(str(self.memory_path), model="new-embedding"))

        payload = json.loads(
            await self.memory.recall_memory_structured("what am I busy with recently", session_id="s1", source=self.source)
        )
        self.assertFalse(payload["profile"])
        self.assertFalse(payload["facts"])
        self.assertFalse(payload["recent_events"])

    async def test_memory_views_expose_projection_without_embedding(self):
        await self.memory.save_memory("payment callback fixed", 0.8, session_id="s1", source=self.source)
        await self.memory.update_working_summary("session summary", session_id="s1")

        source_ids = [record["id"] for record in self.memory._store["records"]]
        await self.memory._apply_profile_upsert("user-1", {
            "fact_key": "name",
            "fact_value": "阿明",
            "confidence": 0.9,
            "source_record_ids": [source_ids[0]],
        })
        await self.memory._apply_fact_upsert("user-1", {
            "content": "payment callback work finished",
            "fact_key": "payment_callback_done",
            "confidence": 0.88,
            "source_record_ids": [source_ids[0]],
        })

        snapshot = self.memory.get_memory_snapshot(source_id="user-1", session_id="s1")
        graph = self.memory.get_memory_graph_view(source_id="user-1", session_id="s1")

        self.assertEqual(snapshot["working_summaries"]["session_summary"], "session summary")
        self.assertEqual(snapshot["scope"]["source_id"], "user-1")
        self.assertTrue(any(record["type"] == "profile" for record in snapshot["records"]))
        self.assertTrue(any(record["type"] == "fact" for record in snapshot["records"]))
        self.assertTrue(all("embedding" not in record for record in snapshot["records"]))
        self.assertTrue(all("embedding" not in node for node in graph["nodes"]))
        self.assertTrue(all("source" in edge and "target" in edge for edge in graph["edges"]))

    async def test_structured_recall_returns_profile_fact_and_event_groups(self):
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

    async def test_housekeeping_prompt_receives_existing_memory_and_summary_context(self):
        await self.memory.update_working_summary("session summary for payment work", session_id="s1")
        await self.memory.save_memory("user likes black coffee", 0.8, session_id="s1", source=self.source)

        source_ids = [record["id"] for record in self.memory._store["records"]]
        await self.memory._apply_profile_upsert("user-1", {
            "fact_key": "coffee_preference",
            "fact_value": "black coffee",
            "confidence": 0.92,
            "source_record_ids": [source_ids[0]],
        })
        await self.memory._apply_fact_upsert("user-1", {
            "content": "payment callback cleanup is still open",
            "fact_key": "pay_fix",
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
        self._age_oldest_pending_episode()

        adapter = FakeAdapter()
        self.memory.set_housekeeping_adapter(adapter)

        await self.memory.run_housekeeping(None, "https://example.invalid/chat", "k", "m")

        payload = json.loads(adapter.last_messages[1]["content"])
        self.assertEqual(payload["user_id"], "user-1")
        self.assertEqual(payload["working_summary"]["session_summaries"]["s1"], "session summary for payment work")
        self.assertTrue(payload["existing_profiles"])
        self.assertEqual(payload["existing_profiles"][0]["fact_key"], "coffee_preference")
        self.assertTrue(payload["existing_facts"])
        self.assertEqual(payload["existing_facts"][0]["fact_key"], "pay_fix")
        self.assertGreaterEqual(len(payload["episodes"]), 5)

    async def test_memory_views_without_source_filter_return_all_records(self):
        source_a = DummySource(source_id="feishu-user")
        source_b = DummySource(source_id="desktop-app")
        await self.memory.save_memory("payment callback fixed", 0.8, session_id="s1", source=source_a)
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
        await self.memory.save_memory(
            "Durable relationship fact: User is my developer and friend.",
            0.8,
            session_id="s1",
            source=self.source,
            tags=["remember_knowledge", "remember_category:relationship"],
        )
        for idx in range(4):
            await self.memory.save_memory(f"filler episode {idx}", 0.3, session_id="s1", source=self.source)
        self._age_oldest_pending_episode()

        explicit_record = next(record for record in self.memory._store["records"] if "remember_knowledge" in record.get("tags", []))
        adapter = FakeAdapter()
        adapter.responses.append(json.dumps({
            "profile_upserts": [],
            "fact_upserts": [],
            "links": [],
        }, ensure_ascii=False))
        self.memory.set_housekeeping_adapter(adapter)

        await self.memory.run_housekeeping(None, "https://example.invalid/chat", "k", "m")

        profile_records = [
            record for record in self.memory._store["records"]
            if record.get("type") == "profile" and explicit_record["id"] in record.get("source_record_ids", [])
        ]
        payload = json.loads(adapter.last_messages[1]["content"])
        episode_payload = next(item for item in payload["episodes"] if item["id"] == explicit_record["id"])

        self.assertTrue(profile_records)
        self.assertTrue(episode_payload["hints"]["remember_requested"])
        self.assertEqual(episode_payload["hints"]["remember_category"], "relationship")


if __name__ == "__main__":
    unittest.main()
