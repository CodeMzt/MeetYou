import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.assistant_modes import AssistantModeManager
from core.tool_runtime.models import ToolCallResult
from tools.scenario_tools import ScenarioTools


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


class _FakeContent:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _FakeResult:
    def __init__(self, text: str):
        self.content = [_FakeContent(text)]


class _FakeMCPManager:
    def __init__(self, responses=None, tool_map=None):
        self.responses = responses or {}
        self.tool_map = tool_map or {}
        self.calls = []

    async def call_mcp_tool(self, tool_name: str, arguments: dict):
        self.calls.append((tool_name, dict(arguments)))
        queue = self.responses.get(tool_name, [])
        if not queue:
            raise RuntimeError(f"unexpected tool call: {tool_name}")
        return _FakeResult(queue.pop(0))


class _FakeMemory:
    def __init__(self):
        self._embedding_model = "fake-embedding"
        self._store = {"records": [], "edges": [], "metadata": {}, "working_summaries": {}}
        self.saved = 0
        self.recall_payload = {
            "query": "payment callback",
            "found": True,
            "profile": [{"fact_key": "team", "fact_value": "Payments", "score": 0.92}],
            "facts": [{"content": "Fix callback retries", "fact_key": "billing_callback", "score": 0.88}],
            "recent_events": [],
        }

    def _resolve_user_id(self, source):
        if isinstance(source, dict):
            return source.get("id", "global")
        return getattr(source, "id", "global") or "global"

    def _record_scope(self, user_id: str, session_id: str, record_type: str):
        return {"user_id": user_id, "session_id": session_id if record_type == "episode" else ""}

    async def _get_embedding(self, text: str):
        return [float(len(text or "")), 1.0]

    def _link_semantic_edges(self, record):
        return None

    async def save_memory_graph(self):
        self.saved += 1

    async def recall_memory_structured(self, query, session_id="", source=None, reinforce=True):
        del query, session_id, source, reinforce
        return json.dumps(self.recall_payload, ensure_ascii=False)


class _FakeContextManager:
    async def load_context(self, session_id=""):
        del session_id
        return "recent session context"


class _FakeModeManager:
    def classify_research_source_profile(self, text: str) -> str:
        del text
        return "tech_global"

    def is_primary_source(self, url: str, profile_name: str = "") -> bool:
        del profile_name
        return "docs.python.org" in str(url or "")


class _CatalogModeManager(_FakeModeManager):
    def is_primary_source(self, url: str, profile_name: str = "") -> bool:
        del profile_name
        normalized = str(url or "")
        return "github.com" in normalized or "docs.python.org" in normalized

    def get_source_catalog_status(self) -> dict:
        return {
            "available": True,
            "path": "user/source_catalog.json",
            "error": "",
            "version": "1",
            "profile_count": 1,
            "source_count": 1,
        }

    def get_source_profile(self, profile_name: str) -> dict:
        return {
            "name": profile_name,
            "official_only": True,
            "preferred_source_ids": ["github_releases_official"],
        }

    def get_sources_for_profile(self, profile_name: str, official_only=None) -> list[dict]:
        del official_only
        return [
            {
                "id": "github_releases_official",
                "enabled": True,
                "domain": "github.com",
                "label": "GitHub Releases",
                "connector_type": "github_releases",
                "profiles": [profile_name],
                "priority": 100,
                "credibility": "primary",
                "primary_source": True,
                "freshness": "high",
                "auth": [],
                "request_defaults": {"site_query": "github.com"},
            }
        ]

    def resolve_source_auth_entries(self, source_config: dict) -> list[dict]:
        del source_config
        return []


class _Config:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key: str):
        return self._values.get(key)


class ScenarioToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_research_topic_wraps_search_chain(self):
        memory = _FakeMemory()
        manager = _FakeMCPManager(
            responses={
                "tavily-search": [
                    json.dumps(
                        {
                            "answer": "Short answer",
                            "results": [
                                {
                                    "title": "Source One",
                                    "url": "https://example.com/one",
                                    "content": "Snippet one",
                                }
                            ],
                        }
                    )
                ],
                "tavily-extract": [
                    json.dumps(
                        {
                            "results": [
                                {
                                    "url": "https://example.com/one",
                                    "title": "Source One",
                                    "raw_content": "Full article one " * 20,
                                }
                            ]
                        }
                    )
                ],
            },
            tool_map={
                "tavily-search": "tavily_web",
                "tavily-extract": "tavily_web",
            },
        )
        tools = ScenarioTools(memory, _FakeContextManager(), manager, mode_manager=_FakeModeManager())

        raw = await tools.research_topic("latest payment outage")
        payload = json.loads(raw)

        self.assertEqual(payload["chain"], "research_topic")
        self.assertEqual(payload["source_profile"], "tech_global")
        self.assertEqual(payload["search"]["search_backend"], "tavily")
        self.assertEqual(payload["search"]["source_profile"], "tech_global")
        self.assertEqual(payload["search"]["evidence"][0]["credible_level"], "secondary")
        self.assertEqual(payload["search"]["citation_blocks"][0]["source_id"], 1)
        self.assertEqual(manager.calls[0][0], "tavily-search")

    async def test_search_knowledge_combines_memory_and_notion(self):
        memory = _FakeMemory()
        manager = _FakeMCPManager(
            responses={
                "post-search": [
                    json.dumps(
                        {
                            "results": [
                                {
                                    "id": "page_1",
                                    "url": "https://notion.so/page-1",
                                    "object": "page",
                                    "title": "Payment Callback Plan",
                                }
                            ]
                        }
                    )
                ],
                "retrieve-a-page": [
                    json.dumps(
                        {
                            "id": "page_1",
                            "url": "https://notion.so/page-1",
                            "properties": {
                                "title": {
                                    "title": [
                                        {"plain_text": "Payment Callback Plan"}
                                    ]
                                }
                            },
                        }
                    )
                ],
                "retrieve-block-children": [
                    json.dumps(
                        {
                            "results": [
                                {
                                    "paragraph": {
                                        "rich_text": [
                                            {"plain_text": "Use idempotency keys for retry safety."}
                                        ]
                                    }
                                }
                            ]
                        }
                    )
                ],
            },
            tool_map={
                "post-search": "notion_knowledge",
                "retrieve-a-page": "notion_knowledge",
                "retrieve-block-children": "notion_knowledge",
            },
        )
        tools = ScenarioTools(memory, _FakeContextManager(), manager)

        raw = await tools.search_knowledge("payment callback", source={"id": "desktop-user"})
        payload = json.loads(raw)

        self.assertTrue(payload["found"])
        self.assertIn("memory", payload["scope_used"])
        self.assertIn("notion", payload["scope_used"])
        source_types = {item["source_type"] for item in payload["sources"]}
        self.assertIn("memory", source_types)
        self.assertIn("notion", source_types)

    async def test_search_knowledge_redirects_live_web_queries(self):
        tools = ScenarioTools(_FakeMemory(), _FakeContextManager(), _FakeMCPManager())

        raw = await tools.search_knowledge("今天上海天气")
        payload = json.loads(raw)

        self.assertFalse(payload["found"])
        self.assertEqual(payload["route_suggestion"]["preferred_tool"], "research_topic")

    async def test_inspect_page_includes_source_profile_and_evidence(self):
        manager = _FakeMCPManager(
            responses={
                "tavily-extract": [
                    json.dumps(
                        {
                            "results": [
                                {
                                    "url": "https://docs.python.org/3/library/pathlib.html",
                                    "title": "pathlib",
                                    "raw_content": "Pathlib is the object-oriented filesystem paths module. " * 8,
                                }
                            ]
                        }
                    )
                ]
            },
            tool_map={"tavily-extract": "tavily_web"},
        )
        tools = ScenarioTools(_FakeMemory(), _FakeContextManager(), manager, mode_manager=_FakeModeManager())

        raw = await tools.inspect_page("https://docs.python.org/3/library/pathlib.html")
        payload = json.loads(raw)

        self.assertEqual(payload["chain"], "inspect_page")
        self.assertEqual(payload["source_profile"], "tech_global")
        self.assertTrue(payload["page"]["evidence"][0]["is_primary_source"])

    async def test_research_topic_prefers_catalog_results_when_available(self):
        tools = ScenarioTools(
            _FakeMemory(),
            _FakeContextManager(),
            _FakeMCPManager(),
            mode_manager=_CatalogModeManager(),
        )

        async def fake_catalog_search(query, *, source_profile, limit=5, official_only=None, activity_callback=None):
            del query, limit, official_only, activity_callback
            return {
                "catalog_status": {"available": True},
                "catalog_unavailable": False,
                "source_profile": source_profile,
                "sources": [
                    {
                        "id": 1,
                        "title": "GitHub Release v1.2.3",
                        "url": "https://github.com/example/project/releases/tag/v1.2.3",
                        "summary": "Official release notes",
                        "snippet": "Official release notes",
                        "published_date": "2026-04-01",
                        "reader": "github_releases",
                        "source_type": "github_releases",
                        "catalog_source_id": "github_releases_official",
                        "catalog_source_label": "GitHub Releases",
                        "catalog_source_domain": "github.com",
                        "connector_type": "github_releases",
                        "credible_level": "primary",
                        "freshness": "high",
                    }
                ],
                "partial_failures": [],
            }

        tools._authoritative_sources.search = fake_catalog_search

        raw = await tools.research_topic("latest sdk release")
        payload = json.loads(raw)

        self.assertEqual(payload["search"]["search_backend"], "source_catalog")
        self.assertFalse(payload["search"]["catalog_unavailable"])
        self.assertEqual(payload["search"]["source_profile"], "tech_global")
        self.assertEqual(payload["search"]["evidence"][0]["credible_level"], "primary")

    async def test_track_source_updates_returns_catalog_payload(self):
        tools = ScenarioTools(
            _FakeMemory(),
            _FakeContextManager(),
            _FakeMCPManager(),
            mode_manager=_CatalogModeManager(),
        )

        async def fake_track_updates(*, source_profile, watchlist=None, since="", limit=8, activity_callback=None):
            del watchlist, since, limit, activity_callback
            return {
                "catalog_status": {"available": True},
                "catalog_unavailable": False,
                "source_profile": source_profile,
                "watchlist": ["sdk"],
                "updates": [
                    {
                        "id": 1,
                        "title": "GitHub Release v1.2.3",
                        "url": "https://github.com/example/project/releases/tag/v1.2.3",
                    }
                ],
                "partial_failures": [],
            }

        tools._authoritative_sources.track_updates = fake_track_updates

        raw = await tools.track_source_updates("tech_global", watchlist="sdk")
        payload = json.loads(raw)

        self.assertEqual(payload["tool"], "track_source_updates")
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["catalog_unavailable"])
        self.assertEqual(payload["updates"][0]["title"], "GitHub Release v1.2.3")

    async def test_manage_tasks_create_list_update_and_complete(self):
        memory = _FakeMemory()
        tools = ScenarioTools(memory, _FakeContextManager(), _FakeMCPManager())

        created = json.loads(
            await tools.manage_tasks(
                action="create",
                summary="Fix payment callback retries",
                project="Billing",
                source={"id": "desktop-user"},
            )
        )
        task_key = created["tasks"][0]["task_key"]
        self.assertEqual(created["action"], "create")

        listed = json.loads(
            await tools.manage_tasks(
                action="list",
                source={"id": "desktop-user"},
            )
        )
        self.assertEqual(listed["task_count"], 1)
        self.assertEqual(listed["tasks"][0]["task_key"], task_key)

        updated = json.loads(
            await tools.manage_tasks(
                action="update",
                task_key=task_key,
                task_status="blocked",
                source={"id": "desktop-user"},
            )
        )
        self.assertEqual(updated["tasks"][0]["task_status"], "blocked")

        completed = json.loads(
            await tools.manage_tasks(
                action="complete",
                task_key=task_key,
                completion_summary="已确认修复完成",
                source={"id": "desktop-user"},
            )
        )
        self.assertEqual(completed["tasks"][0]["task_status"], "done")
        self.assertEqual(completed["tasks"][0]["last_completion_summary"], "已确认修复完成")

    async def test_manage_tasks_rejects_schedule_and_manage_scheduled_tasks_handles_it(self):
        memory = _FakeMemory()
        tools = ScenarioTools(memory, _FakeContextManager(), _FakeMCPManager())

        failed = await tools.manage_tasks(
            action="create",
            summary="每天早上九点检查日报",
            schedule_kind="recurring",
            recurrence={"freq": "daily", "hour": 9, "minute": 0},
            timezone="UTC",
            source={"id": "desktop-user"},
        )
        self.assertIsInstance(failed, ToolCallResult)
        self.assertFalse(failed.ok)
        self.assertIn("manage_tasks only manages user TODO items", failed.error.message)

        created = json.loads(
            await tools.manage_scheduled_tasks(
                action="create",
                summary="每天早上九点检查日报",
                schedule_kind="recurring",
                recurrence={"freq": "daily", "hour": 9, "minute": 0},
                timezone="UTC",
                source={"id": "desktop-user"},
            )
        )
        self.assertEqual(created["tasks"][0]["task_domain"], "assistant_schedule")
        self.assertEqual(created["tasks"][0]["schedule_kind"], "recurring")

        todo = json.loads(
            await tools.manage_tasks(
                action="create",
                summary="每天早上九点前完成日报整理",
                source={"id": "desktop-user"},
            )
        )
        self.assertEqual(todo["tasks"][0]["task_domain"], "user_todo")
        self.assertEqual(todo["tasks"][0]["schedule_kind"], "none")

    async def test_open_skill_tools_list_load_and_create(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            skill_dir = Path(tmp_dir) / "SKILL"
            _populate_skill_dir(skill_dir)
            mode_manager = AssistantModeManager(
                _Config(
                    {
                        "assistant_modes": json.dumps(
                            {
                                "skill_prompt_dir": str(skill_dir)
                            }
                        )
                    }
                )
            )
            tools = ScenarioTools(_FakeMemory(), _FakeContextManager(), _FakeMCPManager(), mode_manager=mode_manager)
            route_context = {"current_mode": "research", "loaded_skills": []}

            listed = json.loads(await tools.list_skills(skill_type="all"))
            self.assertGreaterEqual(listed["skill_count"], 2)
            self.assertTrue(any(item["skill_type"] == "mode" for item in listed["skills"]))

            loaded = json.loads(await tools.load_skill("mode:research", route_context=route_context))
            self.assertTrue(loaded["loaded"])
            self.assertTrue(loaded["injected_into_context"])
            self.assertIn("mode:research", route_context["loaded_skills"])

            created = json.loads(
                await tools.create_skill(
                    skill_id="release_note_triage",
                    title="Release Note Triage",
                    summary="Summarize release notes into actions.",
                    content="Extract breaking changes and concrete follow-up actions.",
                    recommended_tools=["research_topic"],
                    applicable_modes=["research"],
                    scenarios=["release notes"],
                    inject_context=True,
                    route_context=route_context,
                )
            )
            self.assertTrue(created["created"])
            self.assertIn("release_note_triage", route_context["loaded_skills"])

            loaded_created = json.loads(await tools.load_skill("release_note_triage", route_context=route_context))
            self.assertEqual(Path(loaded_created["skill"]["storage_path"]).parent, skill_dir.resolve())


if __name__ == "__main__":
    unittest.main()
