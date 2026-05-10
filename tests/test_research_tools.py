from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.artifacts import LocalArtifactStore
from core.db.base import Base
from core.db.bootstrap import build_core_services
from core.db.models import Principal, Workspace
from core.services.v5_service import ArtifactService
from tools.research_tools import ResearchTools


class ResearchToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        with self.Session() as session:
            principal = Principal(principal_key="self", display_name="Self")
            session.add(principal)
            session.flush()
            workspace = Workspace(workspace_id="personal", principal_id=principal.id, title="Personal")
            session.add(workspace)
            session.commit()
            self.principal = principal
            self.workspace = workspace

        services = build_core_services(self.Session)
        services.artifact = ArtifactService(
            self.Session,
            store=LocalArtifactStore(Path(self.tmp.name) / "artifacts"),
        )
        self.domain = SimpleNamespace(services=services, principal=self.principal)
        self.tools = ResearchTools()
        self.tools.set_core_domain(self.domain)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.tmp.cleanup()

    async def test_manage_research_tasks_completes_report_artifact_with_citation_guard(self) -> None:
        created = await self.tools.create_research_task(topic="V5 evidence ledger")
        research_task_id = created["research_task_id"]

        started = await self.tools.manage_research_tasks(
            action="start",
            research_task_id=research_task_id,
        )
        self.assertTrue(started["ok"])
        self.assertEqual(started["status"], "running")

        locked_plan = await self.tools.manage_research_tasks(
            action="update",
            research_task_id=research_task_id,
            plan={"schema": "locked-after-start"},
        )
        self.assertFalse(locked_plan["ok"])
        self.assertEqual(locked_plan["code"], "research_plan_locked")

        invalid = await self.tools.manage_research_tasks(
            action="complete",
            research_task_id=research_task_id,
            evidence_ledger=[{"source_id": 1, "url": "https://example.test/one"}],
            report_markdown="Unsupported source [2].",
        )
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["code"], "research_report_citation_invalid")
        self.assertEqual(invalid["missing_source_ids"], ["2"])

        completed = await self.tools.manage_research_tasks(
            action="complete",
            research_task_id=research_task_id,
            evidence_ledger=[{"source_id": 1, "url": "https://example.test/one"}],
            report_markdown="Supported source [1].",
            report_filename="evidence.md",
            summary="Done",
        )
        self.assertTrue(completed["ok"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["artifact"]["filename"], "evidence.md")
        self.assertEqual(completed["artifact"]["citation_validation"]["citation_ids"], ["1"])

    async def test_create_research_task_rejects_unknown_project_or_thread(self) -> None:
        unknown_project = await self.tools.create_research_task(
            topic="must stay project-bound",
            project_id="prj_missing",
        )
        unknown_thread = await self.tools.create_research_task(
            topic="must stay thread-bound",
            thread_id="thr_missing",
        )

        self.assertFalse(unknown_project["ok"])
        self.assertEqual(unknown_project["code"], "project_not_found")
        self.assertFalse(unknown_thread["ok"])
        self.assertEqual(unknown_thread["code"], "thread_not_found")

    async def test_manage_research_tasks_list_rejects_unknown_project_filter(self) -> None:
        await self.tools.create_research_task(topic="existing task")

        result = await self.tools.manage_research_tasks(
            action="list",
            project_id="prj_missing",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "project_not_found")

    async def test_manage_research_tasks_run_uses_core_runner(self) -> None:
        project = self.domain.services.project.create_project(
            principal_id=self.principal.id,
            workspace_id=self.workspace.id,
            title="Tool runner project",
        )
        self.domain.services.project.add_source(
            project_id=project.project_id,
            principal_id=self.principal.id,
            title="Tool source",
            content="Tool-managed research can use project evidence.",
        )
        created = await self.tools.create_research_task(
            topic="tool managed run",
            project_id=project.project_id,
            source_policy={"source_adapters": [], "include_project_sources": True},
        )

        result = await self.tools.manage_research_tasks(
            action="run",
            research_task_id=created["research_task_id"],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["evidence_ledger"][0]["source_type"], "project_source")


if __name__ == "__main__":
    unittest.main()
