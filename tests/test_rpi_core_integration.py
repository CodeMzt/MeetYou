from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.db.models import Endpoint  # noqa: F401 - imports model metadata for create_all
from core.services.endpoint_service import (
    EndpointCapabilityService,
    EndpointConnectionService,
    EndpointRegistryService,
)
from core.services.operation_call_service import OperationCallService
from core.services.operation_service import OperationService
from core.services.tool_router_service import ToolRouterError, ToolRouterService
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.config import RpiEndpointConfig, SecurityConfig
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.protocol import (
    build_call_accepted,
    build_call_error,
    build_call_progress,
    build_call_result,
    build_hello,
    build_tools_snapshot,
)
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.registry import build_default_registry
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.runtime.operation_runner import OperationRunner
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.runtime.result_models import OperationRequest
from gateway.endpoint_ws import ENDPOINT_WS_SCHEMA, EndpointWebSocketManager
from gateway.routes.endpoint import _handle_endpoint_frame


class _FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.client = SimpleNamespace(host="127.0.0.1")

    async def send_json(self, frame):
        self.sent.append(dict(frame))

    async def close(self, code=1000):
        self.close_code = code


class _WorkspaceService:
    def __init__(self):
        self.workspace = SimpleNamespace(
            id=uuid4(),
            workspace_id="personal",
            meta={"tool_policy": "allow_all"},
        )

    def get_by_workspace_id(self, workspace_id):
        return self.workspace if workspace_id == "personal" else None

    def get_by_id(self, row_id):
        return self.workspace if row_id == self.workspace.id else None

    def tool_allowed(self, workspace, tool_key):
        del workspace, tool_key
        return True

    def get_effective_tool_target_preferences(self, workspace, **kwargs):
        del workspace, kwargs
        return {
            "preferred_target_endpoint_ids": [],
            "preferred_endpoint_provider_types": ["rpi"],
            "tool_target_routing_policy": "balanced",
            "source": "test",
        }


class _NoopService:
    def get_by_session_id(self, session_id):
        del session_id
        return None

    def get_by_id(self, row_id):
        del row_id
        return None


