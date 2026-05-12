from __future__ import annotations

import asyncio
import unittest

from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.capabilities.base import (
    CapabilityDefinition,
)
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.config import RpiEndpointConfig
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.registry import build_default_registry
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.runtime.operation_runner import OperationRunner
from endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.runtime.result_models import OperationRequest


class OperationRunnerTests(unittest.IsolatedAsyncioTestCase):
    def _runner(self):
        registry = build_default_registry(RpiEndpointConfig(), force_fake_gpio=True)
        return OperationRunner(registry, default_timeout_seconds=1, max_timeout_seconds=1), registry

    async def test_executes_echo_and_emits_progress_then_completed(self):
        runner, _ = self._runner()
        events = []

        async def emit(event):
            events.append(event)

        final = await runner.run(
            OperationRequest(
                operation_id="op-echo",
                call_id="call-echo",
                capability_name="rpi.echo",
                arguments={"text": "hello"},
            ),
            emit=emit,
        )

        self.assertTrue(final.succeeded)
        self.assertEqual(final.payload, {"text": "hello"})
        self.assertEqual([event.event_type for event in events], ["operation.progress", "operation.completed"])

    async def test_unknown_capability_fails(self):
        runner, _ = self._runner()

        final = await runner.run(
            OperationRequest(
                operation_id="op-missing",
                call_id="call-missing",
                capability_name="rpi.missing",
                arguments={},
            )
        )

        self.assertEqual(final.status, "failed")
        self.assertEqual(final.error["code"], "capability_not_found")

    async def test_timeout_fails(self):
        runner, registry = self._runner()

        async def slow_handler(arguments, context):
            del arguments, context
            await asyncio.sleep(0.05)
            return {"ok": True}

        registry.register(
            CapabilityDefinition(
                name="rpi.test.slow",
                description="Slow Test",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                output_schema={"type": "object"},
                risk_level="read",
                requires_confirmation=False,
                handler=slow_handler,
            )
        )

        final = await runner.run(
            OperationRequest(
                operation_id="op-slow",
                call_id="call-slow",
                capability_name="rpi.test.slow",
                arguments={},
                timeout_seconds=0.01,
            )
        )

        self.assertEqual(final.status, "failed")
        self.assertEqual(final.error["code"], "operation_timeout")

    async def test_repeated_operation_id_is_idempotent(self):
        runner, registry = self._runner()
        calls = {"count": 0}

        async def counter_handler(arguments, context):
            del context
            calls["count"] += 1
            return {"value": arguments["value"], "count": calls["count"]}

        registry.register(
            CapabilityDefinition(
                name="rpi.test.counter",
                description="Counter Test",
                input_schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                output_schema={"type": "object"},
                risk_level="read",
                requires_confirmation=False,
                handler=counter_handler,
            )
        )

        first = await runner.run(
            OperationRequest(
                operation_id="op-repeat",
                call_id="call-1",
                capability_name="rpi.test.counter",
                arguments={"value": "first"},
            )
        )
        second = await runner.run(
            OperationRequest(
                operation_id="op-repeat",
                call_id="call-2",
                capability_name="rpi.test.counter",
                arguments={"value": "second"},
            )
        )

        self.assertEqual(calls["count"], 1)
        self.assertEqual(second.payload, first.payload)
        self.assertEqual(second.call_id, "call-1")


if __name__ == "__main__":
    unittest.main()

