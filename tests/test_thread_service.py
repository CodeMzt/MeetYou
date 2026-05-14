from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.db.models import Message, Principal, Workspace
from core.services.message_service import MessageService
from core.services.thread_service import ThreadService


class ThreadServiceTests(unittest.TestCase):
    def setUp(self) -> None:
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

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_default_thread_is_stable_and_listed(self) -> None:
        service = ThreadService(self.Session)

        first = service.ensure_default_thread(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            default_key="frontend.default",
            title="Desktop Chat",
        )
        second = service.ensure_default_thread(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            default_key="frontend.default",
            title="Ignored",
        )
        other = service.create_thread(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            title="Other",
        )
        rows = service.list_threads(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            limit=10,
        )

        self.assertEqual(first.thread_id, second.thread_id)
        self.assertEqual(first.meta.get("default_key"), "frontend.default")
        self.assertIn(first.thread_id, {row.thread_id for row in rows})
        self.assertIn(other.thread_id, {row.thread_id for row in rows})

    def test_delete_thread_soft_deletes_non_default_and_preserves_default_by_default(self) -> None:
        service = ThreadService(self.Session)
        default_thread = service.ensure_default_thread(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            default_key="frontend.default",
            title="Desktop Chat",
        )
        other = service.create_thread(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            title="Other",
        )

        default_result = service.delete_thread(
            principal_id=self.principal_id,
            thread_id=default_thread.thread_id,
        )
        other_result = service.delete_thread(
            principal_id=self.principal_id,
            thread_id=other.thread_id,
        )
        rows = service.list_threads(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            limit=10,
        )

        self.assertFalse(default_result.deleted)
        self.assertEqual(default_result.reason, "default_thread")
        self.assertTrue(other_result.deleted)
        self.assertNotIn(other.thread_id, {row.thread_id for row in rows})
        self.assertIn(default_thread.thread_id, {row.thread_id for row in rows})

    def test_message_context_window_is_bounded_chronological_and_excludes_current(self) -> None:
        thread_service = ThreadService(self.Session)
        message_service = MessageService(self.Session)
        thread = thread_service.create_thread(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            title="Context thread",
        )
        rows = [
            message_service.create_message(thread_id=thread.id, role="user", content="old user"),
            message_service.create_message(thread_id=thread.id, role="assistant", content="old assistant"),
            message_service.create_message(thread_id=thread.id, role="user", content="recent user"),
            message_service.create_message(thread_id=thread.id, role="assistant", content="recent assistant"),
            message_service.create_message(
                thread_id=thread.id,
                role="user",
                content="current user",
                meta={"endpoint_message_id": "endpoint-current"},
            ),
        ]
        ignored = message_service.create_message(
            thread_id=thread.id,
            role="tool",
            content="tool output",
        )
        base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with self.Session() as session:
            for index, row in enumerate([*rows, ignored]):
                persisted = session.get(Message, row.id)
                persisted.created_at = base_time + timedelta(seconds=index)
            session.commit()

        window = message_service.load_thread_context_window(
            thread_id=thread.id,
            before_message_id=rows[-1].message_id,
            limit=2,
        )
        self.assertEqual([row.content for row in window["messages"]], ["recent user", "recent assistant"])
        self.assertEqual(window["total_count"], 4)
        self.assertEqual(window["older_count"], 2)

        older = message_service.list_older_thread_context_messages(
            thread_id=thread.id,
            before_message_id=rows[-1].message_id,
            offset=2,
            limit=10,
        )
        self.assertEqual([row.content for row in older], ["old user", "old assistant"])

        endpoint_excluded = message_service.load_thread_context_window(
            thread_id=thread.id,
            exclude_endpoint_message_id="endpoint-current",
            limit=4,
        )
        self.assertEqual(
            [row.content for row in endpoint_excluded["messages"]],
            ["old user", "old assistant", "recent user", "recent assistant"],
        )
        self.assertNotIn("current user", {row.content for row in endpoint_excluded["messages"]})
        self.assertEqual(endpoint_excluded["older_count"], 0)

    def test_first_user_message_marks_default_thread_for_model_auto_title(self) -> None:
        thread_service = ThreadService(self.Session)
        message_service = MessageService(self.Session)
        default_thread = thread_service.create_thread(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            title="新会话",
        )
        manual_thread = thread_service.create_thread(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            title="人工标题",
        )

        first = message_service.create_message(
            thread_id=default_thread.id,
            role="user",
            content="请帮我研究救国会在近代史中的作用，并给出引用。",
        )
        message_service.create_message(
            thread_id=manual_thread.id,
            role="user",
            content="这条消息不应该覆盖人工标题。",
        )
        message_service.create_message(
            thread_id=default_thread.id,
            role="user",
            content="第二条消息不应该再次改名。",
        )

        pending = thread_service.get_by_thread_id(default_thread.thread_id)
        preserved = thread_service.get_by_thread_id(manual_thread.thread_id)
        self.assertEqual(pending.title, "新会话")
        self.assertTrue(pending.meta["auto_title_pending"])
        self.assertEqual(pending.meta["auto_title_source_message_id"], first.message_id)
        self.assertEqual(preserved.title, "人工标题")

        applied = thread_service.apply_auto_title(
            thread_id=default_thread.thread_id,
            title="近代救国会研究",
            source_message_id=first.message_id,
            model="test-title-model",
            provider="test",
        )

        self.assertIsNotNone(applied)
        renamed = thread_service.get_by_thread_id(default_thread.thread_id)
        self.assertEqual(renamed.title, "近代救国会研究")
        self.assertTrue(renamed.meta["auto_title"])
        self.assertFalse(renamed.meta["auto_title_pending"])
        self.assertEqual(renamed.meta["auto_title_model"], "test-title-model")


if __name__ == "__main__":
    unittest.main()
