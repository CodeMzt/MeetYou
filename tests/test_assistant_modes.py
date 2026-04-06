import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.assistant_modes import AssistantModeManager
from core.semantic_router import SemanticRouteDecision


class _FakeConfig:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key: str):
        return self._values.get(key)


class _InjectedSemanticRouter:
    def analyze(
        self,
        content: str,
        *,
        current_mode: str = "",
        source_kind: str = "",
        sticky_current_mode: bool = True,
        enable_keyword_fallback: bool = True,
    ):
        del content, current_mode, source_kind, sticky_current_mode, enable_keyword_fallback
        return SemanticRouteDecision(
            mode="research",
            confidence="high",
            reason="Injected semantic router selected research.",
            source_profile="finance_macro",
            active_skills=["research_grounding"],
            should_preload_context=False,
            prefer_live_web=True,
            signals=["injected_semantic"],
            adapter_name="injected_test_router",
            used_keyword_fallback=False,
        )

    def should_activate_skill(self, skill_name: str, content: str, *, mode: str = "", enable_keyword_fallback: bool = True):
        del content, mode, enable_keyword_fallback
        return skill_name == "research_grounding"

    def classify_source_profile(self, text: str, *, enable_keyword_fallback: bool = True) -> str:
        del text, enable_keyword_fallback
        return "finance_macro"

    def should_preload_context(self, query: str, goal: str = "", *, enable_keyword_fallback: bool = True) -> bool:
        del query, goal, enable_keyword_fallback
        return False

    def is_live_web_query(self, query: str, *, enable_keyword_fallback: bool = True) -> bool:
        del query, enable_keyword_fallback
        return True


