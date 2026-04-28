from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.io_protocol import make_source
from core.runtime_context import bind_event_context, get_event_context, reset_event_context
from core.session_manager import SessionManager
from tools.workspace_tools import WorkspaceTools


class _WorkspaceService:
    def __init__(self):
        self.personal = SimpleNamespace(
            id="workspace-row-personal",
            workspace_id="personal",
            title="Personal",
            base_mode="general",
            description="",
            default_execution_target="core_only",
            meta={},
        )
        self.workspace = SimpleNamespace(
            id="workspace-row-study",
            workspace_id="study",
            title="Study",
            base_mode="general",
            description="Study zone",
            default_execution_target="specific_endpoint",
            meta={"memory_ranking_policy": "workspace_first"},
        )

    def get_by_workspace_id(self, workspace_id: str):
        return {"study": self.workspace, "personal": self.personal}.get(workspace_id)

    def get_by_id(self, row_id):
        return {"workspace-row-study": self.workspace, "workspace-row-personal": self.personal}.get(row_id)

    def list_workspaces(self):
        return [self.personal, self.workspace]

    def get_governance_view(self, workspace):
        return {
            "description": getattr(workspace, "description", ""),
            "default_execution_target": getattr(workspace, "default_execution_target", "core_only"),
            "memory_ranking_policy": (getattr(workspace, "meta", {}) or {}).get("memory_ranking_policy", "workspace_first"),
        }


class _SessionService:
    def __init__(self):
        self.row = SimpleNamespace(
            id="session-row-1",
            session_id="sess_1",
            thread_id="thread-row-1",
            client_id="client-row-1",
            active_workspace_id="workspace-row-personal",
            status="active",
        )
        self.updates: list[dict] = []

    def get_by_session_id(self, session_id: str):
        return self.row if session_id == "sess_1" else None

    def set_active_workspace(self, **kwargs):
        self.updates.append(dict(kwargs))
        self.row.active_workspace_id = kwargs["active_workspace_id"]
        return self.row


class _ThreadService:
    def get_by_id(self, row_id):
        if row_id == "thread-row-1":
            return SimpleNamespace(id=row_id, thread_id="thr_1", home_workspace_id="workspace-row-personal")
        return None


class _ClientService:
    def __init__(self):
        self.binds: list[dict] = []

    def get_by_id(self, row_id):
        if row_id == "client-row-1":
            return SimpleNamespace(id=row_id, client_id="desktop-app")
        return None

    def bind_workspace(self, **kwargs):
        self.binds.append(dict(kwargs))
        return SimpleNamespace(**kwargs)

    def list_clients_for_workspace(self, workspace_id):
        if workspace_id == "workspace-row-personal":
            return [(SimpleNamespace(client_id="desktop-app", client_type="electron", display_name="Desktop"), SimpleNamespace())]
        if workspace_id == "workspace-row-study":
            return [(SimpleNamespace(client_id="study-client", client_type="desktop", display_name="Study Client"), SimpleNamespace())]
        return []


class _EndpointService:
    def list_all(self):
        return [
            SimpleNamespace(
                endpoint_id="desktop-app",
                endpoint_type="desktop_executor",
                provider_type="desktop",
                workspace_scope=["personal"],
                status="online",
                meta={"display_name": "Desktop"},
            ),
            SimpleNamespace(
                endpoint_id="study-endpoint",
                endpoint_type="desktop_executor",
                provider_type="desktop",
                workspace_scope=["study"],
                status="online",
                meta={"display_name": "Study Endpoint"},
            ),
        ]


class _Gateway:
    def __init__(self):
        self.events: list[dict] = []

    async def publish_client_thread_event(self, thread_id: str, *, event_type: str, payload: dict) -> None:
        self.events.append({"thread_id": thread_id, "event_type": event_type, "payload": dict(payload)})


class WorkspaceToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_switch_workspace_updates_session_binding_and_publishes_event(self):
        session_service = _SessionService()
        client_service = _ClientService()
        gateway = _Gateway()
        session_manager = SessionManager()
        source = make_source("web", "desktop-app", client_id="desktop-app")

        tools = WorkspaceTools()
        tools.set_core_domain(
            SimpleNamespace(
                services=SimpleNamespace(
                    workspace=_WorkspaceService(),
                    session=session_service,
                    thread=_ThreadService(),
                    client=client_service,
                    endpoint=_EndpointService(),
                )
            )
        )
        tools.set_runtime(session_manager=session_manager, gateway_getter=lambda: gateway)

        token = bind_event_context(session_id="sess_1", source=source)
        try:
            result = await tools.switch_workspace("study", reason="continue study work")
            runtime_context = get_event_context()
        finally:
            reset_event_context(token)

        self.assertTrue(result["ok"])
        self.assertEqual(result["active_workspace_id"], "study")
        self.assertEqual(session_service.updates[0]["active_workspace_id"], "workspace-row-study")
        self.assertEqual(client_service.binds[0]["workspace_id"], "workspace-row-study")
        binding = session_manager.get_binding("sess_1")
        self.assertIsNotNone(binding)
        self.assertEqual(binding.metadata["active_workspace_id"], "study")
        self.assertEqual(runtime_context["active_workspace_id"], "study")
        self.assertEqual(gateway.events[0]["event_type"], "workspace.changed")
        self.assertEqual(gateway.events[0]["payload"]["active_workspace_id"], "study")

    async def test_list_workspaces_reports_active_workspace(self):
        tools = WorkspaceTools()
        tools.set_core_domain(
            SimpleNamespace(
                services=SimpleNamespace(
                    workspace=_WorkspaceService(),
                    session=_SessionService(),
                    thread=_ThreadService(),
                    client=_ClientService(),
                    endpoint=_EndpointService(),
                )
            )
        )

        token = bind_event_context(session_id="sess_1", active_workspace_id="study")
        try:
            result = await tools.list_workspaces(include_endpoints=True)
        finally:
            reset_event_context(token)

        self.assertTrue(result["ok"])
        self.assertEqual(result["active_workspace_id"], "study")
        rows = {item["workspace_id"]: item for item in result["workspaces"]}
        self.assertTrue(rows["study"]["active"])
        self.assertFalse(rows["personal"]["active"])
        self.assertEqual(rows["study"]["endpoints"][0]["endpoint_id"], "study-endpoint")
        self.assertEqual(rows["personal"]["endpoints"][0]["endpoint_id"], "desktop-app")


if __name__ == "__main__":
    unittest.main()
