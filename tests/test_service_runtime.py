import asyncio
import json
import logging
import unittest
from types import SimpleNamespace

from core.logger import StructuredFormatter
from core.runtime_context import bind_event_context, reset_event_context
from core.tool_runtime.models import ToolCallResult, ToolErrorCategory, ToolSourceType
from service_runtime.boundaries import build_default_runtime_boundaries, build_runtime_platform_boundaries
from service_runtime.models import RuntimeCommand, RuntimeEventKind, RuntimeHealthStatus
from service_runtime.service import ServiceRuntime


class _FakeApp:
    background_status = {
        "pending_delivery_count": 0,
        "scheduler_stalled": False,
        "housekeeping_stalled": False,
        "pending_consolidation_stale": False,
        "last_housekeeping_error": "",
        "job_failures": [],
        "inbound_queue_size": 0,
        "due_task_count": 0,
        "overdue_task_count": 0,
        "repeated_failure_tasks": [],
    }

    def __init__(self, health_getter=None, telemetry_recorder=None):
        self.health_getter = health_getter
        self.telemetry_recorder = telemetry_recorder
        self.setup_called = False
        self.shutdown_called = False
        self.heart = SimpleNamespace(
            scheduler_processor=self._noop,
            housekeeping_processor=self._noop,
            heartbeat_processor=self._noop,
        )
        self.proprioceptor = SimpleNamespace(run=self._noop)

    async def setup(self):
        self.setup_called = True

    async def shutdown(self):
        self.shutdown_called = True

    async def brain_processor(self):
        return None

    async def get_background_status(self):
        return dict(self.background_status)

    async def _noop(self):
        return None


