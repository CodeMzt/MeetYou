import unittest

from core.context import ContextManager
from core.model_capabilities import ModelCapabilityResolver


class _FakeMemory:
    async def load_working_summary(self, session_id: str = "") -> str:
        return ""

    async def update_working_summary(self, context: str, session_id: str = "") -> str:
        return "ok"


class _FakeAdapter:
    def get_context_limit(self, model_name: str) -> int:
        return 10000


class ModelCapabilitiesTests(unittest.TestCase):
    def test_resolver_returns_budget_fields(self):
        budget = ModelCapabilityResolver.resolve(
            context_limit_info={"context_limit_tokens": 20000},
            model_options={"thinking": {"budget_tokens": 300}},
        ).to_dict()
        self.assertEqual(budget["context_window"], 20000)
        self.assertGreater(budget["max_output_tokens"], 0)
        self.assertEqual(budget["reserved_reasoning_tokens"], 300)
        self.assertGreater(budget["tool_result_budget"], 0)
        self.assertGreater(budget["target_input_tokens"], 0)

    def test_context_plan_keeps_pending_tool_call_chain(self):
        manager = ContextManager(_FakeMemory(), _FakeAdapter(), event_bus=None)
        history = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "call", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "user", "content": "older"},
        ]

        plan = __import__("asyncio").run(
            manager.build_context_plan(
                session_history_before_turn=history,
                current_turn_messages=[{"role": "user", "content": "now"}],
                auto_memory_message=None,
                policy_messages=[],
                proprioception_message=None,
                conversation_summary="",
                model="gpt-4o",
                provider_name="openai",
                api_url="https://api.openai.com/v1/responses",
                context_limit_override=120,
            )
        )
        assistant_tool = [m for m in plan["messages"] if m.get("role") == "assistant" and m.get("tool_calls")]
        self.assertEqual(len(assistant_tool), 1)


if __name__ == "__main__":
    unittest.main()
