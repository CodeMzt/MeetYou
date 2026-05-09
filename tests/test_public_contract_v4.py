import unittest

from core.public_contract import (
    EXECUTION_TARGET_CORE_LOCAL,
    EXECUTION_TARGET_ENDPOINT,
    EXECUTION_TARGETS,
    PUBLIC_ASSISTANT_MODES,
    normalize_execution_target,
    to_internal_assistant_mode,
    to_public_assistant_mode,
)


class PublicContractV4Tests(unittest.TestCase):
    def test_public_modes_include_v5_research_mode(self):
        self.assertEqual(PUBLIC_ASSISTANT_MODES, ("general", "automation", "research", "danxi"))
        for old_mode in ("normal", "auto"):
            self.assertEqual(to_public_assistant_mode(old_mode), "general")
            self.assertEqual(to_internal_assistant_mode(old_mode), "general")
        for retired_mode in ("documents", "study"):
            self.assertEqual(to_public_assistant_mode(retired_mode), "general")
            self.assertEqual(to_internal_assistant_mode(retired_mode), "general")
            self.assertEqual(to_internal_assistant_mode(retired_mode, fallback="normal"), "general")
        self.assertEqual(to_public_assistant_mode("research"), "research")
        self.assertEqual(to_internal_assistant_mode("research"), "research")
        self.assertEqual(to_public_assistant_mode("office"), "automation")
        self.assertEqual(to_internal_assistant_mode("office"), "automation")
        self.assertEqual(to_internal_assistant_mode("automation"), "automation")
        self.assertEqual(to_public_assistant_mode("danxi"), "danxi")
        self.assertEqual(to_internal_assistant_mode("danxi"), "danxi")

    def test_desktop_is_not_an_execution_target_alias(self):
        self.assertEqual(normalize_execution_target("desktop"), EXECUTION_TARGET_CORE_LOCAL)

    def test_execution_targets_are_v4_endpoint_terms(self):
        self.assertIn(EXECUTION_TARGET_CORE_LOCAL, EXECUTION_TARGETS)
        self.assertIn(EXECUTION_TARGET_ENDPOINT, EXECUTION_TARGETS)
        self.assertNotIn("core_only", EXECUTION_TARGETS)
        self.assertNotIn("specific_endpoint", EXECUTION_TARGETS)


if __name__ == "__main__":
    unittest.main()
