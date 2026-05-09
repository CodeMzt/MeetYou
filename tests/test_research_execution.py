from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.artifacts import LocalArtifactStore
from core.db.base import Base
from core.db.bootstrap import build_core_services
from core.db.models import Principal, Workspace
from core.services.research_execution_service import ResearchExecutionService
from core.services.v5_service import ArtifactService


class ResearchExecutionServiceTests(unittest.TestCase):
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
        self.services = build_core_services(self.Session)
        self.services.artifact = ArtifactService(
            self.Session,
            store=LocalArtifactStore(Path(self.tmp.name) / "artifacts"),
        )

    def tearDown(self) -> None:
        self.engine.dispose()
        self.tmp.cleanup()

    def test_runner_gathers_academic_evidence_and_creates_artifact(self) -> None:
        def fake_fetch(url: str, timeout: float = 8.0) -> str:
            del timeout
            self.assertIn("openalex", url)
            return """
            {
              "results": [
                {
                  "id": "https://openalex.org/W1",
                  "title": "Durable conversation branches",
                  "publication_year": 2026,
                  "abstract_inverted_index": {"Durable": [0], "checkpoints": [1]},
                  "authorships": [{"author": {"display_name": "A. Researcher"}}],
                  "primary_location": {"source": {"display_name": "Journal of Runtime Systems"}}
                }
              ]
            }
            """

        task = self.services.research_task.create_task(
            principal_id=self.principal.id,
            topic="conversation checkpointing",
            source_policy={"source_adapters": ["openalex"], "limit": 1},
        )
        result = ResearchExecutionService(self.services, fetcher=fake_fetch).run_task(task.research_task_id)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        completed = self.services.research_task.get_by_research_task_id(task.research_task_id)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.evidence_ledger[0]["source_id"], "1")
        self.assertEqual(completed.evidence_ledger[0]["adapter"], "openalex")
        artifact = self.services.artifact.get_by_id(completed.artifact_id)
        report_path = self.services.artifact.resolve_local_path(artifact)
        self.assertIn("Durable conversation branches", Path(report_path).read_text(encoding="utf-8"))
        self.assertIn("[1]", Path(report_path).read_text(encoding="utf-8"))

    def test_runner_gathers_direct_web_evidence_and_creates_artifact(self) -> None:
        def fake_web_fetch(url: str, timeout: float = 8.0) -> dict:
            del timeout
            self.assertEqual(url, "https://example.test/research")
            return {
                "url": url,
                "content_type": "text/html; charset=utf-8",
                "content": """
                <html>
                  <head><title>Readable V5 web source</title><script>ignorePrompt()</script></head>
                  <body><main>Web evidence about durable research reports and citation ledgers.</main></body>
                </html>
                """,
            }

        task = self.services.research_task.create_task(
            principal_id=self.principal.id,
            topic="web evidence",
            source_policy={
                "source_adapters": ["web"],
                "web_urls": ["https://example.test/research"],
                "limit": 1,
            },
        )
        result = ResearchExecutionService(self.services, web_fetcher=fake_web_fetch).run_task(task.research_task_id)

        self.assertTrue(result["ok"])
        completed = self.services.research_task.get_by_research_task_id(task.research_task_id)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.evidence_ledger[0]["source_type"], "web_page")
        self.assertEqual(completed.evidence_ledger[0]["adapter"], "web")
        self.assertEqual(completed.evidence_ledger[0]["verification_status"], "fetched")
        self.assertEqual(completed.evidence_ledger[0]["title"], "Readable V5 web source")
        self.assertIn("durable research reports", completed.evidence_ledger[0]["snippet"])
        self.assertNotIn("ignorePrompt", completed.evidence_ledger[0]["snippet"])
        self.assertEqual(completed.meta["gather_errors"], [])
        artifact = self.services.artifact.get_by_id(completed.artifact_id)
        report_path = self.services.artifact.resolve_local_path(artifact)
        self.assertIn("Readable V5 web source", Path(report_path).read_text(encoding="utf-8"))

    def test_runner_reports_web_adapter_missing_seed_urls(self) -> None:
        task = self.services.research_task.create_task(
            principal_id=self.principal.id,
            topic="web without urls",
            source_policy={"source_adapters": ["web"]},
        )
        result = ResearchExecutionService(self.services).run_task(task.research_task_id)

        self.assertFalse(result["ok"])
        failed = self.services.research_task.get_by_research_task_id(task.research_task_id)
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.meta["runner_error"], "no_evidence")
        self.assertEqual(failed.meta["gather_errors"][0]["adapter"], "web")
        self.assertEqual(failed.meta["gather_errors"][0]["error_type"], "WebSeedUrlsRequired")

    def test_runner_uses_project_sources_without_external_fetch(self) -> None:
        project = self.services.project.create_project(
            principal_id=self.principal.id,
            workspace_id=self.workspace.id,
            title="Research project",
        )
        self.services.project.add_source(
            project_id=project.project_id,
            principal_id=self.principal.id,
            title="Saved note",
            content="Project source evidence about branchable conversation history.",
        )
        task = self.services.research_task.create_task(
            principal_id=self.principal.id,
            project_id=project.id,
            topic="project evidence",
            source_policy={"source_adapters": [], "include_project_sources": True},
        )

        def no_fetch(url: str, timeout: float = 8.0) -> str:
            del url, timeout
            raise AssertionError("academic fetch should not run")

        result = ResearchExecutionService(self.services, fetcher=no_fetch).run_task(task.research_task_id)

        self.assertTrue(result["ok"])
        completed = self.services.research_task.get_by_research_task_id(task.research_task_id)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.evidence_ledger[0]["source_type"], "project_source")
        self.assertEqual(completed.evidence_ledger[0]["title"], "Saved note")

    def test_runner_fails_when_no_evidence_is_available(self) -> None:
        task = self.services.research_task.create_task(
            principal_id=self.principal.id,
            topic="empty evidence",
            source_policy={"source_adapters": []},
        )
        result = ResearchExecutionService(self.services).run_task(task.research_task_id)

        self.assertFalse(result["ok"])
        failed = self.services.research_task.get_by_research_task_id(task.research_task_id)
        self.assertEqual(failed.status, "failed")
        self.assertIn("did not gather", failed.summary)


if __name__ == "__main__":
    unittest.main()