def _populate_skill_dir(target_dir: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    source_dir = repo_root / "prompt" / "SKILL"
    target_dir.mkdir(parents=True, exist_ok=True)
    for skill_name in (
        "task-recognition",
        "research-grounding",
        "study-coaching",
        "mode-normal",
        "mode-documents",
        "mode-research",
        "mode-office",
        "mode-study",
    ):
        (target_dir / skill_name).write_text((source_dir / skill_name).read_text(encoding="utf-8"), encoding="utf-8")


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
        self.assertIn("research_grounding", route.active_skills or [])

    def test_composes_mode_and_skill_prompts(self):
        manager = AssistantModeManager(_FakeConfig())

        prompt_text = manager.get_prompt_for_mode("research")

        self.assertIn("[Research Mode]", prompt_text)
        self.assertIn("[Research Mode Skill]", prompt_text)
        self.assertIn("[Research Grounding Skill]", prompt_text)
        self.assertIn("evidence-first research posture", prompt_text)
        self.assertIn("Reason about freshness explicitly", prompt_text)
        self.assertIn("Purpose:", prompt_text)
        self.assertIn("When to use:", prompt_text)
        self.assertIn("Boundaries:", prompt_text)

    def test_resolves_prompt_paths_from_repository_root(self):
        manager = AssistantModeManager(_FakeConfig())
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                os.chdir(tmp_dir)
                prompt_text = manager.get_prompt_for_mode("study")
            finally:
                os.chdir(previous_cwd)

        self.assertIn("[Study Mode]", prompt_text)
        self.assertIn("Start with the shared basic tools", prompt_text)
        self.assertIn("[Study Coaching Skill]", prompt_text)

    def test_defaults_skill_prompt_dir_to_prompt_skill(self):
        manager = AssistantModeManager(_FakeConfig())

        self.assertEqual(manager._mode_registry()["skill_prompt_dir"], "prompt/SKILL")

    def test_skill_prompts_live_only_under_prompt_skill(self):
        repo_root = Path(__file__).resolve().parent.parent

        self.assertFalse((repo_root / "prompt" / "skills").exists())
        for skill_name in (
            "task-recognition",
            "research-grounding",
            "study-coaching",
            "mode-normal",
            "mode-documents",
            "mode-research",
            "mode-office",
            "mode-study",
        ):
            skill_path = repo_root / "prompt" / "SKILL" / skill_name
            self.assertTrue(skill_path.is_file())
            skill_text = skill_path.read_text(encoding="utf-8")
            self.assertIn("Purpose:", skill_text)
            if skill_name.startswith("mode-"):
                self.assertIn("Tool strategy:", skill_text)
            else:
                self.assertIn("When to use:", skill_text)
                self.assertIn("Tool paths:", skill_text)
            self.assertIn("Boundaries:", skill_text)

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

    def test_task_recognition_skill_extends_study_mode_tools(self):
        manager = AssistantModeManager(_FakeConfig())

        route = manager.route(
            {
                "content": "Quiz me on distributed systems and remind me to review chapter 3 tomorrow.",
                "metadata": {},
            },
            session_metadata={},
            source=SimpleNamespace(kind="desktop", id="desktop-user"),
        )

        self.assertEqual(route.current_mode, "study")
        self.assertIn("task_recognition", route.active_skills or [])
        self.assertIn("manage_tasks", route.tool_bundle)
        self.assertIn("manage_scheduled_tasks", route.tool_bundle)
        prompt_text = manager.assemble_prompt_for_route(route.to_dict())
        self.assertIn("[Study Mode Skill]", prompt_text)
        self.assertIn("[Task Recognition Skill]", prompt_text)
        self.assertIn("[Study Coaching Skill]", prompt_text)

    def test_research_route_includes_shared_basic_web_and_memory_tools(self):
        manager = AssistantModeManager(_FakeConfig())

        route = manager.route(
            {
                "content": "Create a research report with citations about the latest browser policies.",
                "metadata": {},
            },
            session_metadata={},
            source=SimpleNamespace(kind="web", id="browser-tab"),
        )

        self.assertEqual(route.current_mode, "research")
        self.assertIn("search_memory", route.tool_bundle)
        self.assertIn("search_web", route.tool_bundle)
        self.assertIn("read_web_page", route.tool_bundle)
        self.assertIn("list_skills", route.tool_bundle)
        self.assertIn("load_skill", route.tool_bundle)
        self.assertIn("create_skill", route.tool_bundle)
        self.assertTrue(route.authorization_policy["read_only"])
        self.assertIn("mode:research", route.authorization_policy["policy_sources"])

    def test_skill_management_tools_are_available_in_all_modes(self):
        manager = AssistantModeManager(_FakeConfig())

        for mode in ("normal", "documents", "research", "office", "study"):
            bundle = manager.get_tool_bundle(mode)
            self.assertIn("list_skills", bundle["tools"])
            self.assertIn("load_skill", bundle["tools"])
            self.assertIn("create_skill", bundle["tools"])

    def test_uses_injected_semantic_router_for_route_selection(self):
        manager = AssistantModeManager(_FakeConfig(), semantic_router=_InjectedSemanticRouter())

        route = manager.route(
            {
                "content": "Please just summarize this local folder.",
                "metadata": {},
            },
            session_metadata={"current_mode": "documents"},
            source=SimpleNamespace(kind="desktop", id="desktop-user"),
        )

        self.assertEqual(route.current_mode, "research")
        self.assertEqual(route.source_profile, "finance_macro")
        self.assertIn("research_grounding", route.active_skills or [])
        self.assertIn("track_source_updates", route.tool_bundle)
        self.assertIn("Injected semantic router selected research.", route.route_reason)
        self.assertEqual(route.confidence, "high")
        self.assertTrue(route.prefer_live_web)
        self.assertFalse(route.should_preload_context)
        self.assertEqual(route.adapter_name, "injected_test_router")
        self.assertIn("injected_semantic", route.signals or [])

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

    def test_lists_loads_and_creates_open_skills(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            skill_dir = Path(tmp_dir) / "SKILL"
            _populate_skill_dir(skill_dir)
            manager = AssistantModeManager(
                _FakeConfig(
                    {
                        "assistant_modes": json.dumps(
                            {
                                "skill_prompt_dir": str(skill_dir)
                            }
                        )
                    }
                )
            )

            all_skills = manager.list_skills()
            self.assertTrue(any(item["skill_type"] == "mode" for item in all_skills))
            self.assertTrue(any(item["skill_type"] == "reusable" for item in all_skills))

            research_mode_skill = manager.load_skill("mode:research")
            self.assertIsNotNone(research_mode_skill)
            self.assertEqual(research_mode_skill["skill_type"], "mode")
            self.assertIn("[Research Mode Skill]", research_mode_skill["content"])

            created = manager.create_skill(
                skill_id="release_note_triage",
                title="Release Note Triage",
                summary="Summarize release notes into actionable updates.",
                content="Read the release notes, extract breaking changes, and produce action items.",
                recommended_tools=["research_topic", "compile_report"],
                applicable_modes=["research", "documents"],
                scenarios=["release notes", "change review"],
            )
            self.assertEqual(created["skill_type"], "reusable")
            self.assertEqual(Path(created["storage_path"]).parent, skill_dir.resolve())

            loaded = manager.load_skill("release_note_triage")
            self.assertIsNotNone(loaded)
            self.assertIn("breaking changes", loaded["content"])

            prompt_text = manager.assemble_prompt_for_route(
                {
                    "current_mode": "research",
                    "content": "Review a new SDK release.",
                    "active_skills": ["research_grounding"],
                    "loaded_skills": ["release_note_triage"],
                }
            )
            self.assertIn("breaking changes", prompt_text)

            capability = manager.get_skill_capability("release_note_triage")
            self.assertIsNotNone(capability)
            self.assertIn("research_topic", capability["tools"])

            bundle = manager.get_tool_bundle("research", loaded_skills=["release_note_triage"])
            self.assertIn("research_topic", bundle["tools"])
            self.assertIn("compile_report", bundle["tools"])

    def test_validates_capability_registry_and_loaded_skill_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            skill_dir = Path(tmp_dir) / "SKILL"
            _populate_skill_dir(skill_dir)
            manager = AssistantModeManager(
                _FakeConfig(
                    {
                        "assistant_modes": json.dumps(
                            {
                                "skill_prompt_dir": str(skill_dir)
                            }
                        )
                    }
                )
            )

            manager.create_skill(
                skill_id="workspace_triage",
                title="Workspace Triage",
                summary="Inspect a workspace and summarize next actions.",
                content="Inspect the workspace and produce next actions.",
                recommended_tools=["analyze_workspace", "compile_report"],
                applicable_modes=["documents"],
                scenarios=["workspace triage"],
            )

            problems = manager.validate_capability_registry(
                tool_names=[
                    "ask_human",
                    "get_current_system_time",
                    "search_knowledge",
                    "search_memory",
                    "search_web",
                    "read_web_page",
                    "remember_knowledge",
                    "manage_memories",
                    "list_skills",
                    "load_skill",
                    "create_skill",
                    "get_sys_vitals",
                    "research_topic",
                    "inspect_page",
                    "track_source_updates",
                    "exec_sys_cmd",
                    "analyze_workspace",
                    "read_local_documents",
                    "write_local_document",
                    "rewrite_local_document",
                    "compile_report",
                    "manage_schedule",
                    "draft_message",
                    "meeting_brief",
                    "sync_notes",
                    "build_study_plan",
                    "extract_learning_points",
                    "quiz_me",
                    "generate_flashcards",
                    "track_mastery",
                    "manage_tasks",
                    "manage_scheduled_tasks",
                ],
                mcp_servers=["filesystem_tools"],
            )

            self.assertEqual(problems, [])
            bundle = manager.get_tool_bundle("documents", loaded_skills=["workspace_triage"])
            self.assertIn("analyze_workspace", bundle["tools"])
            self.assertIn("compile_report", bundle["tools"])

    def test_trusted_write_roots_and_primary_sources(self):
        with tempfile.TemporaryDirectory() as tmp_dir, tempfile.TemporaryDirectory() as other_dir:
            repo_root = Path(__file__).resolve().parent.parent
            manager = AssistantModeManager(
                _FakeConfig(
                    {
                        "trusted_write_roots": json.dumps([tmp_dir]),
                        "source_catalog_path": str(repo_root / "user" / "source_catalog.json"),
                    }
                )
            )

            trusted_file = Path(tmp_dir) / "docs" / "summary.md"
            other_file = Path(other_dir) / "notes.md"

            self.assertTrue(manager.is_trusted_write_path(str(trusted_file)))
            self.assertFalse(manager.is_trusted_write_path(str(other_file)))
            self.assertTrue(manager.is_primary_source("https://github.com/python/cpython/releases", "tech_updates"))


if __name__ == "__main__":
    unittest.main()
