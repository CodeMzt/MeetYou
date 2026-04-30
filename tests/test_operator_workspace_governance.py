from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.services.workspace_service import WorkspaceService
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway


class _WorkspaceService:
    def __init__(self):
        self.workspace = SimpleNamespace(
            workspace_id="personal",
            title="Personal",
            status="active",
            base_mode="general",
            description="Personal workspace",
            prompt_overlay="",
            default_execution_target="core.local",
            meta={
                "tool_policy": "allow_all",
                "allowed_tool_ids": [],
                "preferred_target_endpoint_ids": [],
                "preferred_endpoint_provider_types": [],
                "preferred_source_profiles": [],
                "tool_target_routing_policy": "balanced",
                "memory_ranking_policy": "workspace_first",
                "tool_routing_overrides": {},
            },
        )
        self.last_update: dict | None = None

    def list_workspaces(self):
        return [self.workspace]

    def get_by_workspace_id(self, workspace_id):
        return self.workspace if workspace_id == "personal" else None

    def update_workspace(self, **kwargs):
        self.last_update = dict(kwargs)
        if kwargs.get("base_mode") is not None:
            self.workspace.base_mode = kwargs["base_mode"]
        if kwargs.get("default_execution_target") is not None:
            self.workspace.default_execution_target = kwargs["default_execution_target"]
        if kwargs.get("metadata") is not None:
            merged = dict(self.workspace.meta or {})
            merged.update(dict(kwargs["metadata"]))
            self.workspace.meta = WorkspaceService.normalize_governance_metadata(merged)
        return self.workspace


class OperatorWorkspaceGovernanceTests(unittest.TestCase):
    def test_patch_updates_workspace_routing_governance_fields(self):
        workspace_service = _WorkspaceService()
        gateway = FastAPIGateway(
            EventBus(),
            SessionManager(),
            core_domain=SimpleNamespace(
                principal=SimpleNamespace(id="principal-row"),
                services=SimpleNamespace(workspace=workspace_service),
            ),
            access_token="operator-token",
        )
        client = TestClient(gateway.app)

        response = client.patch(
            "/operator/workspaces/personal",
            headers={"Authorization": "Bearer operator-token"},
            json={
                "default_execution_target": "workspace_any_endpoint",
                "tool_policy": "allowlist",
                "allowed_tool_ids": ["utility.echo", "delivery.message"],
                "preferred_target_endpoint_ids": ["desktop.personal.executor"],
                "preferred_endpoint_provider_types": ["desktop"],
                "tool_target_routing_policy": "strict_preferred_endpoint",
                "tool_routing_overrides": {
                    "utility.echo": {
                        "preferred_target_endpoint_ids": ["desktop.personal.executor"],
                        "tool_target_routing_policy": "strict_preferred_endpoint",
                    },
                },
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["default_execution_target"], "workspace_any_endpoint")
        self.assertEqual(payload["tool_policy"], "allowlist")
        self.assertEqual(payload["allowed_tool_ids"], ["utility.echo", "delivery.message"])
        self.assertEqual(payload["preferred_target_endpoint_ids"], ["desktop.personal.executor"])
        self.assertEqual(payload["preferred_endpoint_provider_types"], ["desktop"])
        self.assertEqual(payload["tool_target_routing_policy"], "strict_preferred_endpoint")
        self.assertIn("utility.echo", payload["tool_routing_overrides"])
        self.assertEqual(workspace_service.last_update["default_execution_target"], "workspace_any_endpoint")
        self.assertEqual(
            workspace_service.last_update["metadata"]["preferred_target_endpoint_ids"],
            ["desktop.personal.executor"],
        )


if __name__ == "__main__":
    unittest.main()
