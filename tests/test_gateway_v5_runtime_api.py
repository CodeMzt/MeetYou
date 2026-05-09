from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.artifacts import LocalArtifactStore
from core.db.base import Base
from core.db.bootstrap import build_core_services
from core.db.models import Principal, Workspace
from core.event_bus import EventBus
from core.services.v5_service import ArtifactService
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway


class GatewayV5RuntimeApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            "sqlite+pysqlite://",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        with self.Session() as session:
            principal = Principal(principal_key="self", display_name="Self")
            session.add(principal)
            session.flush()
            workspace = Workspace(
                workspace_id="personal",
                principal_id=principal.id,
                title="Personal",
            )
            session.add(workspace)
            session.commit()
            self.principal = principal
            self.workspace = workspace

        self.services = build_core_services(self.Session)
        self.services.artifact = ArtifactService(
            self.Session,
            store=LocalArtifactStore(Path(self.tmp.name) / "artifacts"),
        )
        self.domain = SimpleNamespace(
            services=self.services,
            principal=self.principal,
            workspaces={"personal": self.workspace},
        )
        self.gateway = FastAPIGateway(
            EventBus(),
            SessionManager(),
            core_domain=self.domain,
            access_token="runtime-token",
        )
        self.client = TestClient(self.gateway.app)
        self.addCleanup(self.client.close)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.tmp.cleanup()

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer runtime-token"}

    def test_project_source_research_artifact_and_versioning_routes(self) -> None:
        project_response = self.client.post(
            "/runtime/projects",
            json={
                "workspace_id": "personal",
                "title": "V5 Project",
                "description": "Project container",
                "instructions": "Use project sources first.",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["project_id"]

        source_response = self.client.post(
            f"/runtime/projects/{project_id}/sources",
            json={"title": "Source note", "content": "Evidence note", "source_type": "note"},
            headers=self._auth_headers(),
        )
        self.assertEqual(source_response.status_code, 200)
        self.assertEqual(source_response.json()["content"], "Evidence note")

        thread_response = self.client.post(
            "/runtime/threads",
            json={
                "workspace_id": "personal",
                "project_id": project_id,
                "title": "Project thread",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(thread_response.status_code, 200)
        self.assertEqual(thread_response.json()["project_id"], project_id)
        thread_id = thread_response.json()["thread_id"]

        project_threads_response = self.client.get(
            f"/runtime/projects/{project_id}/threads",
            headers=self._auth_headers(),
        )
        self.assertEqual(project_threads_response.status_code, 200)
        self.assertEqual(project_threads_response.json()[0]["thread_id"], thread_id)

        detach_thread_response = self.client.patch(
            f"/runtime/threads/{thread_id}",
            json={"project_id": "", "title": "Detached thread"},
            headers=self._auth_headers(),
        )
        self.assertEqual(detach_thread_response.status_code, 200)
        self.assertEqual(detach_thread_response.json()["project_id"], "")
        self.assertEqual(detach_thread_response.json()["title"], "Detached thread")

        project = self.services.project.get_by_project_id(project_id)
        artifact = self.services.artifact.create_text_artifact(
            principal_id=self.principal.id,
            project_id=project.id,
            text="# Report",
            filename="report.md",
        )
        artifacts_response = self.client.get(
            f"/runtime/projects/{project_id}/artifacts",
            headers=self._auth_headers(),
        )
        self.assertEqual(artifacts_response.status_code, 200)
        self.assertEqual(artifacts_response.json()[0]["artifact_id"], artifact.artifact_id)

        download_response = self.client.get(
            f"/runtime/artifacts/{artifact.artifact_id}/download",
            headers=self._auth_headers(),
        )
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response.text, "# Report")

        research_response = self.client.post(
            "/runtime/research-tasks",
            json={
                "project_id": project_id,
                "topic": "conversation version trees",
                "source_policy": {"source_adapters": ["arxiv"]},
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(research_response.status_code, 200)
        self.assertEqual(research_response.json()["status"], "planned")
        self.assertEqual(research_response.json()["plan"]["source_adapters"], ["arxiv"])
        research_task_id = research_response.json()["research_task_id"]

        approve_response = self.client.patch(
            f"/runtime/research-tasks/{research_task_id}",
            json={"action": "approve", "plan": {"schema": "meetyou.research.plan.v1", "steps": []}},
            headers=self._auth_headers(),
        )
        self.assertEqual(approve_response.status_code, 200)
        self.assertEqual(approve_response.json()["status"], "approved")

        start_response = self.client.patch(
            f"/runtime/research-tasks/{research_task_id}",
            json={"action": "start"},
            headers=self._auth_headers(),
        )
        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(start_response.json()["status"], "running")

        locked_plan_response = self.client.patch(
            f"/runtime/research-tasks/{research_task_id}",
            json={"plan": {"schema": "should-not-edit-after-start"}},
            headers=self._auth_headers(),
        )
        self.assertEqual(locked_plan_response.status_code, 400)
        self.assertEqual(locked_plan_response.json()["error"]["code"], "research_plan_locked")

        invalid_report_response = self.client.patch(
            f"/runtime/research-tasks/{research_task_id}",
            json={
                "report_markdown": "This report cites a missing source [9].",
                "evidence_ledger": [{"source_id": 1, "url": "https://example.test/source-1"}],
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(invalid_report_response.status_code, 400)
        self.assertEqual(invalid_report_response.json()["error"]["code"], "research_report_citation_invalid")

        report_response = self.client.patch(
            f"/runtime/research-tasks/{research_task_id}",
            json={
                "summary": "Report complete.",
                "report_markdown": "# Research Report\n\nA supported claim [1].",
                "report_filename": "conversation-versioning.md",
                "evidence_ledger": [{"source_id": 1, "url": "https://example.test/source-1"}],
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(report_response.status_code, 200)
        self.assertEqual(report_response.json()["status"], "completed")
        self.assertTrue(report_response.json()["artifact_id"])
        self.assertEqual(report_response.json()["artifact"]["metadata"]["citation_validation"]["citation_ids"], ["1"])

        report_download_response = self.client.get(
            report_response.json()["artifact"]["download_url"],
            headers=self._auth_headers(),
        )
        self.assertEqual(report_download_response.status_code, 200)
        self.assertIn("A supported claim [1].", report_download_response.text)

        thread = self.services.thread.create_thread(
            principal_id=self.principal.id,
            workspace_id=self.workspace.id,
            project_id=project.id,
            title="Versioned thread",
        )
        user_message = self.services.message.create_message(
            thread_id=thread.id,
            role="user",
            content="original prompt",
        )
        self.services.conversation_version.attach_message_to_active_branch(
            thread_row_id=thread.id,
            message_row_id=user_message.id,
        )
        assistant_message = self.services.message.create_message(
            thread_id=thread.id,
            role="assistant",
            content="original answer",
        )
        self.services.conversation_version.attach_message_to_active_branch(
            thread_row_id=thread.id,
            message_row_id=assistant_message.id,
        )

        branches_response = self.client.get(
            f"/runtime/threads/{thread.thread_id}/branches",
            headers=self._auth_headers(),
        )
        self.assertEqual(branches_response.status_code, 200)
        self.assertEqual(len(branches_response.json()), 1)

        checkpoint_response = self.client.post(
            f"/runtime/threads/{thread.thread_id}/checkpoints",
            json={"title": "Saved point"},
            headers=self._auth_headers(),
        )
        self.assertEqual(checkpoint_response.status_code, 200)
        checkpoint_id = checkpoint_response.json()["checkpoint_id"]

        checkout_response = self.client.post(
            f"/runtime/threads/{thread.thread_id}/checkpoints/{checkpoint_id}/checkout",
            json={"title": "Branch from checkpoint"},
            headers=self._auth_headers(),
        )
        self.assertEqual(checkout_response.status_code, 200)
        self.assertEqual(checkout_response.json()["title"], "Branch from checkpoint")

        edit_retry_response = self.client.post(
            f"/runtime/messages/{user_message.message_id}/edit-retry",
            json={"content": "edited prompt", "title": "Edited branch"},
            headers=self._auth_headers(),
        )
        self.assertEqual(edit_retry_response.status_code, 200)
        self.assertEqual(edit_retry_response.json()["message"]["content"], "edited prompt")
        self.assertEqual(edit_retry_response.json()["replay_status"], "branch_created")


if __name__ == "__main__":
    unittest.main()
