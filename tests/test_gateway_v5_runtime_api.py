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
                "source_policy": {"source_adapters": ["arxiv"], "auto_execute": False, "derived_formats": ["pdf", "docx"]},
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(research_response.status_code, 200)
        self.assertEqual(research_response.json()["status"], "planned")
        self.assertEqual(research_response.json()["plan"]["source_adapters"], ["arxiv"])
        self.assertEqual(research_response.json()["plan"]["language"], "zh-CN")
        self.assertIn("plan_review", [step["id"] for step in research_response.json()["plan"]["steps"]])
        self.assertEqual(research_response.json()["plan"]["deliverables"]["derived_formats"], ["pdf", "docx"])
        self.assertIn("citation_guard", [gate["enforcement"] for gate in research_response.json()["plan"]["quality_gates"]])
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
        self.assertTrue(start_response.json()["run_id"])

        start_events_response = self.client.get(
            f"/runtime/research-tasks/{research_task_id}/events",
            headers=self._auth_headers(),
        )
        self.assertEqual(start_events_response.status_code, 200)
        self.assertEqual(len(start_events_response.json()), 1)
        self.assertEqual(start_events_response.json()[0]["type"], "research.started")
        self.assertEqual(start_events_response.json()[0]["run_id"], start_response.json()["run_id"])
        self.assertEqual(start_events_response.json()[0]["payload"]["research_task_id"], research_task_id)

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
        derived_artifacts = report_response.json()["derived_artifacts"]
        self.assertEqual([row["content_type"] for row in derived_artifacts], [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ])
        self.assertEqual([row["metadata"]["derived_format"] for row in derived_artifacts], ["pdf", "docx"])
        self.assertEqual(len(report_response.json()["metadata"]["derived_artifacts"]), 2)

        completed_events_response = self.client.get(
            f"/runtime/research-tasks/{research_task_id}/events",
            params={"after_seq": 1},
            headers=self._auth_headers(),
        )
        self.assertEqual(completed_events_response.status_code, 200)
        self.assertEqual([event["type"] for event in completed_events_response.json()], ["research.completed"])
        self.assertEqual(completed_events_response.json()[0]["payload"]["status"], "succeeded")

        report_download_response = self.client.get(
            report_response.json()["artifact"]["download_url"],
            headers=self._auth_headers(),
        )
        self.assertEqual(report_download_response.status_code, 200)
        self.assertIn("A supported claim [1].", report_download_response.text)
        pdf_download_response = self.client.get(derived_artifacts[0]["download_url"], headers=self._auth_headers())
        self.assertEqual(pdf_download_response.status_code, 200)
        self.assertTrue(pdf_download_response.content.startswith(b"%PDF-"))
        docx_download_response = self.client.get(derived_artifacts[1]["download_url"], headers=self._auth_headers())
        self.assertEqual(docx_download_response.status_code, 200)
        self.assertTrue(docx_download_response.content.startswith(b"PK"))

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
        default_branch_id = branches_response.json()[0]["branch_id"]
        self.assertEqual(branches_response.json()[0]["title"], "默认分支")
        self.assertTrue(branches_response.json()[0]["metadata"]["is_active"])

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
        self.assertEqual(checkout_response.json()["parent_branch_id"], default_branch_id)
        self.assertTrue(checkout_response.json()["metadata"]["is_active"])

        edit_retry_response = self.client.post(
            f"/runtime/messages/{user_message.message_id}/edit-retry",
            json={"content": "edited prompt", "title": "Edited branch"},
            headers=self._auth_headers(),
        )
        self.assertEqual(edit_retry_response.status_code, 200)
        self.assertEqual(edit_retry_response.json()["message"]["content"], "edited prompt")
        self.assertEqual(edit_retry_response.json()["replay_status"], "branch_created")
        self.assertEqual(edit_retry_response.json()["branch"]["parent_branch_id"], default_branch_id)
        self.assertTrue(edit_retry_response.json()["branch"]["metadata"]["is_active"])

        branches_after_retry_response = self.client.get(
            f"/runtime/threads/{thread.thread_id}/branches",
            headers=self._auth_headers(),
        )
        self.assertEqual(branches_after_retry_response.status_code, 200)
        branches_after_retry = branches_after_retry_response.json()
        self.assertEqual(len(branches_after_retry), 3)
        active_branches = [row for row in branches_after_retry if row["metadata"]["is_active"]]
        self.assertEqual([row["branch_id"] for row in active_branches], [edit_retry_response.json()["branch"]["branch_id"]])
        sibling_branch_ids = [row["branch_id"] for row in branches_after_retry if row["parent_branch_id"] == default_branch_id]
        self.assertEqual(set(sibling_branch_ids), {checkout_response.json()["branch_id"], edit_retry_response.json()["branch"]["branch_id"]})

        activate_response = self.client.post(
            f"/runtime/threads/{thread.thread_id}/branches/{checkout_response.json()['branch_id']}/activate",
            headers=self._auth_headers(),
        )
        self.assertEqual(activate_response.status_code, 200)
        self.assertEqual(activate_response.json()["branch_id"], checkout_response.json()["branch_id"])
        self.assertTrue(activate_response.json()["metadata"]["is_active"])

        activated_messages_response = self.client.get(
            f"/runtime/threads/{thread.thread_id}/messages",
            headers=self._auth_headers(),
        )
        self.assertEqual(activated_messages_response.status_code, 200)
        self.assertEqual([row["content"] for row in activated_messages_response.json()], ["original prompt", "original answer"])

        branches_after_activate_response = self.client.get(
            f"/runtime/threads/{thread.thread_id}/branches",
            headers=self._auth_headers(),
        )
        self.assertEqual(branches_after_activate_response.status_code, 200)
        active_after_activate = [row for row in branches_after_activate_response.json() if row["metadata"]["is_active"]]
        self.assertEqual([row["branch_id"] for row in active_after_activate], [checkout_response.json()["branch_id"]])

    def test_research_task_start_auto_executes_read_only_runner(self) -> None:
        project_response = self.client.post(
            "/runtime/projects",
            json={"workspace_id": "personal", "title": "Research Runner Project"},
            headers=self._auth_headers(),
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["project_id"]
        source_response = self.client.post(
            f"/runtime/projects/{project_id}/sources",
            json={
                "source_type": "note",
                "title": "Project evidence note",
                "content": "Saved project evidence for automatic research execution.",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(source_response.status_code, 200)
        task_response = self.client.post(
            "/runtime/research-tasks",
            json={
                "project_id": project_id,
                "topic": "automatic research execution",
                "source_policy": {"source_adapters": [], "include_project_sources": True},
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(task_response.status_code, 200)
        research_task_id = task_response.json()["research_task_id"]

        start_response = self.client.patch(
            f"/runtime/research-tasks/{research_task_id}",
            json={"action": "start"},
            headers=self._auth_headers(),
        )
        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(start_response.json()["status"], "running")

        completed_response = self.client.get(
            f"/runtime/research-tasks/{research_task_id}",
            headers=self._auth_headers(),
        )
        self.assertEqual(completed_response.status_code, 200)
        completed = completed_response.json()
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["evidence_ledger"][0]["source_type"], "project_source")
        self.assertTrue(completed["artifact_id"])
        download_response = self.client.get(completed["artifact"]["download_url"], headers=self._auth_headers())
        self.assertEqual(download_response.status_code, 200)
        self.assertIn("Project evidence note", download_response.text)

    def test_edit_retry_queues_runtime_event_when_message_has_session(self) -> None:
        thread_response = self.client.post(
            "/runtime/threads",
            json={"workspace_id": "personal", "title": "Edit retry queue thread"},
            headers=self._auth_headers(),
        )
        self.assertEqual(thread_response.status_code, 200)
        thread_id = thread_response.json()["thread_id"]

        session_response = self.client.post(
            "/runtime/sessions",
            json={
                "thread_id": thread_id,
                "workspace_id": "personal",
                "endpoint_id": "ui.endpoint",
                "endpoint_type": "electron",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(session_response.status_code, 200)
        session_id = session_response.json()["session_id"]

        message_response = self.client.post(
            "/runtime/messages",
            json={
                "thread_id": thread_id,
                "workspace_id": "personal",
                "session_id": session_id,
                "endpoint_id": "ui.endpoint",
                "endpoint_type": "electron",
                "role": "user",
                "content": "original queued prompt",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(message_response.status_code, 200)
        message_id = message_response.json()["message_id"]
        while not self.gateway._event_bus.inbound_queue.empty():
            self.gateway._event_bus.inbound_queue.get_nowait()

        edit_retry_response = self.client.post(
            f"/runtime/messages/{message_id}/edit-retry",
            json={"content": "edited queued prompt", "title": "Queued edited branch"},
            headers=self._auth_headers(),
        )
        self.assertEqual(edit_retry_response.status_code, 200)
        self.assertEqual(edit_retry_response.json()["replay_status"], "queued")

        event = self.gateway._event_bus.inbound_queue.get_nowait()
        self.assertEqual(event.session_id, session_id)
        self.assertEqual(event.content, "edited queued prompt")
        self.assertEqual(event.metadata["message_id"], edit_retry_response.json()["message"]["message_id"])
        self.assertTrue(event.metadata["edit_retry"])
        self.assertEqual(event.metadata["branch_id"], edit_retry_response.json()["branch"]["branch_id"])

    def test_edit_retry_uses_current_thread_session_as_fallback(self) -> None:
        thread_response = self.client.post(
            "/runtime/threads",
            json={"workspace_id": "personal", "title": "Edit retry fallback thread"},
            headers=self._auth_headers(),
        )
        self.assertEqual(thread_response.status_code, 200)
        thread_id = thread_response.json()["thread_id"]

        session_response = self.client.post(
            "/runtime/sessions",
            json={
                "thread_id": thread_id,
                "workspace_id": "personal",
                "endpoint_id": "ui.endpoint",
                "endpoint_type": "electron",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(session_response.status_code, 200)
        session_id = session_response.json()["session_id"]

        message_response = self.client.post(
            "/runtime/messages",
            json={
                "thread_id": thread_id,
                "workspace_id": "personal",
                "endpoint_id": "ui.endpoint",
                "endpoint_type": "electron",
                "role": "user",
                "content": "legacy prompt without session",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(message_response.status_code, 200)
        self.assertEqual(message_response.json()["session_id"], "")
        message_id = message_response.json()["message_id"]
        while not self.gateway._event_bus.inbound_queue.empty():
            self.gateway._event_bus.inbound_queue.get_nowait()

        edit_retry_response = self.client.post(
            f"/runtime/messages/{message_id}/edit-retry",
            json={
                "content": "fallback session edited prompt",
                "title": "Fallback edited branch",
                "session_id": session_id,
                "endpoint_id": "ui.endpoint",
                "endpoint_type": "electron",
                "workspace_id": "personal",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(edit_retry_response.status_code, 200)
        self.assertEqual(edit_retry_response.json()["replay_status"], "queued")
        self.assertEqual(edit_retry_response.json()["message"]["session_id"], session_id)

        event = self.gateway._event_bus.inbound_queue.get_nowait()
        self.assertEqual(event.session_id, session_id)
        self.assertEqual(event.content, "fallback session edited prompt")
        self.assertEqual(event.metadata["message_id"], edit_retry_response.json()["message"]["message_id"])
        self.assertEqual(event.metadata["endpoint_id"], "ui.endpoint")
        self.assertEqual(event.metadata["endpoint_type"], "electron")
        self.assertTrue(event.metadata["edit_retry"])

    def test_edit_retry_rejects_fallback_session_from_another_thread(self) -> None:
        first_thread_response = self.client.post(
            "/runtime/threads",
            json={"workspace_id": "personal", "title": "Edit retry first thread"},
            headers=self._auth_headers(),
        )
        second_thread_response = self.client.post(
            "/runtime/threads",
            json={"workspace_id": "personal", "title": "Edit retry second thread"},
            headers=self._auth_headers(),
        )
        self.assertEqual(first_thread_response.status_code, 200)
        self.assertEqual(second_thread_response.status_code, 200)
        first_thread_id = first_thread_response.json()["thread_id"]
        second_thread_id = second_thread_response.json()["thread_id"]

        session_response = self.client.post(
            "/runtime/sessions",
            json={
                "thread_id": second_thread_id,
                "workspace_id": "personal",
                "endpoint_id": "ui.endpoint",
                "endpoint_type": "electron",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(session_response.status_code, 200)

        message_response = self.client.post(
            "/runtime/messages",
            json={
                "thread_id": first_thread_id,
                "workspace_id": "personal",
                "endpoint_id": "ui.endpoint",
                "endpoint_type": "electron",
                "role": "user",
                "content": "legacy prompt on first thread",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(message_response.status_code, 200)

        edit_retry_response = self.client.post(
            f"/runtime/messages/{message_response.json()['message_id']}/edit-retry",
            json={
                "content": "bad fallback",
                "session_id": session_response.json()["session_id"],
                "endpoint_id": "ui.endpoint",
                "endpoint_type": "electron",
                "workspace_id": "personal",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(edit_retry_response.status_code, 400)
        self.assertEqual(edit_retry_response.json()["error"]["code"], "session_thread_mismatch")


if __name__ == "__main__":
    unittest.main()
