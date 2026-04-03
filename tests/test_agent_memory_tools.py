import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.agent_memory import AgentMemoryTools


class _FakeMemory:
    def __init__(self):
        self.calls = []

    async def save_memory(self, memory_text, text_emotion_intensity=1.0, session_id="", source=None, tags=None):
        self.calls.append({
            "memory_text": memory_text,
            "text_emotion_intensity": text_emotion_intensity,
            "session_id": session_id,
            "source": source,
            "tags": list(tags or []),
        })
        return "saved"


class _FakeSource:
    def __init__(self, source_id: str = "user-1"):
        self.id = source_id


class AgentMemoryToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_remember_knowledge_formats_preference_memory_candidate(self):
        memory = _FakeMemory()
        tools = AgentMemoryTools(memory)

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

    async def test_remember_knowledge_falls_back_to_fact_category(self):
        memory = _FakeMemory()
        tools = AgentMemoryTools(memory)

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


if __name__ == "__main__":
    unittest.main()
