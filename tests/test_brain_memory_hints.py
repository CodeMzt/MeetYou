import json
import os
import sys
import types
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeClientSession:
    async def close(self):
        return None


sys.modules.setdefault("aiohttp", types.SimpleNamespace(ClientSession=_FakeClientSession))

from adapters.base import StreamEvent
from core.brain import Brain


class FakeAdapter:
    def __init__(self):
        self.messages_seen = []

    async def stream_chat(self, session, api_url, api_key, model, messages, tools=None, **kwargs):
        self.messages_seen.append(messages)
        yield StreamEvent(type="text", text="ok")


class FakeToolsManager:
    def __init__(self):
        self.calls = []

    def get_all_tools(self):
        return []

    async def call_tool(self, tool_name, tool_args, session_id="", source=None, tool_activity_callback=None):
        self.calls.append({
            "tool_name": tool_name,
            "tool_args": dict(tool_args),
            "session_id": session_id,
        })
        return json.dumps({
            "query": tool_args.get("query", ""),
            "found": False,
            "profile": [],
            "tasks": [],
            "recent_events": [],
        }, ensure_ascii=False)


class FakeContextManager:
    def __init__(self):
        self.proprioception_info = {"ui_info": "", "running_apps": [], "last_update_time": 0}
        self.updates = []

    async def load_context(self, session_id: str = "") -> str:
        return "persisted context"

    async def update_context(self, context: str, session_id: str = "", source=None) -> str:
        self.updates.append({"context": context, "session_id": session_id})
        return "ok"

    async def trim_history(self, chat_history, model, session, api_url, api_key, reserve_ratio: float = 0.75):
        return None


class BrainMemoryHintTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.adapter = FakeAdapter()
        self.tools_manager = FakeToolsManager()
        self.context_manager = FakeContextManager()
        self.brain = Brain(
            self.adapter,
            self.tools_manager,
            self.context_manager,
            event_bus=None,
            exception_router=None,
        )
        await self.brain.init_brain("system prompt")

    async def asyncTearDown(self):
        await self.brain.close_brain()

    async def test_injects_memory_trigger_hint_for_profile_preference_and_project_signals(self):
        async for _ in self.brain.input_brain(
            "session-hint-1",
            {"role": "user", "content": "My name is Alex, I prefer black coffee, and I am still working on the payment callback bug."},
            "key",
            "url",
            "model",
        ):
            pass

        hints = [
            str(msg.get("content"))
            for msg in self.adapter.messages_seen[0]
            if msg.get("role") == "system" and "[Memory Trigger Hint]" in str(msg.get("content"))
        ]
        self.assertEqual(len(hints), 1)
        self.assertIn("profile", hints[0])
        self.assertIn("preference", hints[0])
        self.assertIn("project", hints[0])
        self.assertIn("remember_knowledge", hints[0])

    async def test_does_not_inject_memory_trigger_hint_for_temporary_state(self):
        async for _ in self.brain.input_brain(
            "session-hint-2",
            {"role": "user", "content": "I feel sleepy today and the weather is weird."},
            "key",
            "url",
            "model",
        ):
            pass

        hints = [
            str(msg.get("content"))
            for msg in self.adapter.messages_seen[0]
            if msg.get("role") == "system" and "[Memory Trigger Hint]" in str(msg.get("content"))
        ]
        self.assertEqual(hints, [])

    async def test_suppresses_memory_trigger_hint_for_memory_lookup_question(self):
        async for _ in self.brain.input_brain(
            "session-hint-3",
            {"role": "user", "content": "Do you remember my name?"},
            "key",
            "url",
            "model",
        ):
            pass

        hints = [
            str(msg.get("content"))
            for msg in self.adapter.messages_seen[0]
            if msg.get("role") == "system" and "[Memory Trigger Hint]" in str(msg.get("content"))
        ]
        self.assertEqual(hints, [])


if __name__ == "__main__":
    unittest.main()
