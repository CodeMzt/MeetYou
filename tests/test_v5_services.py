from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.artifacts import LocalArtifactStore
from core.db.base import Base
from core.db.models import Message, Principal, Thread, Workspace
from core.services.message_service import MessageService
from core.services.thread_service import ThreadService
from core.services.v5_service import (
    ArtifactService,
    ConversationVersionService,
    ProjectService,
    ResearchTaskCitationError,
    ResearchTaskService,
    ResearchTaskStateError,
)


class V5ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
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
            self.principal_id = principal.id
            self.workspace_id = workspace.id

        self.project_service = ProjectService(self.Session)
        self.thread_service = ThreadService(self.Session)
        self.message_service = MessageService(self.Session)
        self.version_service = ConversationVersionService(self.Session)
        self.research_service = ResearchTaskService(self.Session)
        self.artifact_service = ArtifactService(
            self.Session,
            store=LocalArtifactStore(Path(self.tmp.name) / "artifacts"),
        )

    def tearDown(self) -> None:
        self.engine.dispose()
        self.tmp.cleanup()

    def _create_thread(self):
        return self.thread_service.create_thread(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            title="V5 thread",
        )

    def test_project_sources_can_snapshot_a_message(self) -> None:
        project = self.project_service.create_project(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            title="Research Project",
            description="Shared project context",
            memory_scope={"mode": "project"},
        )
        thread = self._create_thread()
        message = self.message_service.create_message(
            thread_id=thread.id,
            role="assistant",
            content="The project should preserve this answer.",
        )

        source = self.project_service.save_message_source(
            project_id=project.project_id,
            principal_id=self.principal_id,
            message_id=message.message_id,
            title="Saved answer",
        )
        sources = self.project_service.list_sources(project_id=project.project_id)

        self.assertIsNotNone(source)
        self.assertEqual(source.source_type, "message_snapshot")
        self.assertEqual(source.content, "The project should preserve this answer.")
        self.assertEqual(source.source_message_id, message.id)
        self.assertEqual(source.meta["source_message_id"], message.message_id)
        self.assertEqual([row.source_id for row in sources], [source.source_id])

    def test_threads_can_attach_to_and_leave_projects(self) -> None:
        project = self.project_service.create_project(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            title="Project Threads",
        )
        thread = self.thread_service.create_thread(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            project_id=project.id,
            title="Project conversation",
        )

        project_threads = self.thread_service.list_threads(
            principal_id=self.principal_id,
            project_id=project.id,
        )
        self.assertEqual([row.thread_id for row in project_threads], [thread.thread_id])

        updated = self.thread_service.update_thread(
            thread_row_id=thread.id,
            fields={"project_id": None, "title": "Detached conversation"},
        )
        detached_project_threads = self.thread_service.list_threads(
            principal_id=self.principal_id,
            project_id=project.id,
        )

        self.assertIsNone(updated.project_id)
        self.assertEqual(updated.title, "Detached conversation")
        self.assertEqual(detached_project_threads, [])

    def test_local_artifact_store_persists_checksum_and_resolves_inside_root(self) -> None:
        artifact = self.artifact_service.create_text_artifact(
            principal_id=self.principal_id,
            text="# Report\n\nEvidence-backed summary.",
            filename="report final.md",
            artifact_type="research_report",
        )
        path = Path(self.artifact_service.resolve_local_path(artifact))

        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "report_final.md")
        self.assertEqual(path.read_text(encoding="utf-8"), "# Report\n\nEvidence-backed summary.")
        self.assertEqual(artifact.checksum, hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):
            self.artifact_service.store.resolve_path("../escape.md")

    def test_checkpoint_restore_checkout_and_edit_retry_are_non_destructive(self) -> None:
        thread = self._create_thread()
        first = self.message_service.create_message(thread_id=thread.id, role="user", content="original question")
        self.version_service.attach_message_to_active_branch(thread_row_id=thread.id, message_row_id=first.id)
        second = self.message_service.create_message(thread_id=thread.id, role="assistant", content="original answer")
        self.version_service.attach_message_to_active_branch(thread_row_id=thread.id, message_row_id=second.id)
        checkpoint = self.version_service.create_checkpoint(thread_id=thread.thread_id, title="Before follow-up")
        third = self.message_service.create_message(thread_id=thread.id, role="user", content="follow-up")
        self.version_service.attach_message_to_active_branch(thread_row_id=thread.id, message_row_id=third.id)

        restored = self.version_service.restore_checkpoint(
            thread_id=thread.thread_id,
            checkpoint_id=checkpoint.checkpoint_id,
        )
        checkout = self.version_service.checkout_checkpoint(
            thread_id=thread.thread_id,
            checkpoint_id=checkpoint.checkpoint_id,
            title="Alternative branch",
        )
        edit_result = self.version_service.edit_retry(
            message_id=first.message_id,
            new_content="edited question",
            title="Edited branch",
        )

        self.assertEqual(restored.message_id, second.id)
        self.assertEqual(checkout.root_message_id, second.id)
        self.assertEqual(edit_result["replay_status"], "branch_created")
        self.assertEqual(edit_result["message"].content, "edited question")
        self.assertEqual(edit_result["message"].revision_of_message_id, first.id)
        self.assertEqual(edit_result["message"].variant_index, 1)

        with self.Session() as session:
            stored_thread = session.query(Thread).filter_by(id=thread.id).one()
            old_first = session.query(Message).filter_by(id=first.id).one()
            old_second = session.query(Message).filter_by(id=second.id).one()
            old_third = session.query(Message).filter_by(id=third.id).one()
            edited = session.query(Message).filter_by(id=edit_result["message"].id).one()

        self.assertEqual(stored_thread.active_branch_id, edit_result["branch"].id)
        self.assertEqual(stored_thread.current_leaf_message_id, edited.id)
        self.assertEqual(old_first.content, "original question")
        self.assertEqual(old_second.content, "original answer")
        self.assertEqual(old_third.content, "follow-up")

    def test_research_task_starts_as_editable_plan_with_read_only_source_adapters(self) -> None:
        project = self.project_service.create_project(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            title="Literature Review",
        )
        task = self.research_service.create_task(
            principal_id=self.principal_id,
            project_id=project.id,
            topic="checkpointing in agent runtimes",
            source_policy={"source_adapters": ["arxiv", "openalex"]},
            output_format="markdown",
        )
        updated = self.research_service.transition_task(
            research_task_id=task.research_task_id,
            action="start",
            fields={
                "evidence_ledger": [{"source_id": 1, "url": "https://example.test/paper"}],
            },
        )

        self.assertEqual(task.status, "planned")
        self.assertTrue(task.plan["requires_approval"])
        self.assertEqual(task.plan["source_adapters"], ["arxiv", "openalex"])
        self.assertEqual([step["id"] for step in task.plan["steps"]], ["intake", "gather", "synthesize", "artifact"])
        self.assertEqual(updated.status, "running")
        self.assertEqual(updated.evidence_ledger[0]["source_id"], 1)
        self.assertEqual(updated.meta["events"][0]["action"], "start")

        with self.assertRaises(ResearchTaskStateError) as raised:
            self.research_service.transition_task(
                research_task_id=task.research_task_id,
                fields={"plan": {"schema": "locked"}},
            )
        self.assertEqual(raised.exception.code, "research_plan_locked")

    def test_research_task_state_transitions_are_validated(self) -> None:
        task = self.research_service.create_task(
            principal_id=self.principal_id,
            topic="deep research lifecycle",
        )
        approved = self.research_service.transition_task(
            research_task_id=task.research_task_id,
            action="approve",
            fields={"plan": {"schema": "meetyou.research.plan.v1", "steps": []}},
        )
        running = self.research_service.transition_task(
            research_task_id=task.research_task_id,
            action="start",
            fields={},
        )
        cancelled = self.research_service.transition_task(
            research_task_id=task.research_task_id,
            action="cancel",
            fields={},
        )

        self.assertEqual(approved.status, "approved")
        self.assertEqual(running.status, "running")
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual([event["action"] for event in cancelled.meta["events"]], ["approve", "start", "cancel"])

        with self.assertRaises(ResearchTaskStateError) as raised:
            self.research_service.transition_task(
                research_task_id=task.research_task_id,
                action="start",
                fields={},
            )
        self.assertEqual(raised.exception.code, "research_transition_invalid")

    def test_research_report_citations_must_exist_in_evidence_ledger(self) -> None:
        validation = self.research_service.validate_report_citations(
            "Finding one [1] and finding two [2].",
            [{"source_id": 1}, {"source_id": "2"}],
        )

        self.assertEqual(validation["citation_ids"], ["1", "2"])
        self.assertEqual(validation["missing_source_ids"], [])

        with self.assertRaises(ResearchTaskCitationError) as raised:
            self.research_service.validate_report_citations(
                "This cites an unread source [3].",
                [{"source_id": 1}, {"source_id": 2}],
            )
        self.assertEqual(raised.exception.missing_source_ids, ["3"])


if __name__ == "__main__":
    unittest.main()
