from __future__ import annotations

import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.db.bootstrap import build_core_services
from core.db.models import Principal, Workspace
from tools.project_tools import ProjectTools


class ProjectToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
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
        self.domain = SimpleNamespace(services=self.services, principal=self.principal)
        self.tools = ProjectTools()
        self.tools.set_core_domain(self.domain)

    def tearDown(self) -> None:
        self.engine.dispose()

    async def test_manage_projects_and_sources(self) -> None:
        created = await self.tools.manage_projects(
            action="create",
            workspace_id="personal",
            title="Tool Project",
            description="Project managed from tool.",
            instructions="Use project sources.",
        )
        self.assertTrue(created["ok"])
        project_id = created["project"]["project_id"]

        listed = await self.tools.manage_projects(action="list", workspace_id="personal")
        self.assertEqual([row["project_id"] for row in listed["projects"]], [project_id])

        source = await self.tools.manage_project_sources(
            action="create",
            project_id=project_id,
            title="Tool source",
            content="Durable project source content.",
        )
        self.assertTrue(source["ok"])
        source_id = source["source"]["source_id"]

        loaded_source = await self.tools.manage_project_sources(
            action="get",
            project_id=project_id,
            source_id=source_id,
        )
        self.assertEqual(loaded_source["source"]["content"], "Durable project source content.")

        archived_source = await self.tools.manage_project_sources(
            action="delete",
            project_id=project_id,
            source_id=source_id,
        )
        self.assertTrue(archived_source["ok"])
        self.assertEqual(archived_source["source"]["status"], "archived")
        active_sources = await self.tools.manage_project_sources(action="list", project_id=project_id)
        self.assertEqual(active_sources["sources"], [])

        thread = self.services.thread.create_thread(
            principal_id=self.principal.id,
            workspace_id=self.workspace.id,
            title="Tool thread",
        )
        attached = await self.tools.manage_projects(
            action="attach_thread",
            project_id=project_id,
            thread_id=thread.thread_id,
        )
        self.assertEqual(attached["thread"]["project_id"], project_id)

        project_threads = await self.tools.manage_projects(action="list_threads", project_id=project_id)
        self.assertEqual([row["thread_id"] for row in project_threads["threads"]], [thread.thread_id])

        message = self.services.message.create_message(
            thread_id=thread.id,
            role="assistant",
            content="Snapshot me into the project.",
        )
        saved = await self.tools.manage_project_sources(
            action="save_message",
            project_id=project_id,
            message_id=message.message_id,
            title="Saved message",
        )
        self.assertEqual(saved["source"]["source_type"], "message_snapshot")
        self.assertEqual(saved["source"]["content"], "Snapshot me into the project.")

        detached = await self.tools.manage_projects(
            action="detach_thread",
            thread_id=thread.thread_id,
        )
        self.assertEqual(detached["thread"]["project_id"], "")

        archived = await self.tools.manage_projects(action="archive", project_id=project_id)
        self.assertEqual(archived["project"]["status"], "archived")


if __name__ == "__main__":
    unittest.main()