class _CoreHarness:
    def __init__(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self.endpoint_ws_manager = EndpointWebSocketManager()
        self.endpoint = EndpointRegistryService(self.Session)
        self.endpoint_connection = EndpointConnectionService(self.Session)
        self.endpoint_capability = EndpointCapabilityService(self.Session)
        self.operation = OperationService(self.Session)
        self.operation_call = OperationCallService(self.Session)
        self.workspace = _WorkspaceService()
        self.thread = _NoopService()
        self.tool_router = ToolRouterService(
            actor_service=_NoopService(),
            workspace_service=self.workspace,
            endpoint_service=self.endpoint,
            endpoint_capability_service=self.endpoint_capability,
            session_service=_NoopService(),
            thread_service=self.thread,
            operation_service=self.operation,
            operation_call_service=self.operation_call,
        )
        self.tool_router.set_connected_endpoint_ids_getter(
            self.endpoint_ws_manager.connected_endpoint_ids_now
        )
        self.services = SimpleNamespace(
            endpoint=self.endpoint,
            endpoint_connection=self.endpoint_connection,
            endpoint_capability=self.endpoint_capability,
            operation=self.operation,
            operation_call=self.operation_call,
            tool_router=self.tool_router,
            thread=self.thread,
        )
        self.domain = SimpleNamespace(services=self.services)
        self.published_updates: list[dict] = []

    def close(self):
        self.engine.dispose()

    def _require_core_domain(self):
        return self.domain

    async def _safe_send_json(self, websocket, frame):
        await websocket.send_json(frame)

    async def publish_endpoint_operation_update(self, **kwargs):
        self.published_updates.append(dict(kwargs))
        return await self.endpoint_ws_manager.publish_operation_update(**kwargs)

    async def handle(self, websocket, frame, state):
        await _handle_endpoint_frame(self, websocket, frame, state)


class RpiCoreIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.harness = _CoreHarness()
        self.config = RpiEndpointConfig(
            endpoint_id="pi-test",
            workspace_ids=["personal"],
            security=SecurityConfig(
                safe_shell_enabled=False,
                gpio_allowed_pins=[17],
                gpio_write_default_duration_ms=0,
            ),
        )
        self.rpi_registry = build_default_registry(self.config, force_fake_gpio=True)
        self.rpi_runner = OperationRunner(self.rpi_registry, default_timeout_seconds=1, max_timeout_seconds=1)
        self.rpi_socket = _FakeWebSocket()
        await self.harness.endpoint_ws_manager.connect(self.rpi_socket)
        self.state: dict = {}
        await self.harness.handle(self.rpi_socket, build_hello(self.config), self.state)
        await self.harness.handle(
            self.rpi_socket,
            build_tools_snapshot(
                self.config,
                revision=1,
                capabilities=self.rpi_registry.tool_definitions(),
            ),
            self.state,
        )

    async def asyncTearDown(self):
        self.harness.close()

    async def _dispatch_with_fake_pi(self, *, tool_key: str, arguments: dict, return_operation: bool = False):
        monitor = _FakeWebSocket()
        await self.harness.endpoint_ws_manager.connect(monitor)

        async def _transport(*, endpoint_id, payload):
            delivered = await self.harness.endpoint_ws_manager.send_to_endpoint(endpoint_id, payload)
            self.assertEqual(delivered, 1)

            async def _reply_from_fake_pi():
                operation_id = payload["payload"]["operation_id"]
                call_id = payload["payload"]["call_id"]
                await self.harness.endpoint_ws_manager.subscribe(
                    monitor,
                    target_type="operation",
                    target_id=operation_id,
                    subscription_id=f"sub-{operation_id}",
                )
                await self.harness.handle(
                    self.rpi_socket,
                    build_call_accepted(self.config, call_id=call_id, correlation_id=payload["message_id"]),
                    self.state,
                )
                await self.harness.handle(
                    self.rpi_socket,
                    build_call_progress(
                        self.config,
                        call_id=call_id,
                        correlation_id=payload["message_id"],
                        phase="running",
                        detail=f"Executing {tool_key}",
                    ),
                    self.state,
                )
                final = await self.rpi_runner.run(
                    OperationRequest(
                        operation_id=operation_id,
                        call_id=call_id,
                        capability_name=tool_key,
                        arguments=arguments,
                        timeout_seconds=1,
                    )
                )
                if final.succeeded:
                    await self.harness.handle(
                        self.rpi_socket,
                        build_call_result(
                            self.config,
                            call_id=call_id,
                            correlation_id=payload["message_id"],
                            result=final.payload,
                        ),
                        self.state,
                    )
                    return
                await self.harness.handle(
                    self.rpi_socket,
                    build_call_error(
                        self.config,
                        call_id=call_id,
                        correlation_id=payload["message_id"],
                        code=final.error["code"],
                        message=final.error["message"],
                        retryable=bool(final.error.get("retryable", False)),
                    ),
                    self.state,
                )

            asyncio.create_task(_reply_from_fake_pi())
            return True

        self.harness.tool_router.set_endpoint_transport(_transport)
        try:
            result = await self.harness.tool_router.dispatch_tool_call(
                tool_key=tool_key,
                arguments=arguments,
                workspace_id="personal",
                target_endpoint_id=self.config.executor_endpoint_id,
                confirmed=True,
                timeout_seconds=1,
                return_operation=return_operation,
            )
            return result, monitor
        except Exception as exc:
            return exc, monitor

    async def _wait_for_operation_update_phase(self, monitor: _FakeWebSocket, phase: str) -> list[str]:
        for _ in range(20):
            phases = [
                frame["payload"]["phase"]
                for frame in monitor.sent
                if frame.get("type") == "delivery.operation_update"
            ]
            if phase in phases:
                return phases
            await asyncio.sleep(0.01)
        return [
            frame["payload"]["phase"]
            for frame in monitor.sent
            if frame.get("type") == "delivery.operation_update"
        ]

    async def test_pi_capability_registration_is_received_by_core(self):
        endpoint = self.harness.endpoint.get_by_endpoint_id(self.config.executor_endpoint_id)
        capabilities = self.harness.endpoint_capability.list_for_endpoint(endpoint_row_id=endpoint.id)
        capability_keys = {capability.tool_key for capability in capabilities if capability.enabled}

        self.assertEqual(endpoint.provider_type, "rpi")
        self.assertEqual(endpoint.endpoint_type, "rpi_executor")
        self.assertIn("rpi.echo", capability_keys)
        self.assertIn("rpi.system.info", capability_keys)
        self.assertIn("rpi.gpio.read", capability_keys)
        self.assertNotIn("rpi.shell.safe_exec", capability_keys)

    async def test_tool_router_resolves_rpi_capability_to_endpoint_target(self):
        target = self.harness.tool_router.resolve_execution_target(
            tool_key="rpi.echo",
            workspace_id="personal",
            confirmed=True,
        )

        self.assertEqual(target.target_type, "endpoint")
        self.assertEqual(target.target_id, self.config.executor_endpoint_id)
        self.assertEqual(target.endpoint_capability.tool_key, "rpi.echo")
        self.assertEqual((target.routing_decision or {})["selected_endpoint_id"], self.config.executor_endpoint_id)

    async def test_rpi_echo_operation_reaches_endpoint_and_records_completed_result(self):
        result, monitor = await self._dispatch_with_fake_pi(
            tool_key="rpi.echo",
            arguments={"text": "hello pi"},
            return_operation=True,
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["result"], {"text": "hello pi"})
        operation = self.harness.operation.get_by_operation_id(result["operation_id"])
        call = self.harness.operation_call.get_by_call_id(result["call_id"])
        self.assertEqual(operation.status, "succeeded")
        self.assertEqual(operation.meta["result"], {"text": "hello pi"})
        self.assertEqual(call.status, "succeeded")
        self.assertEqual(call.result, {"text": "hello pi"})
        self.assertTrue(any(frame["type"] == "tool.call.request" for frame in self.rpi_socket.sent))
        update_phases = await self._wait_for_operation_update_phase(monitor, "completed")
        self.assertIn("accepted", update_phases)
        self.assertIn("running", update_phases)
        self.assertIn("completed", update_phases)

    async def test_rpi_gpio_failure_records_failed_operation(self):
        result, monitor = await self._dispatch_with_fake_pi(
            tool_key="rpi.gpio.read",
            arguments={"pin": 22},
            return_operation=True,
        )

        self.assertIsInstance(result, ToolRouterError)
        self.assertEqual(result.code, "gpio_pin_not_allowed")
        failed = self.harness.published_updates[-1]
        operation = self.harness.operation.get_by_operation_id(failed["operation_id"])
        call_id = failed["payload"]["call_id"]
        call = self.harness.operation_call.get_by_call_id(call_id)
        self.assertEqual(operation.status, "failed")
        self.assertEqual(operation.meta["error"]["code"], "gpio_pin_not_allowed")
        self.assertEqual(call.status, "failed")
        self.assertEqual(call.error["code"], "gpio_pin_not_allowed")
        await self._wait_for_operation_update_phase(monitor, "failed")
        failed_updates = [
            frame
            for frame in monitor.sent
            if frame.get("type") == "delivery.operation_update"
            and frame["payload"].get("phase") == "failed"
        ]
        self.assertEqual(len(failed_updates), 1)

    async def test_disconnected_rpi_endpoint_returns_clear_toolrouter_error(self):
        await self.harness.endpoint_ws_manager.disconnect(self.rpi_socket)

        with self.assertRaises(ToolRouterError) as raised:
            self.harness.tool_router.resolve_execution_target(
                tool_key="rpi.echo",
                workspace_id="personal",
                endpoint_id=self.config.executor_endpoint_id,
                confirmed=True,
            )

        self.assertEqual(raised.exception.code, "target_endpoint_unavailable")
        self.assertTrue(raised.exception.retryable)

    async def test_gpio_pin_allowlist_still_enforced_in_pi_runner(self):
        final = await self.rpi_runner.run(
            OperationRequest(
                operation_id="op-gpio-denied",
                call_id="call-gpio-denied",
                capability_name="rpi.gpio.read",
                arguments={"pin": 22},
            )
        )

        self.assertEqual(final.status, "failed")
        self.assertEqual(final.error["code"], "gpio_pin_not_allowed")


if __name__ == "__main__":
    unittest.main()
