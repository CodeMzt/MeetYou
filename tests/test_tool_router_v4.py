from __future__ import annotations

import asyncio
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


class _WorkspaceService:
    def get_by_workspace_id(self, workspace_id):
        return SimpleNamespace(id="workspace-row", workspace_id=workspace_id)

    def get_by_id(self, row_id):
        return SimpleNamespace(id=row_id, workspace_id="personal") if row_id else None


class _EndpointService:
    def get_by_endpoint_id(self, endpoint_id):
        if endpoint_id == "desktop.local.executor":
            return SimpleNamespace(id="endpoint-row", endpoint_id=endpoint_id, provider_type="desktop", status="online")
        return None

    def get_by_id(self, row_id):
        if row_id == "endpoint-row":
            return SimpleNamespace(id="endpoint-row", endpoint_id="desktop.local.executor", provider_type="desktop", status="online")
        return None


class _EndpointCapabilityService:
    def list_for_endpoint(self, *, endpoint_row_id):
        if endpoint_row_id != "endpoint-row":
            return []
        return [
            SimpleNamespace(
                id="endpoint-capability-row",
                capability_id="endpoint.desktop.local.executor.utility.echo",
                tool_key="utility.echo",
                enabled=True,
                requires_confirmation=False,
                risk_level="read",
            )
        ]

    def list_enabled_for_tool(self, tool_key):
        if tool_key == "utility.echo":
            return [self.list_for_endpoint(endpoint_row_id="endpoint-row")[0]]
        return []


class _OperationService:
    def __init__(self):
        self.rows = []

    def create_operation(self, **kwargs):
        row = SimpleNamespace(id=f"operation-row-{len(self.rows) + 1}", operation_id=f"op_{len(self.rows) + 1}", **kwargs)
        self.rows.append(row)
        return row


class _OperationCallService:
    def __init__(self):
        self.rows = []

    def create_call(self, **kwargs):
        row = SimpleNamespace(id=f"call-row-{len(self.rows) + 1}", call_id=f"call_{len(self.rows) + 1}", **kwargs)
        self.rows.append(row)
        return row

    def mark_dispatched(self, *, call_id):
        return self._mark(call_id, "dispatched")

    def mark_succeeded(self, *, call_id, result=None):
        row = self._mark(call_id, "succeeded")
        row.result = dict(result or {})
        return row

    def mark_failed(self, *, call_id, error=None):
        row = self._mark(call_id, "failed")
        row.error = dict(error or {})
        return row

    def _mark(self, call_id, status):
        for row in self.rows:
            if row.call_id == call_id:
                row.status = status
                return row
        raise AssertionError(f"unknown call_id: {call_id}")


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

    async def test_endpoint_dispatch_can_return_operation_envelope_without_changing_default_tool_result(self):
        operation_service = _OperationService()
        operation_call_service = _OperationCallService()
        router = ToolRouterService(
            actor_service=_NoopService(),
            workspace_service=_WorkspaceService(),
            endpoint_service=_EndpointService(),
            endpoint_capability_service=_EndpointCapabilityService(),
            session_service=_NoopService(),
            thread_service=_NoopService(),
            operation_service=operation_service,
            operation_call_service=operation_call_service,
        )

        async def _transport(*, endpoint_id, payload):
            self.assertEqual(endpoint_id, "desktop.local.executor")

            async def _finish():
                await asyncio.sleep(0)
                await router.notify_call_result(payload["payload"]["call_id"], {"echo": payload["payload"]["arguments"]["text"]})

            asyncio.create_task(_finish())
            return True

        router.set_endpoint_transport(_transport)

        direct = await router.dispatch_tool_call(
            tool_key="utility.echo",
            arguments={"text": "direct"},
            workspace_id="personal",
            target_endpoint_id="desktop.local.executor",
            confirmed=True,
        )
        self.assertEqual(direct, {"echo": "direct"})

        envelope = await router.dispatch_tool_call(
            tool_key="utility.echo",
            arguments={"text": "envelope"},
            workspace_id="personal",
            target_endpoint_id="desktop.local.executor",
            confirmed=True,
            return_operation=True,
        )
        self.assertEqual(envelope["status"], "succeeded")
        self.assertEqual(envelope["operation_id"], "op_2")
        self.assertEqual(envelope["call_id"], "call_2")
        self.assertEqual(envelope["execution_target_id"], "desktop.local.executor")
        self.assertEqual(envelope["result"], {"echo": "envelope"})
        self.assertEqual(operation_service.rows[-1].thread_id, None)


if __name__ == "__main__":
    unittest.main()
