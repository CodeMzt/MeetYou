import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.memory_tools import MemoryTools


class _FakeMemory:
    def __init__(self):
        self.calls = []
        self._store = {
            "records": [
                {
                    "id": "ep_1",
                    "type": "episode",
                    "scope": {"user_id": "user-1", "session_id": "s1"},
                    "content": "User prefers black coffee in the morning.",
                    "canonical_text": "user prefers black coffee in the morning.",
                    "embedding": [1.0, 0.0],
                    "embedding_model": "fake",
                    "status": "active",
                    "created_at": "2026-04-06T00:00:00Z",
                    "last_updated_at": "2026-04-06T00:00:00Z",
                },
                {
                    "id": "ep_2",
                    "type": "episode",
                    "scope": {"user_id": "user-1", "session_id": "s1"},
                    "content": "User likes black coffee beans from Yunnan.",
                    "canonical_text": "user likes black coffee beans from yunnan.",
                    "embedding": [1.0, 1.0],
                    "embedding_model": "fake",
                    "status": "active",
                    "created_at": "2026-04-06T00:00:00Z",
                    "last_updated_at": "2026-04-06T00:00:01Z",
                },
            ]
        }
        self._embedding_model = "fake"

    async def save_memory(self, memory_text, text_emotion_intensity=1.0, session_id="", source=None, tags=None):
        self.calls.append({
            "memory_text": memory_text,
            "text_emotion_intensity": text_emotion_intensity,
            "session_id": session_id,
            "source": source,
            "tags": list(tags or []),
        })
        return "成功保存记忆, id=ep_1"

    def _resolve_user_id(self, source):
        if source is None:
            return "global"
        return getattr(source, "id", "") or "global"

    def _remember_category(self, record):
        return "preference"

    def _canonicalize(self, text):
        return str(text or "").strip().lower()

    async def _get_embedding(self, text):
        return [float(len(text or "")), 1.0]

    async def save_memory_graph(self):
        return None


class _FakeSource:
    def __init__(self, source_id: str = "user-1"):
        self.id = source_id


class MemoryToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_remember_knowledge_formats_preference_memory_candidate(self):
        memory = _FakeMemory()
        tools = MemoryTools(memory)

        raw = await tools.remember_knowledge(
            content="User prefers black coffee in the morning.",
            category="preference",
            session_id="s1",
            source=_FakeSource(),
        )

        payload = json.loads(raw)
        self.assertTrue(payload["saved"])
        self.assertEqual(payload["category"], "preference")
        self.assertEqual(payload["memory_text"], "Durable user preference: User prefers black coffee in the morning.")
        self.assertEqual(memory.calls[0]["session_id"], "s1")
        self.assertAlmostEqual(memory.calls[0]["text_emotion_intensity"], 0.72, places=2)
        self.assertIn("remember_knowledge", memory.calls[0]["tags"])
        self.assertIn("remember_category:preference", memory.calls[0]["tags"])
        self.assertEqual(payload["kind"], "object_operation")
        self.assertEqual(payload["object_type"], "memory")

    async def test_remember_knowledge_falls_back_to_fact_category(self):
        memory = _FakeMemory()
        tools = MemoryTools(memory)

        raw = await tools.remember_knowledge(
            content="User mentioned a durable detail.",
            category="unknown-category",
            importance=0.91,
        )

        payload = json.loads(raw)
        self.assertEqual(payload["category"], "fact")
        self.assertEqual(memory.calls[0]["memory_text"], "Durable memory candidate: User mentioned a durable detail.")
        self.assertAlmostEqual(memory.calls[0]["text_emotion_intensity"], 0.91, places=2)
        self.assertIn("remember_category:fact", memory.calls[0]["tags"])

    async def test_manage_memories_lists_and_edits_memory(self):
        memory = _FakeMemory()
        tools = MemoryTools(memory)

        listed = json.loads(await tools.manage_memories(action="list", source=_FakeSource()))
        self.assertEqual(listed["object_type"], "memory")
        self.assertEqual(listed["memory_count"], 2)

        detailed = json.loads(await tools.manage_memories(action="detail", memory_id="ep_1", source=_FakeSource()))
        self.assertEqual(detailed["objects"][0]["object_id"], "ep_1")

        updated = json.loads(
            await tools.manage_memories(
                action="edit",
                memory_id="ep_1",
                content="User now prefers hand brew coffee.",
                source=_FakeSource(),
            )
        )
        self.assertEqual(updated["status"], "success")
        self.assertEqual(updated["objects"][0]["preview"], "User now prefers hand brew coffee.")

    async def test_manage_memories_returns_ambiguous_candidates_and_can_delete_after_confirmation(self):
        memory = _FakeMemory()
        tools = MemoryTools(memory)

        ambiguous = json.loads(
            await tools.manage_memories(
                action="delete",
                query="black coffee",
                session_id="web:test",
                source=_FakeSource(),
            )
        )
        self.assertEqual(ambiguous["status"], "ambiguous")
        self.assertGreaterEqual(len(ambiguous["candidates"]), 2)

        with patch("tools.memory_tools.request_user_confirmation", AsyncMock(return_value=True)):
            deleted = json.loads(
                await tools.manage_memories(
                    action="delete",
                    memory_ids=["ep_1", "ep_2"],
                    session_id="web:test",
                    source=_FakeSource(),
                )
            )
        self.assertEqual(deleted["status"], "success")
        self.assertEqual(deleted["memory_count"], 2)
        self.assertEqual(memory._store["records"][0]["status"], "deleted")


if __name__ == "__main__":
    unittest.main()
