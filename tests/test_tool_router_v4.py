from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from core.services.tool_router_service import ToolRouterError, ToolRouterService


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
    def __init__(self):
        self.get_by_endpoint_id_calls = 0
        self.get_by_id_calls = 0

    def get_by_endpoint_id(self, endpoint_id):
        self.get_by_endpoint_id_calls += 1
        if endpoint_id == "desktop.local.executor":
            return SimpleNamespace(id="endpoint-row", endpoint_id=endpoint_id, provider_type="desktop", status="online")
        return None

    def get_by_id(self, row_id):
        self.get_by_id_calls += 1
        if row_id == "endpoint-row":
            return SimpleNamespace(id="endpoint-row", endpoint_id="desktop.local.executor", provider_type="desktop", status="online")
        return None


class _EndpointCapabilityService:
    def __init__(self):
        self.list_for_endpoint_calls = 0
        self.list_enabled_for_tool_calls = 0

    def list_for_endpoint(self, *, endpoint_row_id):
        self.list_for_endpoint_calls += 1
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
        self.list_enabled_for_tool_calls += 1
        if tool_key == "utility.echo":
            return [self.list_for_endpoint(endpoint_row_id="endpoint-row")[0]]
        return []


class _ScoringWorkspaceService(_WorkspaceService):
    def __init__(self, *, preferred_endpoint_ids=None, preferred_provider_types=None, routing_policy="balanced"):
        self.workspace = SimpleNamespace(
            id="workspace-row",
            workspace_id="personal",
            meta={
                "preferred_target_endpoint_ids": list(preferred_endpoint_ids or []),
                "preferred_endpoint_provider_types": list(preferred_provider_types or []),
                "tool_target_routing_policy": routing_policy,
            },
        )

    def get_by_workspace_id(self, workspace_id):
        return self.workspace if workspace_id == "personal" else None

    def get_by_id(self, row_id):
        return self.workspace if row_id else None

    def get_effective_tool_target_preferences(self, workspace, **kwargs):
        del kwargs
        meta = dict(getattr(workspace, "meta", {}) or {})
        return {
            "preferred_target_endpoint_ids": list(meta.get("preferred_target_endpoint_ids") or []),
            "preferred_endpoint_provider_types": list(meta.get("preferred_endpoint_provider_types") or []),
            "tool_target_routing_policy": str(meta.get("tool_target_routing_policy") or "balanced"),
            "source": "test",
        }


class _AllowlistWorkspaceService(_WorkspaceService):
    def get_by_workspace_id(self, workspace_id):
        return SimpleNamespace(
            id="workspace-row",
            workspace_id=workspace_id,
            meta={"tool_policy": "allowlist", "allowed_tool_ids": ["delivery.message"]},
        )

    def tool_allowed(self, workspace, tool_id):
        meta = dict(getattr(workspace, "meta", {}) or {})
        if meta.get("tool_policy") != "allowlist":
            return True
        return tool_id in set(meta.get("allowed_tool_ids") or [])


class _ScoringEndpointService:
    def __init__(self):
        self.rows = {
            "endpoint-a": SimpleNamespace(
                id="endpoint-a",
                endpoint_id="desktop.a.executor",
                provider_type="desktop",
                status="online",
                priority=100,
                workspace_scope=["other"],
                meta={"heartbeat_metrics": {"active_calls": 0}, "routing_stats": {"success_count": 10, "failure_count": 0, "average_latency_ms": 200}},
            ),
            "endpoint-b": SimpleNamespace(
                id="endpoint-b",
                endpoint_id="desktop.b.executor",
                provider_type="desktop",
                status="online",
                priority=100,
                workspace_scope=["personal"],
                meta={"heartbeat_metrics": {"active_calls": 4, "cpu_percent": 80}, "routing_stats": {"success_count": 4, "failure_count": 4, "average_latency_ms": 5000}},
            ),
            "endpoint-c": SimpleNamespace(
                id="endpoint-c",
                endpoint_id="desktop.c.executor",
                provider_type="desktop",
                status="online",
                priority=50,
                workspace_scope=["personal"],
                meta={"heartbeat_metrics": {"active_calls": 0, "cpu_percent": 10}, "routing_stats": {"success_count": 9, "failure_count": 1, "average_latency_ms": 500}},
            ),
        }
        self.routing_results = []

    def get_by_endpoint_id(self, endpoint_id):
        return next((row for row in self.rows.values() if row.endpoint_id == endpoint_id), None)

    def get_by_id(self, row_id):
        return self.rows.get(row_id)

    def record_routing_result(self, **kwargs):
        self.routing_results.append(dict(kwargs))


