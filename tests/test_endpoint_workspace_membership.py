from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.db.bootstrap import build_core_services


class EndpointWorkspaceMembershipTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
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

    def tearDown(self):
        self.engine.dispose()

    def test_provider_seed_does_not_override_core_managed_primary_workspace(self):
        endpoint = self.services.endpoint.ensure_endpoint(
            endpoint_id="desktop.main.executor",
            endpoint_type="desktop_executor",
            provider_type="desktop",
            transport_type="websocket",
            workspace_scope=["personal"],
        )
        seeded_scope = self.services.endpoint_workspace_membership.seed_endpoint_memberships(
            endpoint_row_id=endpoint.id,
            workspace_ids=["personal"],
        )

        self.assertEqual(seeded_scope, ["personal"])

        result = self.services.endpoint_workspace_membership.set_primary_workspace(
            endpoint_id="desktop.main.executor",
            workspace_id="study",
        )
        self.assertEqual(result["primary_workspace_id"], "study")
        self.assertEqual(result["workspace_ids"], ["study", "personal"])

        reseeded_scope = self.services.endpoint_workspace_membership.seed_endpoint_memberships(
            endpoint_row_id=endpoint.id,
            workspace_ids=["personal"],
        )
        refreshed = self.services.endpoint.get_by_endpoint_id("desktop.main.executor")

        self.assertEqual(reseeded_scope, ["study", "personal"])
        self.assertEqual(refreshed.workspace_scope, ["study", "personal"])
        self.assertEqual((refreshed.meta or {}).get("primary_workspace_id"), "study")

    def test_remove_membership_syncs_cache_and_rejects_last_workspace(self):
        endpoint = self.services.endpoint.ensure_endpoint(
            endpoint_id="desktop.main.executor",
            endpoint_type="desktop_executor",
            provider_type="desktop",
            transport_type="websocket",
            workspace_scope=["personal"],
        )
        self.services.endpoint_workspace_membership.seed_endpoint_memberships(
            endpoint_row_id=endpoint.id,
            workspace_ids=["personal", "study"],
        )

        result = self.services.endpoint_workspace_membership.remove_workspace(
            endpoint_id="desktop.main.executor",
            workspace_id="personal",
        )
        refreshed = self.services.endpoint.get_by_endpoint_id("desktop.main.executor")

        self.assertEqual(result["workspace_ids"], ["study"])
        self.assertEqual(refreshed.workspace_scope, ["study"])
        with self.assertRaises(ValueError):
            self.services.endpoint_workspace_membership.remove_workspace(
                endpoint_id="desktop.main.executor",
                workspace_id="study",
            )

    def test_core_endpoints_are_readonly_for_workspace_membership_mutations(self):
        self.services.endpoint.ensure_endpoint(
            endpoint_id="core.local",
            endpoint_type="core_local",
            provider_type="core",
            transport_type="inproc",
        )

        with self.assertRaises(ValueError):
            self.services.endpoint_workspace_membership.set_primary_workspace(
                endpoint_id="core.local",
                workspace_id="personal",
            )


if __name__ == "__main__":
    unittest.main()
