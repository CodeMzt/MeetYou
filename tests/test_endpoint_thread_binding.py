from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.db.models import Endpoint, Principal, Thread, Workspace
from core.services.endpoint_service import (
    EndpointCapabilityService,
    EndpointThreadBindingError,
    EndpointThreadBindingService,
)


class EndpointThreadBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        with self.Session() as session:
            principal = Principal(principal_key="self", display_name="Self")
            other_principal = Principal(principal_key="other", display_name="Other")
            session.add_all([principal, other_principal])
            session.flush()
            workspace = Workspace(workspace_id="personal", principal_id=principal.id, title="Personal")
            other_workspace = Workspace(workspace_id="other", principal_id=principal.id, title="Other")
            endpoint = Endpoint(
                endpoint_id="wechat.meetwechat.ui",
                endpoint_type="wechat_ui",
                provider_type="wechat",
                transport_type="websocket",
                workspace_scope=["personal"],
                status="online",
            )
            session.add_all([workspace, other_workspace, endpoint])
            session.flush()
            explicit_thread = Thread(
                thread_id="thr_explicit",
                principal_id=principal.id,
                home_workspace_id=workspace.id,
                title="Explicit",
            )
            foreign_workspace_thread = Thread(
                thread_id="thr_other_workspace",
                principal_id=principal.id,
                home_workspace_id=other_workspace.id,
                title="Other Workspace",
            )
            session.add_all([explicit_thread, foreign_workspace_thread])
            session.commit()
            self.principal_id = principal.id
            self.workspace_id = workspace.id
            self.workspace_public_id = workspace.workspace_id
            self.endpoint_id = endpoint.id
            self.endpoint_public_id = endpoint.endpoint_id

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_per_conversation_resolution_is_idempotent(self) -> None:
        service = EndpointThreadBindingService(self.Session)

        first_binding, first_thread = service.resolve_thread(
            principal_id=self.principal_id,
            endpoint_row_id=self.endpoint_id,
            endpoint_public_id=self.endpoint_public_id,
            workspace_row_id=self.workspace_id,
            workspace_public_id=self.workspace_public_id,
            thread_strategy="per_conversation",
            conversation_key="wechat:chat:one",
            title="Chat One",
        )
        second_binding, second_thread = service.resolve_thread(
            principal_id=self.principal_id,
            endpoint_row_id=self.endpoint_id,
            endpoint_public_id=self.endpoint_public_id,
            workspace_row_id=self.workspace_id,
            workspace_public_id=self.workspace_public_id,
            thread_strategy="per_conversation",
            conversation_key="wechat:chat:one",
            title="Ignored",
        )
        _, other_thread = service.resolve_thread(
            principal_id=self.principal_id,
            endpoint_row_id=self.endpoint_id,
            endpoint_public_id=self.endpoint_public_id,
            workspace_row_id=self.workspace_id,
            workspace_public_id=self.workspace_public_id,
            thread_strategy="per_conversation",
            conversation_key="wechat:chat:two",
            title="Chat Two",
        )

        self.assertEqual(first_binding.binding_id, second_binding.binding_id)
        self.assertEqual(first_thread.thread_id, second_thread.thread_id)
        self.assertNotEqual(first_thread.thread_id, other_thread.thread_id)
        self.assertEqual(first_binding.conversation_key, "conversation:wechat:chat:one")

    def test_per_conversation_treats_explicit_thread_as_non_authoritative_hint(self) -> None:
        service = EndpointThreadBindingService(self.Session)

        _, thread = service.resolve_thread(
            principal_id=self.principal_id,
            endpoint_row_id=self.endpoint_id,
            endpoint_public_id=self.endpoint_public_id,
            workspace_row_id=self.workspace_id,
            workspace_public_id=self.workspace_public_id,
            thread_strategy="per_conversation",
            conversation_key="wechat:chat:stale-cache",
            explicit_thread_id="thr_missing",
            title="Stale Cache",
        )

        self.assertNotEqual(thread.thread_id, "thr_missing")
        self.assertTrue(thread.thread_id.startswith("thr_"))

    def test_per_conversation_rebinds_when_previous_thread_was_deleted(self) -> None:
        service = EndpointThreadBindingService(self.Session)

        binding, first_thread = service.resolve_thread(
            principal_id=self.principal_id,
            endpoint_row_id=self.endpoint_id,
            endpoint_public_id=self.endpoint_public_id,
            workspace_row_id=self.workspace_id,
            workspace_public_id=self.workspace_public_id,
            thread_strategy="per_conversation",
            conversation_key="wechat:chat:deleted",
            title="Deleted Chat",
        )
        with self.Session() as session:
            row = session.query(Thread).filter_by(thread_id=first_thread.thread_id).one()
            row.status = "deleted"
            session.commit()

        rebound_binding, rebound_thread = service.resolve_thread(
            principal_id=self.principal_id,
            endpoint_row_id=self.endpoint_id,
            endpoint_public_id=self.endpoint_public_id,
            workspace_row_id=self.workspace_id,
            workspace_public_id=self.workspace_public_id,
            thread_strategy="per_conversation",
            conversation_key="wechat:chat:deleted",
            title="Deleted Chat",
            explicit_thread_id=first_thread.thread_id,
        )

        self.assertEqual(binding.binding_id, rebound_binding.binding_id)
        self.assertNotEqual(first_thread.thread_id, rebound_thread.thread_id)
        self.assertEqual(rebound_binding.thread_id, rebound_thread.id)
        self.assertEqual(rebound_thread.status, "active")

    def test_explicit_thread_requires_existing_accessible_thread(self) -> None:
        service = EndpointThreadBindingService(self.Session)

        _, explicit_thread = service.resolve_thread(
            principal_id=self.principal_id,
            endpoint_row_id=self.endpoint_id,
            endpoint_public_id=self.endpoint_public_id,
            workspace_row_id=self.workspace_id,
            workspace_public_id=self.workspace_public_id,
            thread_strategy="explicit_thread",
            explicit_thread_id="thr_explicit",
        )

        self.assertEqual(explicit_thread.thread_id, "thr_explicit")
        with self.assertRaises(EndpointThreadBindingError) as mismatch:
            service.resolve_thread(
                principal_id=self.principal_id,
                endpoint_row_id=self.endpoint_id,
                endpoint_public_id=self.endpoint_public_id,
                workspace_row_id=self.workspace_id,
                workspace_public_id=self.workspace_public_id,
                thread_strategy="explicit_thread",
                explicit_thread_id="thr_other_workspace",
            )
        self.assertEqual(mismatch.exception.code, "explicit_thread_workspace_mismatch")
        with self.assertRaises(EndpointThreadBindingError) as missing:
            service.resolve_thread(
                principal_id=self.principal_id,
                endpoint_row_id=self.endpoint_id,
                endpoint_public_id=self.endpoint_public_id,
                workspace_row_id=self.workspace_id,
                workspace_public_id=self.workspace_public_id,
                thread_strategy="explicit_thread",
                explicit_thread_id="thr_missing",
            )
        self.assertEqual(missing.exception.code, "explicit_thread_not_found")


class EndpointCapabilityCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        with self.Session() as session:
            endpoint = Endpoint(
                endpoint_id="desktop.main.executor",
                endpoint_type="desktop_executor",
                provider_type="desktop",
                transport_type="websocket",
                workspace_scope=["personal"],
                status="online",
            )
            session.add(endpoint)
            session.commit()
            self.endpoint_id = endpoint.id

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_snapshot_preserves_endpoint_tool_catalog_fields(self) -> None:
        service = EndpointCapabilityService(self.Session)

        service.replace_snapshot(
            endpoint_row_id=self.endpoint_id,
            endpoint_public_id="desktop.main.executor",
            capabilities=[
                {
                    "tool_key": "mcp.filesystem.read_file",
                    "tool_id": "endpoint.desktop.main.executor.mcp.filesystem.read_file",
                    "title": "Read File",
                    "description": "Read a file from the desktop endpoint.",
                    "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
                    "output_schema": {"type": "object", "properties": {"content": {"type": "string"}}},
                    "risk_level": "read",
                    "requires_confirmation": False,
                    "enabled": True,
                    "visibility": {"auto_inject": True},
                    "constraints": {"workspace_ids": ["personal"], "timeout": 30},
                }
            ],
        )

        rows = service.list_for_endpoint(endpoint_row_id=self.endpoint_id)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.schema["properties"]["path"]["type"], "string")
        self.assertEqual(row.meta["title"], "Read File")
        self.assertEqual(row.meta["description"], "Read a file from the desktop endpoint.")
        self.assertEqual(row.meta["input_schema"]["type"], "object")
        self.assertEqual(row.meta["output_schema"]["properties"]["content"]["type"], "string")
        self.assertTrue(row.meta["visibility"]["auto_inject"])
        self.assertEqual(row.constraints["timeout"], 30)


if __name__ == "__main__":
    unittest.main()
