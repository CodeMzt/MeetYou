from __future__ import annotations

import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.db.models import Principal, Workspace
from core.runtime_context import bind_event_context, reset_event_context
from core.services.session_service import SessionService
from core.services.thread_service import ThreadService
from core.services.workspace_service import WorkspaceService
from tools.thread_tools import ThreadTools


class _Gateway:
    def __init__(self) -> None:
        self.events = []

    async def publish_thread_delivery_event(self, thread_id: str, *, event_type: str, payload: dict) -> int:
        self.events.append((thread_id, event_type, dict(payload)))
        return 1


class ThreadToolsTests(unittest.IsolatedAsyncioTestCase):
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
        self.gateway = _Gateway()
        self.tools = ThreadTools()
        self.tools.set_core_domain(
            SimpleNamespace(
                principal=SimpleNamespace(id=self.principal_id),
                services=SimpleNamespace(
                    thread=ThreadService(self.Session),
                    workspace=WorkspaceService(self.Session),
                    session=SessionService(self.Session),
                ),
            )
        )
        self.tools.set_runtime(gateway_getter=lambda: self.gateway)

    def tearDown(self) -> None:
        self.engine.dispose()

    async def test_create_list_switch_and_delete_threads(self) -> None:
        default_thread = self.tools._core_domain.services.thread.ensure_default_thread(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            default_key="frontend.default",
            title="Desktop Chat",
        )
        token = bind_event_context(thread_id=default_thread.thread_id, workspace_id="personal", session_id="sess_1")
        try:
            created = await self.tools.manage_threads(action="create", title="Scratch", switch_after_create=True)
            self.assertTrue(created["ok"])
            new_thread_id = created["thread"]["thread_id"]
            self.assertEqual(self.gateway.events[0][1], "thread.switched")
            self.assertEqual(self.gateway.events[0][2]["target_thread_id"], new_thread_id)

            listed = await self.tools.manage_threads(action="list")
            self.assertIn(new_thread_id, {item["thread_id"] for item in listed["threads"]})

            deleted = await self.tools.manage_threads(action="delete", thread_id=new_thread_id)
            self.assertTrue(deleted["deleted"])
            self.assertEqual(deleted["fallback_thread_id"], default_thread.thread_id)
        finally:
            reset_event_context(token)


if __name__ == "__main__":
    unittest.main()
