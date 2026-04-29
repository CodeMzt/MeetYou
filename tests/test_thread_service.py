from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.db.models import Principal, Workspace
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


if __name__ == "__main__":
    unittest.main()
