from __future__ import annotations

from types import SimpleNamespace
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db.base import Base
from core.db.bootstrap import build_core_services
from core.event_bus import EventBus
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway


class OperatorWorkspaceTopologyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.services = build_core_services(self.session_factory)
        self.principal = self.services.principal.ensure_principal(principal_key="self", display_name="Self")
        self.personal = self.services.workspace.ensure_workspace(
            workspace_id="personal",
            principal_id=self.principal.id,
            title="Personal",
        )
        self.study = self.services.workspace.ensure_workspace(
            workspace_id="study",
            principal_id=self.principal.id,
            title="Study",
        )
        endpoint = self.services.endpoint.ensure_endpoint(
            endpoint_id="desktop.main.executor",
            endpoint_type="desktop_executor",
            provider_type="desktop",
            transport_type="websocket",
            workspace_scope=["personal"],
            metadata={"display_name": "Desktop Main"},
        )
        self.services.endpoint_workspace_membership.seed_endpoint_memberships(
            endpoint_row_id=endpoint.id,
            workspace_ids=["personal"],
        )
        self.services.endpoint_capability.upsert_capability(
            endpoint_row_id=endpoint.id,
            tool_key="shell.exec",
            capability_id="endpoint.desktop.main.executor.shell.exec",
        )
        address = self.services.endpoint_address.upsert_address(
            endpoint_row_id=endpoint.id,
            provider_type="desktop",
            address_type="direct",
            external_ref="self",
            address_id="addr.desktop.direct.self",
            display_name="Desktop Direct",
            workspace_scope=["personal"],
        )
        self.services.endpoint_address_workspace_membership.seed_address_memberships(
            address_row_id=address.id,
            workspace_ids=["personal"],
        )
        gateway = FastAPIGateway(
            EventBus(),
            SessionManager(),
            core_domain=SimpleNamespace(principal=self.principal, services=self.services),
            access_token="operator-token",
        )
        self.client = TestClient(gateway.app)

    def tearDown(self):
        self.engine.dispose()

    def _headers(self):
        return {"Authorization": "Bearer operator-token"}

    def test_topology_reports_workspaces_endpoints_addresses_and_capabilities(self):
        response = self.client.get("/operator/workspace-topology", headers=self._headers())

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        endpoint = payload["endpoints"][0]
        address = payload["addresses"][0]
        personal = next(item for item in payload["workspaces"] if item["workspace_id"] == "personal")
        self.assertEqual(endpoint["endpoint_id"], "desktop.main.executor")
        self.assertEqual(endpoint["workspace_ids"], ["personal"])
        self.assertEqual(endpoint["primary_workspace_id"], "personal")
        self.assertIn("shell.exec", endpoint["executable_tools"])
        self.assertEqual(address["workspace_ids"], ["personal"])
        self.assertEqual(personal["endpoint_count"], 1)

    def test_endpoint_move_sets_primary_and_keeps_existing_membership(self):
        response = self.client.patch(
            "/operator/endpoints/desktop.main.executor/primary-workspace",
            headers=self._headers(),
            json={"workspace_id": "study"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["primary_workspace_id"], "study")
        self.assertEqual(payload["workspace_ids"], ["study", "personal"])

    def test_workspace_update_archive_restore_and_personal_archive_guard(self):
        update = self.client.patch(
            "/operator/workspaces/study",
            headers=self._headers(),
            json={"title": "Study Space", "description": "Notes", "prompt_overlay": "Study mode"},
        )
        self.assertEqual(update.status_code, 200, update.text)
        self.assertEqual(update.json()["title"], "Study Space")
        self.assertEqual(update.json()["description"], "Notes")
        self.assertEqual(update.json()["prompt_overlay"], "Study mode")

        archived = self.client.delete("/operator/workspaces/study", headers=self._headers())
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(archived.json()["status"], "archived")
        hidden = self.client.get("/operator/workspaces", headers=self._headers())
        self.assertNotIn("study", {item["workspace_id"] for item in hidden.json()})

        restored = self.client.post("/operator/workspaces/study/restore", headers=self._headers())
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["status"], "active")
        forbidden = self.client.delete("/operator/workspaces/personal", headers=self._headers())
        self.assertEqual(forbidden.status_code, 400)

    def test_address_workspace_membership_can_be_moved(self):
        response = self.client.patch(
            "/operator/addresses/addr.desktop.direct.self/primary-workspace",
            headers=self._headers(),
            json={"workspace_id": "study"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["target_type"], "address")
        self.assertEqual(payload["primary_workspace_id"], "study")
        self.assertEqual(payload["workspace_ids"], ["study", "personal"])

        removed = self.client.delete(
            "/operator/addresses/addr.desktop.direct.self/workspaces/personal",
            headers=self._headers(),
        )
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(removed.json()["workspace_ids"], ["study"])
        last = self.client.delete(
            "/operator/addresses/addr.desktop.direct.self/workspaces/study",
            headers=self._headers(),
        )
        self.assertEqual(last.status_code, 400)


if __name__ == "__main__":
    unittest.main()