class ServiceRuntimeTests(unittest.TestCase):
    def test_default_runtime_boundaries_cover_service_layers(self):
        boundaries = build_default_runtime_boundaries()

        self.assertEqual(
            boundaries.names(),
            [
                "session_execution",
                "background_jobs",
                "tool_execution",
                "delivery",
                "telemetry",
            ],
        )
        self.assertEqual(
            boundaries.delivery.dependencies,
            ("telemetry",),
        )

    def test_runtime_platform_boundaries_separate_core_sensing_and_terminal_capabilities(self):
        boundaries = build_runtime_platform_boundaries().to_dict()

        retained = {item["name"]: item for item in boundaries["retained_in_core"]}
        delegated = {item["name"]: item for item in boundaries["delegated_to_local_agents"]}

        self.assertIn("runtime_host_detection", retained)
        self.assertIn("runtime_host_observability", retained)
        self.assertIn("runtime_host_proprioception", retained)
        self.assertIn("terminal_shell_execution", delegated)
        self.assertIn("terminal_file_and_workspace_io", delegated)
        self.assertIn("terminal_local_mcp_runtime", delegated)
        self.assertIn(
            "tools/system_tools.py::exec_sys_cmd",
            delegated["terminal_shell_execution"]["surfaces"],
        )
        self.assertIn(
            "sensors/proprioceptor.py::Proprioceptor.run",
            retained["runtime_host_proprioception"]["surfaces"],
        )

    def test_service_runtime_exposes_ready_health_after_setup(self):
        runtime = ServiceRuntime(RuntimeCommand.service(), app_factory=_FakeApp)

        asyncio.run(runtime.run())

        health_events = [event for event in runtime.events if event.kind == RuntimeEventKind.HEALTH.value]
        self.assertEqual(len(health_events), 1)
        self.assertTrue(health_events[0].payload["ready"])
        self.assertEqual(health_events[0].payload["status"], RuntimeHealthStatus.READY.value)
        self.assertIn("platform_boundary", health_events[0].payload)
        delegated_names = {
            item["name"] for item in health_events[0].payload["platform_boundary"]["delegated_to_local_agents"]
        }
        self.assertIn("terminal_shell_execution", delegated_names)
        self.assertTrue(runtime._app.setup_called)
        self.assertTrue(runtime._app.shutdown_called)

    def test_health_snapshot_reports_degraded_background_and_telemetry_metrics(self):
        class _DegradedApp(_FakeApp):
            background_status = {
                "pending_delivery_count": 1,
                "scheduler_stalled": False,
                "housekeeping_stalled": False,
                "pending_consolidation_stale": True,
                "last_housekeeping_error": "",
                "job_failures": [],
                "inbound_queue_size": 3,
                "due_task_count": 2,
                "overdue_task_count": 1,
                "repeated_failure_tasks": [{"task_key": "task-1", "summary": "daily digest sync"}],
            }

        runtime = ServiceRuntime(RuntimeCommand.service(), app_factory=_DegradedApp)
        asyncio.run(runtime.run())

        token = bind_event_context(
            trace_id="trace-1",
            session_id="session-1",
            turn_id="turn-1",
            tool_call_id="tool-1",
        )
        try:
            runtime.telemetry.observe_tool_result(
                "search_memory",
                ToolCallResult.failure(
                    tool_name="search_memory",
                    source=ToolSourceType.BUILTIN,
                    action_risk="read",
                    code="tool_builtin_failed",
                    category=ToolErrorCategory.EXECUTION,
                    message="tool failed",
                ),
                tool_args={"query": "hello"},
            )
        finally:
            reset_event_context(token)

        runtime.telemetry.observe_gateway_delivery(
            success=False,
            session_id="session-1",
            delivery_mode="session",
            event_type="message",
            reason="websocket_send_failed",
            metadata={"turn_id": "turn-1"},
        )
        snapshot = asyncio.run(runtime.build_health_snapshot())

        self.assertEqual(snapshot["status"], RuntimeHealthStatus.DEGRADED.value)
        self.assertTrue(snapshot["degraded"])
        self.assertFalse(snapshot["ready"])
        self.assertEqual(snapshot["metrics"]["tool_failures_total"], 1)
        self.assertEqual(snapshot["metrics"]["gateway_delivery_failures_total"], 1)
        self.assertEqual(snapshot["metrics"]["background_pending_delivery_count"], 1)
        self.assertEqual(snapshot["components"][1]["status"], RuntimeHealthStatus.DEGRADED.value)
        checks = {item["name"]: item for item in snapshot["checks"]}
        self.assertEqual(checks["background_loops"]["status"], RuntimeHealthStatus.DEGRADED.value)
        self.assertEqual(checks["background_loops"]["metadata"]["pending_consolidation_stale"], True)
        self.assertIn("repeated_task_failures", checks["background_loops"]["metadata"]["system_issue_candidates"])
        self.assertEqual(checks["heartbeat_alignment"]["status"], RuntimeHealthStatus.DEGRADED.value)
        self.assertEqual(checks["tool_execution"]["status"], RuntimeHealthStatus.DEGRADED.value)
        self.assertEqual(checks["gateway_delivery"]["status"], RuntimeHealthStatus.DEGRADED.value)
        tool_signal = next(item for item in snapshot["telemetry"] if item["code"] == "tool_builtin_failed")
        self.assertEqual(tool_signal["context"]["trace_id"], "trace-1")
        self.assertEqual(tool_signal["context"]["session_id"], "session-1")
        self.assertEqual(tool_signal["context"]["turn_id"], "turn-1")
        self.assertEqual(tool_signal["context"]["tool_call_id"], "tool-1")

    def test_structured_formatter_emits_correlation_context(self):
        formatter = StructuredFormatter(datefmt="%Y-%m-%d %H:%M:%S")
        token = bind_event_context(
            trace_id="trace-ctx",
            session_id="session-ctx",
            turn_id="turn-ctx",
            job_id="job-ctx",
            tool_call_id="tool-ctx",
        )
        try:
            record = logging.LogRecord(
                name="meetyou.test",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="structured log",
                args=(),
                exc_info=None,
            )
            payload = json.loads(formatter.format(record))
        finally:
            reset_event_context(token)

        self.assertEqual(payload["message"], "structured log")
        self.assertEqual(payload["context"]["trace_id"], "trace-ctx")
        self.assertEqual(payload["context"]["session_id"], "session-ctx")
        self.assertEqual(payload["context"]["turn_id"], "turn-ctx")
        self.assertEqual(payload["context"]["job_id"], "job-ctx")
        self.assertEqual(payload["context"]["tool_call_id"], "tool-ctx")
