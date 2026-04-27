from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from core.services.tool_router_service import ToolRouterService


class _WorkspaceService:
    workspace = SimpleNamespace(id="workspace-row", workspace_id="desktop-main")

    def get_by_workspace_id(self, workspace_id: str):
        return self.workspace if workspace_id == "desktop-main" else None

    def get_by_id(self, row_id):
        return self.workspace if row_id == self.workspace.id else None


class _EndpointService:
    endpoint = SimpleNamespace(
        id="endpoint-row",
        endpoint_id="desktop.main.executor",
        provider_type="desktop",
        status="ready",
        workspace_scope=["desktop-main"],
    )

    def get_by_endpoint_id(self, endpoint_id: str):
        return self.endpoint if endpoint_id == self.endpoint.endpoint_id else None

    def get_by_id(self, row_id):
        return self.endpoint if row_id == self.endpoint.id else None


class _EndpointCapabilityService:
    capability = SimpleNamespace(
        id="capability-row",
        endpoint_id="endpoint-row",
        capability_id="endpoint.desktop.main.executor.file.read",
        tool_key="file.read",
        enabled=True,
        requires_confirmation=False,
        risk_level="read",
    )

    def list_for_endpoint(self, *, endpoint_row_id):
        return [self.capability] if endpoint_row_id == "endpoint-row" else []

    def list_enabled_for_tool(self, *, tool_key: str):
        return [self.capability] if tool_key == "file.read" else []


class _OperationService:
    def __init__(self):
        self.operations: list[dict] = []

    def create_operation(self, **kwargs):
        self.operations.append(dict(kwargs))
        return SimpleNamespace(id="operation-row", operation_id="op_1", **kwargs)


class _OperationCallService:
    def __init__(self):
        self.created: list[dict] = []
        self.statuses: list[tuple[str, str]] = []

    def create_call(self, **kwargs):
        self.created.append(dict(kwargs))
        return SimpleNamespace(id="call-row", call_id="call_1", **kwargs)

    def mark_dispatched(self, *, call_id: str):
        self.statuses.append((call_id, "dispatched"))

    def mark_succeeded(self, *, call_id: str, result: dict):
        self.statuses.append((call_id, "succeeded"))

    def mark_failed(self, *, call_id: str, error: dict):
        self.statuses.append((call_id, "failed"))


class EndpointToolDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_router_dispatches_endpoint_tool_request_frame(self):
        operation_service = _OperationService()
        call_service = _OperationCallService()
        router = ToolRouterService(
            actor_service=SimpleNamespace(),
            workspace_service=_WorkspaceService(),
            endpoint_service=_EndpointService(),
            endpoint_capability_service=_EndpointCapabilityService(),
            session_service=SimpleNamespace(get_by_session_id=lambda session_id: None),
            thread_service=SimpleNamespace(get_by_id=lambda row_id: None),
            operation_service=operation_service,
            operation_call_service=call_service,
        )
        frames: list[dict] = []

        async def endpoint_transport(*, endpoint_id: str, payload: dict) -> bool:
            frames.append({"endpoint_id": endpoint_id, "payload": payload})

            async def resolve_later() -> None:
                await asyncio.sleep(0)
                await router.notify_call_result("call_1", {"summary": "read ok"})

            asyncio.create_task(resolve_later())
            return True

        router.set_endpoint_transport(endpoint_transport)

        result = await router.route_tool_call(
            tool_key="file.read",
            arguments={"path": "demo.txt"},
            workspace_id="desktop-main",
            endpoint_id="desktop.main.executor",
            title="Read file",
        )

        self.assertEqual(result, {"summary": "read ok"})
        self.assertEqual(frames[0]["endpoint_id"], "desktop.main.executor")
        frame = frames[0]["payload"]
        self.assertEqual(frame["schema"], "meetyou.endpoint.ws.v4")
        self.assertEqual(frame["type"], "tool.call.request")
        self.assertEqual(frame["payload"]["tool_key"], "file.read")
        self.assertEqual(frame["payload"]["call_id"], "call_1")
        self.assertEqual(operation_service.operations[0]["execution_target_type"], "endpoint")
        self.assertEqual(operation_service.operations[0]["execution_target_id"], "desktop.main.executor")
        self.assertEqual(call_service.created[0]["execution_target_id"], "desktop.main.executor")


if __name__ == "__main__":
    unittest.main()
