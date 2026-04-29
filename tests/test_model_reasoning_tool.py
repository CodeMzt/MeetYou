import json
import unittest

from tools import system_tools


class ModelReasoningToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_manage_model_reasoning_reads_and_updates_global_defaults(self):
        updates = []

        async def provider():
            return {"scope": "global_default", "settings": {"thinking_enabled": True, "thinking_effort": "medium"}}

        async def updater(payload):
            updates.append(dict(payload))
            return {"applied_keys": sorted(payload)}

        system_tools.set_model_reasoning_settings_provider(provider)
        system_tools.set_model_reasoning_settings_updater(updater)

        current = json.loads(await system_tools.manage_model_reasoning("get"))
        self.assertTrue(current["ok"])
        self.assertEqual(current["settings"]["thinking_effort"], "medium")

        result = json.loads(
            await system_tools.manage_model_reasoning(
                "set",
                thinking_enabled=False,
                thinking_effort="high",
                thinking_budget_tokens=4096,
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(updates[-1], {"thinking_enabled": False, "thinking_effort": "", "thinking_budget_tokens": 0})
