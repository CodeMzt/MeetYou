import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.model_capabilities import ModelCapabilityResolver


class ModelCapabilityResolverTests(unittest.TestCase):
    def test_resolve_budget_with_reasoning_enabled(self):
        resolver = ModelCapabilityResolver()
        budget = resolver.resolve(
            model="deepseek-reasoner",
            context_limit_info={"context_limit_tokens": 128000},
            length_policy={"reserved_response_tokens": 4096},
            model_options={"thinking": {"enabled": True, "budget_tokens": 3000}},
        ).to_dict()
        self.assertEqual(budget["context_window"], 128000)
        self.assertEqual(budget["max_output_tokens"], 4096)
        self.assertEqual(budget["reserved_reasoning_tokens"], 3000)
        self.assertGreater(budget["input_budget"], 0)

    def test_resolve_budget_with_reasoning_disabled(self):
        resolver = ModelCapabilityResolver()
        budget = resolver.resolve(
            model="gpt-4o-mini",
            context_limit_info={"context_limit_tokens": 8192},
            model_options={"thinking": {"enabled": False}},
        ).to_dict()
        self.assertEqual(budget["reserved_reasoning_tokens"], 0)
        self.assertGreaterEqual(budget["tool_result_budget"], 128)


if __name__ == "__main__":
    unittest.main()