class _ScoringCapabilityService:
    def __init__(self):
        self.rows = [
            SimpleNamespace(
                id=f"capability-{endpoint_id}",
                capability_id=f"endpoint.{endpoint_id}.utility.echo",
                endpoint_id=endpoint_id,
                tool_key="utility.echo",
                enabled=True,
                requires_confirmation=False,
                risk_level="read",
                meta={},
            )
            for endpoint_id in ("endpoint-a", "endpoint-b", "endpoint-c")
        ]

    def list_for_endpoint(self, *, endpoint_row_id):
        return [row for row in self.rows if row.endpoint_id == endpoint_row_id]

    def list_enabled_for_tool(self, tool_key):
        if tool_key == "utility.echo":
            return list(self.rows)
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

    async def test_registered_core_tool_name_routes_to_core_local(self):
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
        router.register_core_tool("send_delivery_message", lambda args: {"delivered": True, "content": args["content"]})

        result = await router.route_tool_call(
            tool_key="send_delivery_message",
            arguments={"content": "ok"},
            workspace_id="personal",
        )

        self.assertEqual(result, {"delivered": True, "content": "ok"})

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

    async def test_execution_target_resolution_uses_cache_and_invalidation(self):
        endpoint_service = _EndpointService()
        capability_service = _EndpointCapabilityService()
        router = ToolRouterService(
            actor_service=_NoopService(),
            workspace_service=_WorkspaceService(),
            endpoint_service=endpoint_service,
            endpoint_capability_service=capability_service,
            session_service=_NoopService(),
            thread_service=_NoopService(),
            operation_service=_OperationService(),
            operation_call_service=_OperationCallService(),
        )

        first = router.resolve_execution_target(
            tool_key="utility.echo",
            workspace_id="personal",
            endpoint_id="desktop.local.executor",
        )
        second = router.resolve_execution_target(
            tool_key="utility.echo",
            workspace_id="personal",
            endpoint_id="desktop.local.executor",
        )
        router.invalidate_cache(endpoint_id="desktop.local.executor")
        third = router.resolve_execution_target(
            tool_key="utility.echo",
            workspace_id="personal",
            endpoint_id="desktop.local.executor",
        )

        self.assertEqual(first.target_id, "desktop.local.executor")
        self.assertIs(first, second)
        self.assertEqual(third.target_id, "desktop.local.executor")
        self.assertEqual(capability_service.list_for_endpoint_calls, 2)
        self.assertEqual(endpoint_service.get_by_endpoint_id_calls, 2)

    async def test_batch_execution_target_resolution_matches_single_resolution(self):
        router = ToolRouterService(
            actor_service=_NoopService(),
            workspace_service=_WorkspaceService(),
            endpoint_service=_EndpointService(),
            endpoint_capability_service=_EndpointCapabilityService(),
            session_service=_NoopService(),
            thread_service=_NoopService(),
            operation_service=_OperationService(),
            operation_call_service=_OperationCallService(),
        )

        batch = router.resolve_execution_targets(
            [
                {
                    "tool_key": "utility.echo",
                    "workspace_id": "personal",
                    "endpoint_id": "desktop.local.executor",
                },
                {
                    "tool_key": "missing.tool",
                    "workspace_id": "personal",
                    "endpoint_id": "desktop.local.executor",
                },
            ]
        )

        self.assertTrue(batch[0]["ok"])
        self.assertEqual(batch[0]["target"].target_id, "desktop.local.executor")
        self.assertFalse(batch[1]["ok"])
        self.assertEqual(batch[1]["error"]["code"], "endpoint_capability_not_found")

    async def test_workspace_allowlist_blocks_unlisted_tool(self):
        router = ToolRouterService(
            actor_service=_NoopService(),
            workspace_service=_AllowlistWorkspaceService(),
            endpoint_service=_EndpointService(),
            endpoint_capability_service=_EndpointCapabilityService(),
            session_service=_NoopService(),
            thread_service=_NoopService(),
            operation_service=_OperationService(),
            operation_call_service=_OperationCallService(),
        )

        with self.assertRaises(ToolRouterError) as raised:
            router.resolve_execution_target(
                tool_key="utility.echo",
                workspace_id="personal",
                confirmed=True,
            )

        self.assertEqual(raised.exception.code, "workspace_tool_not_allowed")
        self.assertFalse(raised.exception.retryable)

    async def test_scored_resolution_prefers_workspace_preference_load_success_and_latency(self):
        router = ToolRouterService(
            actor_service=_NoopService(),
            workspace_service=_ScoringWorkspaceService(preferred_endpoint_ids=["desktop.c.executor"]),
            endpoint_service=_ScoringEndpointService(),
            endpoint_capability_service=_ScoringCapabilityService(),
            session_service=_NoopService(),
            thread_service=_NoopService(),
            operation_service=_OperationService(),
            operation_call_service=_OperationCallService(),
        )
        router.set_connected_endpoint_ids_getter(lambda: {"desktop.b.executor", "desktop.c.executor"})

        target = router.resolve_execution_target(
            tool_key="utility.echo",
            workspace_id="personal",
            confirmed=True,
        )

        self.assertEqual(target.target_id, "desktop.c.executor")
        decision = target.routing_decision or {}
        self.assertEqual(decision["selected_endpoint_id"], "desktop.c.executor")
        self.assertGreater(decision["score"], 0)
        self.assertEqual(decision["candidate_count"], 3)
        rejected_reasons = {
            reason
            for item in decision["rejected_candidates"]
            for reason in item.get("rejected_reasons", [])
        }
        self.assertIn("endpoint_disconnected", rejected_reasons)
        self.assertIn("workspace_mismatch", rejected_reasons)
        self.assertGreater(decision["breakdown"]["preference"], 0)
        self.assertGreater(decision["breakdown"]["load"], 0)
        self.assertGreater(decision["breakdown"]["success_rate"], 0)
        self.assertGreater(decision["breakdown"]["latency"], 0)

    async def test_disconnected_endpoint_is_not_auto_selected_when_connected_candidate_exists(self):
        router = ToolRouterService(
            actor_service=_NoopService(),
            workspace_service=_ScoringWorkspaceService(preferred_endpoint_ids=["desktop.b.executor"]),
            endpoint_service=_ScoringEndpointService(),
            endpoint_capability_service=_ScoringCapabilityService(),
            session_service=_NoopService(),
            thread_service=_NoopService(),
            operation_service=_OperationService(),
            operation_call_service=_OperationCallService(),
        )
        router.set_connected_endpoint_ids_getter(lambda: {"desktop.c.executor"})

        target = router.resolve_execution_target(
            tool_key="utility.echo",
            workspace_id="personal",
            confirmed=True,
        )

        self.assertEqual(target.target_id, "desktop.c.executor")
        rejected = {
            item["endpoint_id"]: item["rejected_reasons"]
            for item in (target.routing_decision or {}).get("rejected_candidates", [])
        }
        self.assertIn("endpoint_disconnected", rejected["desktop.b.executor"])

    async def test_dispatch_persists_routing_decision_metadata_and_records_stats(self):
        endpoint_service = _ScoringEndpointService()
        operation_service = _OperationService()
        operation_call_service = _OperationCallService()
        router = ToolRouterService(
            actor_service=_NoopService(),
            workspace_service=_ScoringWorkspaceService(preferred_endpoint_ids=["desktop.c.executor"]),
            endpoint_service=endpoint_service,
            endpoint_capability_service=_ScoringCapabilityService(),
            session_service=_NoopService(),
            thread_service=_NoopService(),
            operation_service=operation_service,
            operation_call_service=operation_call_service,
        )
        router.set_connected_endpoint_ids_getter(lambda: {"desktop.c.executor"})

        async def _transport(*, endpoint_id, payload):
            self.assertEqual(endpoint_id, "desktop.c.executor")

            async def _finish():
                await asyncio.sleep(0)
                await router.notify_call_result(payload["payload"]["call_id"], {"echo": "ok"})

            asyncio.create_task(_finish())
            return True

        router.set_endpoint_transport(_transport)

        result = await router.dispatch_tool_call(
            tool_key="utility.echo",
            arguments={"text": "ok"},
            workspace_id="personal",
            confirmed=True,
            return_operation=True,
        )

        self.assertEqual(result["execution_target_id"], "desktop.c.executor")
        decision = operation_service.rows[0].metadata["routing_decision"]
        self.assertEqual(decision["selected_endpoint_id"], "desktop.c.executor")
        self.assertEqual(endpoint_service.routing_results[0]["endpoint_row_id"], "endpoint-c")
        self.assertTrue(endpoint_service.routing_results[0]["success"])


if __name__ == "__main__":
    unittest.main()
