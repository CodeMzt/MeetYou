from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.services.tool_router_service import ToolRouterService


class _NoopService:
    def get_by_workspace_id(self, workspace_id):
        return SimpleNamespace(id="workspace-row", workspace_id=workspace_id)

    def get_by_endpoint_id(self, endpoint_id):
        if endpoint_id == "core.local":
            return SimpleNamespace(id="endpoint-core", endpoint_id="core.local", provider_type="core", status="active")
        return None

    def list_for_endpoint(self, endpoint_row_id):
        return []

    def list_enabled_for_tool(self, tool_key):
        return []


class ToolRouterV4Tests(unittest.IsolatedAsyncioTestCase):
    async def test_core_local_executes_in_process_without_operation(self):
        noop = _NoopService()
        router = ToolRouterService(
            actor_service=noop,
            workspace_service=noop,
            endpoint_service=noop,
            endpoint_capability_service=noop,
            session_service=noop,
            thread_service=noop,
            operation_service=noop,
            operation_call_service=noop,
        )
        router.register_core_tool("core.echo", lambda args: {"echo": args["text"]})

        result = await router.route_tool_call(
            tool_key="core.echo",
            arguments={"text": "ok"},
            workspace_id="personal",
        )

        self.assertEqual(result, {"echo": "ok"})


if __name__ == "__main__":
    unittest.main()
