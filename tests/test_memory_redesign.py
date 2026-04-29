import hashlib
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from core.context import ContextManager
from core.runtime_context import bind_event_context, reset_event_context
from tools.memory_tools import MemoryTools
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
    def __init__(self, kind: str = "cli", source_id: str = "user-1", metadata: dict | None = None):
        self.kind = kind
        self.id = source_id
        self.display_name = source_id
        self.metadata = dict(metadata or {})


class FakeAdapter:
    def __init__(self):
        self.responses: list[str] = []
        self.last_messages = None

    async def chat(self, session, api_url, api_key, model, messages, tools=None, **kwargs):
        self.last_messages = messages
        if not self.responses:
            return {"content": '{"profile_upserts": [], "fact_upserts": [], "links": []}'}
        return {"content": self.responses.pop(0)}


class SummaryAdapter:
    def __init__(self, content: str = "condensed summary"):
        self.content = content
        self.last_messages = None

    async def chat(self, session, api_url, api_key, model, messages, tools=None, **kwargs):
        self.last_messages = messages
        return {"content": self.content}

    def get_context_limit(self, model_name: str) -> int:
        del model_name
        return 128000


class FakeContextPoolService:
    def __init__(self):
        self.calls: list[dict] = []

    def query_by_public_ids(self, **kwargs):
        self.calls.append(dict(kwargs))
        return [
            {
                "context_id": "ctx_feishu_1",
                "item_type": "turn",
                "role": "user",
                "content": "Feishu user asked about payment callback retries.",
                "score": 0.91,
                "same_session": False,
                "same_thread": False,
                "same_workspace": False,
                "workspace_tags": ["remote"],
                "metadata": {"endpoint_id": "feishu"},
                "created_at": "2026-04-24T00:00:00Z",
            }
        ]


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

    async def test_context_plan_uses_summary_layer_and_length_policy(self):
        adapter = SummaryAdapter()
        context_manager = ContextManager(self.memory, adapter=adapter, event_bus=None)
        await context_manager.update_context("session summary", session_id="s1")

        plan = await context_manager.build_context_plan(
            session_history_before_turn=[
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "old user"},
                {"role": "assistant", "content": "old assistant"},
                {"role": "tool", "content": "tool noise"},
            ],
            current_turn_messages=[{"role": "user", "content": "new request"}],
            auto_memory_message={"role": "system", "content": "[自动检索到的相关长期记忆]\n{}"},
            policy_messages=[{"role": "system", "content": "policy"}],
            proprioception_message={"role": "system", "content": "cursor"},
            conversation_summary="session summary",
            route_context={"should_preload_context": True, "prefer_live_web": True},
            requested_mode="auto",
            model="gpt-5.4",
            provider_name="openai",
            api_url="https://api.openai.com/v1/responses",
            context_limit_override=240,
        )

        self.assertEqual(plan["length_policy"]["provider_family"], "openai")
        self.assertTrue(plan["layers"]["conversation_summary"])
        self.assertTrue(any("[对话摘要层]" in message.get("content", "") for message in plan["messages"]))
        self.assertLessEqual(plan["breakdown"]["total"], plan["length_policy"]["target_input_tokens"])

    async def test_context_plan_includes_context_pool_recall(self):
        context_pool = FakeContextPoolService()
        context_manager = ContextManager(self.memory, adapter=SummaryAdapter(), event_bus=None)
        context_manager.set_context_pool_service(context_pool, principal_getter=lambda: "principal-1")

        token = bind_event_context(
            session_id="desktop-session",
            thread_id="desktop-thread",
            active_workspace_id="desktop-main",
        )
        try:
            plan = await context_manager.build_context_plan(
                session_history_before_turn=[],
                current_turn_messages=[{"role": "user", "content": "continue the payment callback topic"}],
                auto_memory_message=None,
                policy_messages=[],
                proprioception_message=None,
                route_context={},
                requested_mode="general",
                model="gpt-5.4",
                provider_name="openai",
                api_url="https://api.openai.com/v1/responses",
                context_limit_override=4096,
            )
        finally:
            reset_event_context(token)

        self.assertTrue(plan["layers"]["context_pool"])
        self.assertTrue(any("[ContextPool]" in message.get("content", "") for message in plan["messages"]))
        self.assertEqual(context_pool.calls[0]["active_workspace_id"], "desktop-main")
        self.assertEqual(context_pool.calls[0]["session_id"], "desktop-session")
        self.assertGreater(plan["breakdown"]["context_pool"], 0)

    async def test_trim_history_persists_summary_without_writing_system_message_into_history(self):
        adapter = SummaryAdapter("updated summary")
        context_manager = ContextManager(self.memory, adapter=adapter, event_bus=None)
        history = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "first turn " * 30},
            {"role": "assistant", "content": "first answer " * 30},
            {"role": "tool", "content": "tool output " * 40},
            {"role": "assistant", "content": "second answer " * 30},
        ]

        result = await context_manager.trim_history(
            history,
            "gpt-5.4",
            None,
            "https://api.openai.com/v1/responses",
            "key",
            context_limit_override=240,
            session_id="s1",
            provider_name="openai",
            preserve_message_count=1,
        )

        self.assertEqual(history[0]["content"], "system prompt")
        self.assertEqual(sum(1 for message in history if message.get("role") == "system"), 1)
        self.assertEqual(result["conversation_summary"], "updated summary")
        self.assertTrue(result["compression"]["triggered"])
        self.assertEqual(result["compression"]["level"], "history_summary")
        self.assertEqual(await context_manager.load_context("s1"), "updated summary")

    async def test_idle_heartbeat_compaction_preserves_recent_turns_and_persists_summary(self):
        adapter = SummaryAdapter("idle heartbeat summary")
        context_manager = ContextManager(self.memory, adapter=adapter, event_bus=None)
        history = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "old request"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "middle request"},
            {"role": "assistant", "content": "middle answer"},
            {"role": "user", "content": "recent request"},
            {"role": "assistant", "content": "recent answer"},
        ]

        result = await context_manager.compact_history_for_idle_heartbeat(
            history,
            model="gpt-5.4",
            session=None,
            api_url="https://api.openai.com/v1/responses",
            api_key="key",
            session_id="s1",
            provider_name="openai",
            preserve_message_count=1,
            recent_message_count=2,
        )

        self.assertTrue(result["compression"]["triggered"])
        self.assertEqual(result["compression"]["level"], "idle_heartbeat_summary")
        self.assertEqual(result["conversation_summary"], "idle heartbeat summary")
        self.assertEqual([message["content"] for message in history], ["system prompt", "recent request", "recent answer"])
        self.assertEqual(await context_manager.load_context("s1"), "idle heartbeat summary")

    async def test_context_estimation_counts_provider_items_and_tool_calls(self):
        context_manager = ContextManager(self.memory, adapter=SummaryAdapter(), event_bus=None)

        plain_tokens = context_manager.estimate_message_tokens(
            {"role": "assistant", "content": "hello"}
        )
        structured_tokens = context_manager.estimate_message_tokens(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "type": "function",
                        "id": "call-1",
                        "function": {"name": "lookup_profile", "arguments": '{"name":"Alex"}'},
                    }
                ],
                "provider_items": [
                    {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque"},
                    {"type": "function_call", "id": "fc_1", "call_id": "call-1"},
                ],
            }
        )

        self.assertGreater(structured_tokens, plain_tokens)

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

    async def test_memory_store_persists_schema_version_and_revision(self):
        await self.memory.save_memory("payment callback needs fix", 0.8, session_id="s1", source=self.source)

        payload = json.loads(self.memory_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["metadata"]["schema_version"], "2")
        self.assertGreaterEqual(payload["metadata"]["revision"], 1)
        self.assertTrue((self.memory_path.parent / f"{self.memory_path.name}.bak").exists())

    async def test_memory_store_recovers_from_backup_when_primary_is_corrupted(self):
        await self.memory.save_memory("payment callback needs fix", 0.8, session_id="s1", source=self.source)
        await self.memory.close_memory()
        self.memory_path.write_text('{"records": "broken"}', encoding="utf-8")

        fresh_memory = DummyMemory()
        await fresh_memory.init_memory(self.config)
        try:
            self.assertEqual(len(fresh_memory._store["records"]), 1)
            repaired = json.loads(self.memory_path.read_text(encoding="utf-8"))
            self.assertEqual(repaired["metadata"]["schema_version"], "2")
            self.assertEqual(len(repaired["records"]), 1)
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
        self.assertIn("layers", snapshot)
        self.assertEqual(snapshot["layers"]["conversation_summary"]["session_summary"], "session summary")
        self.assertTrue(snapshot["layers"]["durable_memory"]["profile"])
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
        self.assertTrue(payload["scope"]["session_aware"])
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

    async def test_principal_scoped_memory_cross_endpoint_recall_preserves_source_attribution(self):
        feishu_source = DummySource(kind="feishu", source_id="feishu-user", metadata={"endpoint_id": "feishu-bot"})
        desktop_source = DummySource(kind="web", source_id="desktop-app", metadata={"endpoint_id": "desktop-app"})

        feishu_token = bind_event_context(
            principal_key="self",
            principal_id="principal-row-1",
            source=feishu_source,
            endpoint_id="feishu-bot",
            workspace_id="personal",
            active_workspace_id="personal",
            thread_id="thr_feishu",
        )
        try:
            await self.memory.save_memory("payment callback retry failures came from Feishu", 0.8, session_id="feishu-session", source=feishu_source)
        finally:
            reset_event_context(feishu_token)

        desktop_token = bind_event_context(
            principal_key="self",
            principal_id="principal-row-1",
            source=desktop_source,
            endpoint_id="desktop-app",
            workspace_id="desktop-main",
            active_workspace_id="desktop-main",
            thread_id="thr_desktop",
        )
        try:
            payload = json.loads(
                await self.memory.recall_memory_structured(
                    "payment callback retry failures",
                    session_id="desktop-session",
                    source=desktop_source,
                    reinforce=False,
                )
            )
        finally:
            reset_event_context(desktop_token)

        self.assertTrue(payload["recent_events"])
        event = payload["recent_events"][0]
        self.assertEqual(event["scope"]["user_id"], "self")
        self.assertEqual(event["source_attribution"]["source_id"], "feishu-user")
        self.assertEqual(event["source_attribution"]["endpoint_id"], "feishu-bot")
        source_view = self.memory.get_memory_snapshot(source_id="feishu-user")
        self.assertTrue(any(record["source_attribution"]["source_id"] == "feishu-user" for record in source_view["records"]))

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

        self.assertTrue(profile_records)
        self.assertIsNone(adapter.last_messages)
        self.assertNotIn("pending_consolidation", explicit_record.get("tags", []))

    async def test_explicit_memory_write_is_strongly_consistent(self):
        tools = MemoryTools(self.memory)

        payload = json.loads(
            await tools.remember_knowledge(
                "I prefer black coffee.",
                category="preference",
                session_id="s1",
                source=self.source,
            )
        )
        recall = json.loads(
            await self.memory.recall_memory_structured("what coffee do I prefer", session_id="s1", source=self.source)
        )

        self.assertTrue(payload["saved"])
        self.assertTrue(recall["profile"])
        self.assertIn("black coffee", recall["profile"][0]["fact_value"])

    async def test_session_aware_recall_ranks_same_session_without_hiding_other_sessions(self):
        await self.memory.save_memory("payment callback still needs fix", 0.8, session_id="s1", source=self.source)
        await self.memory.save_memory("user likes pour over coffee", 0.8, session_id="s2", source=self.source)

        same_session = json.loads(
            await self.memory.recall_memory_structured("coffee", session_id="s1", source=self.source, reinforce=False)
        )
        cross_session = json.loads(
            await self.memory.recall_memory_structured("coffee", session_id="", source=self.source, reinforce=False)
        )

        self.assertTrue(any("coffee" in item["content"].lower() for item in same_session["recent_events"]))
        self.assertTrue(any("coffee" in item["content"].lower() for item in cross_session["recent_events"]))

    async def test_workspace_tags_affect_memory_ranking_and_source_labels(self):
        await self.memory.save_memory("payment callback issue in global scope", 0.8, session_id="s1", source=self.source)

        study_token = bind_event_context(workspace_id="study")
        try:
            await self.memory.save_memory("payment callback issue in study workspace", 0.8, session_id="s1", source=self.source)
        finally:
            reset_event_context(study_token)

        desktop_token = bind_event_context(workspace_id="desktop-main")
        try:
            await self.memory.save_memory("payment callback issue in desktop workspace", 0.8, session_id="s1", source=self.source)
            results = await self.memory.search_records("payment callback issue", session_id="s1", source=self.source)
            payload = json.loads(
                await self.memory.recall_memory_structured("payment callback issue", session_id="s1", source=self.source, reinforce=False)
            )
            text = await self.memory.recall_memory("payment callback issue", session_id="s1", source=self.source, reinforce=False)
        finally:
            reset_event_context(desktop_token)

        self.assertGreaterEqual(len(results), 2)
        self.assertEqual(results[0]["workspace_match"], "current")
        self.assertEqual(results[0]["source_label"], "当前工作区:desktop-main")
        self.assertTrue(any(item["workspace_match"] == "global" for item in results))
        self.assertTrue(any(item.get("source_label") == "当前工作区:desktop-main" for item in payload["recent_events"]))
        self.assertIn("[来源: 当前工作区:desktop-main]", text)

    async def test_memory_record_status_update_and_delete(self):
        await self.memory.save_memory("user likes black coffee", 0.8, session_id="s1", source=self.source)
        memory_id = self.memory._store["records"][-1]["id"]

        invalidated = await self.memory.update_record_status(memory_id, "invalidated")
        active_snapshot = self.memory.get_memory_snapshot(include_invalidated=False)
        full_snapshot = self.memory.get_memory_snapshot(include_invalidated=True)

        self.assertEqual(invalidated["memory_id"], memory_id)
        self.assertEqual(invalidated["status"], "invalidated")
        self.assertFalse(any(record["id"] == memory_id for record in active_snapshot["records"]))
        self.assertTrue(any(record["id"] == memory_id and record["status"] == "invalidated" for record in full_snapshot["records"]))

        restored = await self.memory.update_record_status(memory_id, "active")
        self.assertEqual(restored["record"]["status"], "active")

        await self.memory.save_memory("user likes pour over coffee", 0.8, session_id="s1", source=self.source)
        other_id = self.memory._store["records"][-1]["id"]
        self.memory._store["edges"].append(
            {
                "from_id": memory_id,
                "to_id": other_id,
                "semantic_sim": 0.99,
                "same_entity": False,
                "same_project": False,
                "derived_from": False,
                "contradicts": False,
                "updated_at": dt_to_iso(utcnow()),
            }
        )

        deleted = await self.memory.delete_record(memory_id)

        self.assertTrue(deleted["deleted"])
        self.assertFalse(any(record.get("id") == memory_id for record in self.memory._store["records"]))
        self.assertFalse(
            any(edge.get("from_id") == memory_id or edge.get("to_id") == memory_id for edge in self.memory._store["edges"])
        )

    async def test_memory_record_mutation_rejects_missing_ids(self):
        with self.assertRaises(KeyError):
            await self.memory.update_record_status("missing-memory", "invalidated")
        with self.assertRaises(KeyError):
            await self.memory.delete_record("missing-memory")
        with self.assertRaises(ValueError):
            await self.memory.update_record_status("missing-memory", "archived")


if __name__ == "__main__":
    unittest.main()
