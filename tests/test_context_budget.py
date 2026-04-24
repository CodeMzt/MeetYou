import unittest

from core.context import ContextManager


class _FakeMemory:
    async def load_working_summary(self, session_id: str = "") -> str:
        return ""

    async def update_working_summary(self, context: str, session_id: str = "") -> str:
        return context


class _FakeAdapter:
    def get_context_limit(self, model_name: str) -> int:
        return 1200


class ContextBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_tool_call_chain_stays_pinned_during_budget_trim(self):
        manager = ContextManager(_FakeMemory(), _FakeAdapter(), event_bus=None)
        pending_tool_call = {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "pending-1", "name": "read_local_documents", "arguments": "{}"}],
        }
        history = [
            {"role": "user", "content": f"old prefix {index} " + ("x" * 180)}
            for index in range(12)
        ]
        history.insert(2, pending_tool_call)
        history.extend(
            {"role": "user", "content": f"tail {index} " + ("y" * 180)}
            for index in range(12)
        )

        plan = await manager.build_context_plan(
            session_history_before_turn=history,
            current_turn_messages=[{"role": "user", "content": "now"}],
            auto_memory_message=None,
            policy_messages=[],
            proprioception_message=None,
            model="gpt-4o",
            provider_name="openai",
            context_limit_override=1200,
        )

        planned_history = plan["messages"]
        self.assertTrue(
            any(
                any(tool_call.get("id") == "pending-1" for tool_call in message.get("tool_calls") or [])
                for message in planned_history
            )
        )


if __name__ == "__main__":
    unittest.main()
