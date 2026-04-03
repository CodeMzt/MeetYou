import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.assistant_modes import AssistantModeManager


class _FakeConfig:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key: str):
        return self._values.get(key)


class AssistantModeManagerTests(unittest.TestCase):
    def test_defaults_normal_for_ordinary_conversation(self):
        manager = AssistantModeManager(_FakeConfig())

        route = manager.route(
            {
                "content": "Can you help me think through my plan for tomorrow?",
                "metadata": {},
            },
            session_metadata={},
            source=SimpleNamespace(kind="desktop", id="desktop-user"),
        )

        self.assertEqual(route.current_mode, "normal")
        self.assertEqual(route.requested_mode, "normal")
        self.assertEqual(route.source_profile, "workspace_local")

    def test_routes_documents_for_local_paths(self):
        manager = AssistantModeManager(_FakeConfig())

        route = manager.route(
            {
                "content": "Analyze E:/work/demo/report.md and explain the repo directory tree.",
                "metadata": {},
            },
            session_metadata={},
            source=SimpleNamespace(kind="desktop", id="desktop-user"),
        )

        self.assertEqual(route.current_mode, "documents")
        self.assertEqual(route.source_profile, "workspace_local")
        self.assertIn("documents", route.route_reason)
        self.assertTrue("local_path" in route.route_reason or "directory" in route.route_reason)

    def test_routes_normal_for_lightweight_web_queries(self):
        manager = AssistantModeManager(_FakeConfig())

        route = manager.route(
            {
                "content": "What changed today in https://docs.python.org and what is the latest guidance?",
                "metadata": {},
            },
            session_metadata={},
            source=SimpleNamespace(kind="web", id="browser-tab"),
        )

        self.assertEqual(route.current_mode, "normal")
        self.assertEqual(route.source_profile, "workspace_local")
        self.assertIn("direct_url", route.route_reason)

    def test_routes_research_for_deep_research_queries(self):
        manager = AssistantModeManager(_FakeConfig())

        route = manager.route(
            {
                "content": "Create a research report with citations and track source updates for OpenAI policy changes.",
                "metadata": {},
            },
            session_metadata={},
            source=SimpleNamespace(kind="web", id="browser-tab"),
        )

        self.assertEqual(route.current_mode, "research")
        self.assertEqual(route.source_profile, "policy_global")
        self.assertIn("research", route.route_reason)

    def test_routes_office_and_study_without_sticky_preferred_override(self):
        manager = AssistantModeManager(_FakeConfig())

        office_route = manager.route(
            {
                "content": "Draft a meeting agenda and follow-up email for tomorrow's schedule sync.",
                "metadata": {},
            },
            session_metadata={"current_mode": "documents"},
            source=SimpleNamespace(kind="feishu", id="chat-1"),
        )
        study_route = manager.route(
            {
                "content": "Quiz me on distributed systems and generate flashcards from my notes.",
                "metadata": {},
            },
            session_metadata={"current_mode": "office", "preferred_mode": "research"},
            source=SimpleNamespace(kind="desktop", id="desktop-user"),
        )

        self.assertEqual(office_route.current_mode, "office")
        self.assertEqual(study_route.requested_mode, "normal")
        self.assertEqual(study_route.current_mode, "study")
        self.assertEqual(study_route.source_profile, "study_materials")

    def test_preferred_mode_override_applies_for_single_request(self):
        manager = AssistantModeManager(_FakeConfig())

        route = manager.route(
            {
                "content": "Please summarize this folder.",
                "metadata": {"preferred_mode": "research"},
            },
            session_metadata={"current_mode": "documents"},
            source=SimpleNamespace(kind="desktop", id="desktop-user"),
        )

        self.assertEqual(route.requested_mode, "research")
        self.assertEqual(route.current_mode, "research")
        self.assertIn("Preferred mode override requested", route.route_reason)

    def test_preferred_normal_starts_in_normal_mode(self):
        manager = AssistantModeManager(_FakeConfig())

        route = manager.route(
            {
                "content": "Please help me browse around this topic normally first.",
                "metadata": {"preferred_mode": "normal"},
            },
            session_metadata={"current_mode": "documents"},
            source=SimpleNamespace(kind="desktop", id="desktop-user"),
        )

        self.assertEqual(route.requested_mode, "normal")
        self.assertEqual(route.current_mode, "normal")
        self.assertIn("Preferred mode selected: normal", route.route_reason)

    def test_trusted_write_roots_and_primary_sources(self):
        with tempfile.TemporaryDirectory() as tmp_dir, tempfile.TemporaryDirectory() as other_dir:
            manager = AssistantModeManager(
                _FakeConfig(
                    {
                        "trusted_write_roots": json.dumps([tmp_dir]),
                    }
                )
            )

            trusted_file = Path(tmp_dir) / "docs" / "summary.md"
            other_file = Path(other_dir) / "notes.md"

            self.assertTrue(manager.is_trusted_write_path(str(trusted_file)))
            self.assertFalse(manager.is_trusted_write_path(str(other_file)))
            self.assertTrue(manager.is_primary_source("https://docs.python.org/3/library/pathlib.html", "tech_updates"))


if __name__ == "__main__":
    unittest.main()
