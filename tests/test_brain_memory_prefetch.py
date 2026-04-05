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
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_all_tools(self):
        return []

    async def call_tool(self, tool_name, tool_args, session_id="", source=None, tool_activity_callback=None):
        self.calls.append({
            "tool_name": tool_name,
            "tool_args": dict(tool_args),
            "session_id": session_id,
        })
        return json.dumps(self.payload, ensure_ascii=False)


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


class BrainMemoryPrefetchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.adapter = FakeAdapter()
        self.tools_manager = FakeToolsManager({
            "query": "What is my name?",
            "found": True,
            "profile": [{"fact_key": "name", "fact_value": "A Ming", "score": 0.91}],
            "facts": [],
            "recent_events": [],
        })
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

    async def test_prefetches_structured_memory_for_regular_user_turn(self):
        events = []
        async for event in self.brain.input_brain(
            "session-1",
            {"role": "user", "content": "What is my name?"},
            "key",
            "url",
            "model",
        ):
            events.append(event)

        self.assertEqual([event.type for event in events], ["answer_text", "usage", "done"])
        self.assertEqual(
            "".join(event.text or "" for event in events if event.type == "answer_text"),
            "ok",
        )
        self.assertEqual(len(self.tools_manager.calls), 1)
        self.assertEqual(self.tools_manager.calls[0]["tool_name"], "search_memory")
        self.assertEqual(self.tools_manager.calls[0]["tool_args"]["query"], "What is my name?")
        self.assertTrue(any(
            msg.get("role") == "system" and '"fact_value": "A Ming"' in str(msg.get("content"))
            for msg in self.adapter.messages_seen[0]
        ))
        self.assertTrue(any(
            msg.get("role") == "system" and "[Tool Judgment Policy]" in str(msg.get("content"))
            for msg in self.adapter.messages_seen[0]
        ))
        usage_events = [event for event in events if event.type == "usage"]
        self.assertEqual(len(usage_events), 1)
        self.assertEqual(usage_events[0].usage["session_id"], "session-1")
        self.assertEqual(self.context_manager.updates[-1]["session_id"], "session-1")

    async def test_skips_prefetch_for_short_ack_turn(self):
        self.tools_manager.calls.clear()

        async for _ in self.brain.input_brain(
            "session-2",
            {"role": "user", "content": "ok"},
            "key",
            "url",
            "model",
        ):
            pass

        self.assertEqual(self.tools_manager.calls, [])
        self.assertEqual(self.context_manager.updates[-1]["session_id"], "session-2")


if __name__ == "__main__":
    unittest.main()
