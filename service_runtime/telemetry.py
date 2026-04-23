from __future__ import annotations

from collections import deque
from copy import deepcopy
from typing import Any

from core.runtime_context import get_correlation_context
from service_runtime.models import RuntimeHealthStatus, RuntimeTelemetrySignal


class RuntimeTelemetryRecorder:
    def __init__(self):
        self._counters: dict[str, int] = {
            "tool_calls_total": 0,
            "tool_failures_total": 0,
            "gateway_delivery_attempts_total": 0,
            "gateway_delivery_success_total": 0,
            "gateway_delivery_failures_total": 0,
            "background_stall_events_total": 0,
            "background_failure_events_total": 0,
        }
        self._gauges: dict[str, Any] = {}
        self._signals: deque[RuntimeTelemetrySignal] = deque(maxlen=50)
        self._background_issues: set[str] = set()

    def increment(self, name: str, amount: int = 1) -> None:
        self._counters[name] = int(self._counters.get(name, 0) or 0) + max(int(amount or 0), 0)

    def set_gauge(self, name: str, value: Any) -> None:
        self._gauges[name] = value

    def capture(
        self,
        *,
        code: str,
        component: str,
        severity: str,
        message: str,
        details: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> RuntimeTelemetrySignal:
        signal = RuntimeTelemetrySignal(
            code=code,
            component=component,
            severity=severity,
            message=message,
            details=deepcopy(details or {}),
            context={
                key: str(value or "").strip()
                for key, value in {**get_correlation_context(), **dict(context or {})}.items()
                if key in {"trace_id", "session_id", "turn_id", "job_id", "tool_call_id"}
            },
        )
        self._signals.append(signal)
        return signal

    def observe_tool_result(self, tool_name: str, result, tool_args: dict[str, Any] | None = None) -> None:
        self.increment("tool_calls_total")
        if getattr(result, "ok", False):
            return
        self.increment("tool_failures_total")
        error = getattr(result, "error", None)
        metadata = getattr(result, "metadata", {}) if isinstance(getattr(result, "metadata", {}), dict) else {}
        details = {
            "tool_name": tool_name,
            "tool_args": deepcopy(tool_args or {}),
            "source": getattr(result, "source", ""),
            "action_risk": getattr(result, "action_risk", ""),
            "metadata": deepcopy(metadata),
        }
        if error is not None:
            details["error"] = error.model_dump(mode="json") if hasattr(error, "model_dump") else deepcopy(error)
        self.capture(
            code=getattr(error, "code", "tool_execution_failed"),
            component="tool_execution",
            severity="warning",
            message=getattr(error, "message", f"Tool {tool_name} failed"),
            details=details,
            context={"tool_call_id": get_correlation_context().get("tool_call_id", "")},
        )

    def observe_gateway_delivery(
        self,
        *,
        success: bool,
        session_id: str,
        delivery_mode: str,
        event_type: str = "",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.increment("gateway_delivery_attempts_total")
        if success:
            self.increment("gateway_delivery_success_total")
            return
        self.increment("gateway_delivery_failures_total")
        self.capture(
            code="gateway_delivery_failed",
            component="delivery",
            severity="warning",
            message=reason or "Gateway delivery failed.",
            details={
                "delivery_mode": delivery_mode,
                "event_type": event_type,
                "metadata": deepcopy(metadata or {}),
            },
            context={"session_id": session_id},
        )

    def observe_background_status(self, payload: dict[str, Any]) -> None:
        self.set_gauge("background_pending_delivery_count", int(payload.get("pending_delivery_count", 0) or 0))
        self.set_gauge("background_due_task_count", int(payload.get("due_task_count", 0) or 0))
        self.set_gauge("background_overdue_task_count", int(payload.get("overdue_task_count", 0) or 0))
        self.set_gauge("background_repeated_failure_task_count", len(payload.get("repeated_failure_tasks") or []))
        self.set_gauge("background_inbound_queue_size", int(payload.get("inbound_queue_size", 0) or 0))
        self.set_gauge("background_job_failure_count", len(payload.get("job_failures") or []))
        self.set_gauge("heartbeat_idle_poke_after_seconds", int(payload.get("heartbeat_idle_poke_after_seconds") or 0))
        self.set_gauge("heartbeat_idle_poke_cooldown_seconds", int(payload.get("heartbeat_idle_poke_cooldown_seconds") or 0))
        self.set_gauge("heartbeat_idle_poke_enabled", 1 if payload.get("heartbeat_idle_poke_enabled") else 0)
        self.set_gauge("heartbeat_idle_poke_eligible", 1 if payload.get("idle_poke_eligible") else 0)

        current_issues: set[str] = set()
        issue_specs = (
            ("scheduler_stalled", "background_jobs", "Scheduler loop stalled."),
            ("housekeeping_stalled", "background_jobs", "Housekeeping loop stalled."),
            ("pending_consolidation_stale", "background_jobs", "Pending consolidation is stale."),
        )
        for key, component, message in issue_specs:
            if payload.get(key):
                current_issues.add(key)
                if key not in self._background_issues:
                    self.increment("background_stall_events_total")
                    self.capture(
                        code=key,
                        component=component,
                        severity="error",
                        message=message,
                        details={"background_status": deepcopy(payload)},
                        context={"job_id": key.replace("_stalled", "")},
                    )

        for job_failure in payload.get("job_failures") or []:
            failure = job_failure.get("failure") if isinstance(job_failure, dict) else {}
            if not isinstance(failure, dict):
                continue
            issue_key = f"job_failure:{job_failure.get('job_name') or job_failure.get('job_kind')}"
            current_issues.add(issue_key)
            if issue_key in self._background_issues:
                continue
            self.increment("background_failure_events_total")
            self.capture(
                code=str(failure.get("code") or "background_job_failed"),
                component="background_jobs",
                severity="warning",
                message=str(failure.get("message") or "Background job failed."),
                details=deepcopy(job_failure),
                context={"job_id": str(job_failure.get("job_name") or "")},
            )

        self._background_issues = current_issues

    def metrics_snapshot(self) -> dict[str, Any]:
        return {**self._counters, **self._gauges}

    def recent_signals(self, limit: int = 10) -> list[RuntimeTelemetrySignal]:
        if limit <= 0:
            return []
        return list(self._signals)[-limit:]

    def delivery_check_status(self) -> str:
        pending_count = int(self._gauges.get("background_pending_delivery_count", 0) or 0)
        failure_count = int(self._counters.get("gateway_delivery_failures_total", 0) or 0)
        if pending_count > 0 or failure_count > 0:
            return RuntimeHealthStatus.DEGRADED.value
        return RuntimeHealthStatus.READY.value

    def tool_check_status(self) -> str:
        if int(self._counters.get("tool_failures_total", 0) or 0) > 0:
            return RuntimeHealthStatus.DEGRADED.value
        return RuntimeHealthStatus.READY.value
