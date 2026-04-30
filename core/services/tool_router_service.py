from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable
from uuid import uuid4

from endpoint_tool_sdk.protocol import ENDPOINT_TOOL_ARGUMENTS_PURPOSE
from core.credential_transport import CredentialTransportError, protect_sensitive_arguments


class ToolRouterError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.retryable = retryable


@dataclass(slots=True)
class ExecutionTarget:
    target_id: str
    target_type: str
    endpoint: Any | None = None
    endpoint_capability: Any | None = None
    offline_policy: str = "fail_fast"
    routing_decision: dict[str, Any] | None = None


@dataclass(slots=True)
class EndpointScoreBreakdown:
    online_status: float = 0.0
    workspace_match: float = 0.0
    preference: float = 0.0
    risk: float = 0.0
    priority: float = 0.0
    load: float = 0.0
    success_rate: float = 0.0
    latency: float = 0.0
    trust: float = 0.0
    cost: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.online_status
            + self.workspace_match
            + self.preference
            + self.risk
            + self.priority
            + self.load
            + self.success_rate
            + self.latency
            + self.trust
            + self.cost
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "online_status": round(self.online_status, 3),
            "workspace_match": round(self.workspace_match, 3),
            "preference": round(self.preference, 3),
            "risk": round(self.risk, 3),
            "priority": round(self.priority, 3),
            "load": round(self.load, 3),
            "success_rate": round(self.success_rate, 3),
            "latency": round(self.latency, 3),
            "trust": round(self.trust, 3),
            "cost": round(self.cost, 3),
            "total": round(self.total, 3),
        }


@dataclass(slots=True)
class EndpointRoutingPolicy:
    online_weight: float = 100.0
    db_online_weight: float = 35.0
    workspace_exact_weight: float = 28.0
    workspace_wildcard_weight: float = 14.0
    workspace_open_weight: float = 8.0
    preferred_endpoint_weight: float = 45.0
    preferred_provider_weight: float = 24.0
    low_risk_weight: float = 14.0
    priority_weight: float = 16.0
    load_weight: float = 20.0
    success_weight: float = 18.0
    latency_weight: float = 12.0
    trust_weight: float = 12.0
    cost_weight: float = 8.0


@dataclass(slots=True)
class EndpointCandidate:
    endpoint: Any
    capability: Any
    target_type: str
    breakdown: EndpointScoreBreakdown
    rejected_reasons: list[str]

    @property
    def score(self) -> float:
        return self.breakdown.total

    def to_decision_item(self) -> dict[str, Any]:
        return {
            "endpoint_id": str(getattr(self.endpoint, "endpoint_id", "") or ""),
            "provider_type": str(getattr(self.endpoint, "provider_type", "") or ""),
            "tool_key": str(getattr(self.capability, "tool_key", "") or ""),
            "score": round(self.score, 3),
            "breakdown": self.breakdown.as_dict(),
            "rejected_reasons": list(self.rejected_reasons),
        }


class CoreToolExecutor:
    def __init__(self):
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}

    def register(self, tool_key: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        self._handlers[str(tool_key or "").strip()] = handler

    def has_tool(self, tool_key: str) -> bool:
        return str(tool_key or "").strip() in self._handlers

    async def execute(self, *, tool_key: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get(str(tool_key or "").strip())
        if handler is None:
            raise ToolRouterError("core_tool_not_found", f"Core tool is not registered: {tool_key}")
        result = handler(dict(arguments or {}))
        if asyncio.iscoroutine(result):
            result = await result
        if getattr(result, "ok", None) is False:
            error = getattr(result, "error", None)
            raise ToolRouterError(
                str(getattr(error, "code", "") or "core_tool_failed"),
                str(getattr(error, "message", "") or f"Core tool failed: {tool_key}"),
                details=dict(getattr(error, "details", {}) or {}),
                retryable=bool(getattr(error, "retryable", False)),
            )
        if getattr(result, "ok", None) is True and hasattr(result, "content"):
            content = getattr(result, "content", None)
            data = getattr(content, "data", None)
            if isinstance(data, dict):
                return dict(data)
            if data is not None:
                return {"result": data}
            text = str(getattr(content, "text", "") or "").strip()
            return {"content": text} if text else {}
        return dict(result or {})


class ToolRouterService:
    def __init__(
        self,
        *,
        actor_service,
        workspace_service,
        endpoint_service,
        endpoint_capability_service,
        session_service,
        thread_service,
        operation_service,
        operation_call_service,
    ):
        self._actor_service = actor_service
        self._workspace_service = workspace_service
        self._endpoint_service = endpoint_service
        self._endpoint_capability_service = endpoint_capability_service
        self._session_service = session_service
        self._thread_service = thread_service
        self._operation_service = operation_service
        self._operation_call_service = operation_call_service
        self._core_executor = CoreToolExecutor()
        self._endpoint_transport: Callable[..., Awaitable[bool]] | None = None
        self._external_transport: Callable[..., Awaitable[dict[str, Any]]] | None = None
        self._connected_endpoint_ids_getter: Callable[[], set[str] | list[str] | tuple[str, ...]] | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._resolution_cache_ttl_seconds = 5.0
        self._resolution_cache: dict[tuple[str, str, str, str, bool], tuple[float, ExecutionTarget]] = {}
        self._routing_policy = EndpointRoutingPolicy()

    def set_endpoint_transport(self, transport: Callable[..., Awaitable[bool]] | None) -> None:
        self._endpoint_transport = transport

    def set_external_transport(self, transport: Callable[..., Awaitable[dict[str, Any]]] | None) -> None:
        self._external_transport = transport

    def set_connected_endpoint_ids_getter(self, getter: Callable[[], set[str] | list[str] | tuple[str, ...]] | None) -> None:
        self._connected_endpoint_ids_getter = getter
        self.invalidate_cache()

    def register_core_tool(self, tool_key: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        self._core_executor.register(tool_key, handler)
        self.invalidate_cache(tool_key=tool_key)

    def invalidate_cache(self, *, endpoint_id: str = "", tool_key: str = "", workspace_id: str = "") -> None:
        normalized_endpoint_id = str(endpoint_id or "").strip()
        normalized_tool_key = str(tool_key or "").strip()
        normalized_workspace_id = str(workspace_id or "").strip()
        if not normalized_endpoint_id and not normalized_tool_key and not normalized_workspace_id:
            self._resolution_cache.clear()
            return
        for key, (_, target) in list(self._resolution_cache.items()):
            key_tool, key_workspace, key_endpoint, _key_offline_policy, _key_confirmed = key
            target_endpoint_id = str(getattr(target, "target_id", "") or "")
            if normalized_tool_key and key_tool != normalized_tool_key:
                continue
            if normalized_workspace_id and key_workspace != normalized_workspace_id:
                continue
            if normalized_endpoint_id and key_endpoint != normalized_endpoint_id and target_endpoint_id != normalized_endpoint_id:
                continue
            self._resolution_cache.pop(key, None)

    def _resolution_cache_key(
        self,
        *,
        tool_key: str,
        workspace_id: str,
        execution_target: dict[str, Any] | None,
        endpoint_id: str,
        offline_policy: str,
        confirmed: bool = False,
    ) -> tuple[str, str, str, str, bool]:
        requested = dict(execution_target or {})
        requested_endpoint_id = str(endpoint_id or requested.get("endpoint_id") or requested.get("execution_target_id") or "").strip()
        return (
            str(tool_key or "").strip(),
            str(workspace_id or "").strip(),
            requested_endpoint_id,
            str(offline_policy or "fail_fast").strip() or "fail_fast",
            bool(confirmed),
        )

    def _get_cached_resolution(self, key: tuple[str, str, str, str, bool]) -> ExecutionTarget | None:
        entry = self._resolution_cache.get(key)
        if entry is None:
            return None
        expires_at, target = entry
        if expires_at <= time.monotonic():
            self._resolution_cache.pop(key, None)
            return None
        return target

    def _cache_resolution(self, key: tuple[str, str, str, str, bool], target: ExecutionTarget) -> ExecutionTarget:
        self._resolution_cache[key] = (time.monotonic() + self._resolution_cache_ttl_seconds, target)
        return target

    async def dispatch_workspace_tool(self, **kwargs) -> dict[str, Any]:
        return await self.dispatch_tool_call(**kwargs)

    async def dispatch_tool_call(self, **kwargs) -> dict[str, Any]:
        session_id = str(kwargs.get("session_id") or "").strip()
        workspace_id = str(kwargs.get("workspace_id") or "").strip()
        thread_row_id = kwargs.get("thread_row_id")
        if session_id:
            session_row = self._session_service.get_by_session_id(session_id)
            if session_row is not None:
                thread_row_id = getattr(session_row, "thread_id", None)
                workspace = self._workspace_service.get_by_id(getattr(session_row, "active_workspace_id", None))
                if workspace is None:
                    thread = self._thread_service.get_by_id(thread_row_id)
                    workspace = self._workspace_service.get_by_id(getattr(thread, "workspace_id", None)) if thread is not None else None
                workspace_id = getattr(workspace, "workspace_id", "") or workspace_id
        if not workspace_id:
            raise ToolRouterError("workspace_required", "ToolRouter dispatch requires workspace_id or session_id")
        endpoint_id = str(
            kwargs.get("endpoint_id")
            or kwargs.get("target_endpoint_id")
            or kwargs.get("target_id")
            or ""
        ).strip()
        return await self.route_tool_call(
            tool_key=str(kwargs.get("tool_key") or "").strip(),
            arguments=kwargs.get("arguments") if isinstance(kwargs.get("arguments"), dict) else {},
            workspace_id=workspace_id,
            thread_row_id=thread_row_id,
            requested_by_actor_id=kwargs.get("requested_by_actor_id"),
            requested_by_run_id=kwargs.get("requested_by_run_id"),
            endpoint_id=endpoint_id,
            title=str(kwargs.get("title") or ""),
            timeout_seconds=int(kwargs.get("timeout_seconds") or 120),
            confirmed=bool(kwargs.get("confirmed", False)),
            offline_policy=str(kwargs.get("offline_policy") or "fail_fast"),
            return_operation=bool(kwargs.get("return_operation", False)),
        )

    def resolve_execution_target(
        self,
        *,
        tool_key: str,
        workspace_id: str = "",
        execution_target: dict[str, Any] | None = None,
        endpoint_id: str = "",
        offline_policy: str = "fail_fast",
        confirmed: bool = False,
    ) -> ExecutionTarget:
        cache_key = self._resolution_cache_key(
            tool_key=tool_key,
            workspace_id=workspace_id,
            execution_target=execution_target,
            endpoint_id=endpoint_id,
            offline_policy=offline_policy,
            confirmed=confirmed,
        )
        cached = self._get_cached_resolution(cache_key)
        if cached is not None:
            return cached
        target = self._resolve_execution_target_uncached(
            tool_key=tool_key,
            workspace_id=workspace_id,
            execution_target=execution_target,
            endpoint_id=endpoint_id,
            offline_policy=offline_policy,
            confirmed=confirmed,
        )
        return self._cache_resolution(cache_key, target)

    def _resolve_execution_target_uncached(
        self,
        *,
        tool_key: str,
        workspace_id: str = "",
        execution_target: dict[str, Any] | None = None,
        endpoint_id: str = "",
        offline_policy: str = "fail_fast",
        confirmed: bool = False,
    ) -> ExecutionTarget:
        normalized_tool_key = str(tool_key or "").strip()
        requested = dict(execution_target or {})
        requested_endpoint_id = str(endpoint_id or requested.get("endpoint_id") or requested.get("execution_target_id") or "").strip()
        if requested_endpoint_id:
            endpoint = self._endpoint_service.get_by_endpoint_id(requested_endpoint_id)
            if endpoint is None:
                raise ToolRouterError("execution_target_not_found", f"Execution target not found: {requested_endpoint_id}", retryable=True)
            capability = None
            for candidate in self._endpoint_capability_service.list_for_endpoint(endpoint_row_id=endpoint.id):
                if str(getattr(candidate, "tool_key", "") or "") == normalized_tool_key and bool(getattr(candidate, "enabled", True)):
                    capability = candidate
                    break
            if requested_endpoint_id == "core.local":
                return ExecutionTarget("core.local", "core", endpoint=endpoint, endpoint_capability=capability)
            if capability is None:
                raise ToolRouterError(
                    "endpoint_capability_not_found",
                    f"Endpoint cannot execute tool: {requested_endpoint_id} -> {normalized_tool_key}",
                    details={"endpoint_id": requested_endpoint_id, "tool_key": normalized_tool_key},
                )
            provider_type = str(getattr(endpoint, "provider_type", "") or "").strip()
            target_type = "external" if provider_type in {"external", "webhook", "feishu", "wechatbot", "email"} else "endpoint"
            if target_type == "endpoint" and not self._endpoint_can_dispatch(endpoint, offline_policy=offline_policy):
                raise ToolRouterError(
                    "target_endpoint_unavailable",
                    f"Endpoint is unavailable: {requested_endpoint_id}",
                    details={"endpoint_id": requested_endpoint_id, "tool_key": normalized_tool_key},
                    retryable=True,
                )
            decision = {
                "mode": "explicit",
                "selected_endpoint_id": requested_endpoint_id,
                "tool_key": normalized_tool_key,
                "reason": "explicit_endpoint",
            }
            return ExecutionTarget(requested_endpoint_id, target_type, endpoint=endpoint, endpoint_capability=capability, offline_policy=offline_policy, routing_decision=decision)

        if self._core_executor.has_tool(normalized_tool_key) or normalized_tool_key.startswith("core."):
            endpoint = self._endpoint_service.get_by_endpoint_id("core.local")
            return ExecutionTarget("core.local", "core", endpoint=endpoint)

        workspace = self._workspace_service.get_by_workspace_id(workspace_id) if workspace_id else None
        capabilities = self._endpoint_capability_service.list_enabled_for_tool(tool_key=normalized_tool_key)
        selected, rejected = self._select_best_endpoint_candidate(
            tool_key=normalized_tool_key,
            workspace=workspace,
            capabilities=capabilities,
            confirmed=confirmed,
            offline_policy=offline_policy,
        )
        if selected is not None:
            routing_decision = self._routing_decision(
                tool_key=normalized_tool_key,
                selected=selected,
                rejected=rejected,
                mode="scored",
            )
            return ExecutionTarget(
                getattr(selected.endpoint, "endpoint_id", ""),
                selected.target_type,
                endpoint=selected.endpoint,
                endpoint_capability=selected.capability,
                offline_policy=offline_policy,
                routing_decision=routing_decision,
            )
        if offline_policy in {"queue_until_online", "store_in_outbox"} and capabilities:
            capability = capabilities[0]
            endpoint = self._endpoint_service.get_by_id(getattr(capability, "endpoint_id", None))
            if endpoint is not None:
                routing_decision = {
                    "mode": "offline_policy",
                    "selected_endpoint_id": str(getattr(endpoint, "endpoint_id", "") or ""),
                    "tool_key": normalized_tool_key,
                    "reason": "queued_until_endpoint_online",
                    "candidate_count": len(capabilities),
                }
                return ExecutionTarget(endpoint.endpoint_id, "endpoint", endpoint=endpoint, endpoint_capability=capability, offline_policy=offline_policy, routing_decision=routing_decision)
        raise ToolRouterError("execution_target_unavailable", f"No execution target can run tool: {normalized_tool_key}", retryable=True)

    def _connected_endpoint_ids(self) -> set[str] | None:
        getter = self._connected_endpoint_ids_getter
        if getter is None:
            return None
        try:
            values = getter()
        except Exception:
            return None
        return {str(item or "").strip() for item in (values or []) if str(item or "").strip()}

    @staticmethod
    def _is_db_online(endpoint) -> bool:
        status = str(getattr(endpoint, "status", "") or "").strip().lower()
        return status in {"ready", "online", "active"}

    def _endpoint_can_dispatch(self, endpoint, *, offline_policy: str) -> bool:
        endpoint_id = str(getattr(endpoint, "endpoint_id", "") or "").strip()
        connected = self._connected_endpoint_ids()
        if connected is not None:
            return endpoint_id in connected or offline_policy in {"queue_until_online", "store_in_outbox"}
        return self._is_db_online(endpoint) or offline_policy in {"queue_until_online", "store_in_outbox"}

    def _workspace_preferences(self, workspace, *, tool_key: str) -> dict[str, Any]:
        if workspace is None:
            return {
                "preferred_target_endpoint_ids": [],
                "preferred_endpoint_provider_types": [],
                "tool_target_routing_policy": "balanced",
                "source": "none",
            }
        getter = getattr(self._workspace_service, "get_effective_tool_target_preferences", None)
        if callable(getter):
            try:
                return dict(getter(workspace, tool_key=tool_key) or {})
            except TypeError:
                pass
        meta = dict(getattr(workspace, "meta", {}) or {})
        return {
            "preferred_target_endpoint_ids": list(meta.get("preferred_target_endpoint_ids") or []),
            "preferred_endpoint_provider_types": list(meta.get("preferred_endpoint_provider_types") or []),
            "tool_target_routing_policy": str(meta.get("tool_target_routing_policy") or "balanced"),
            "source": "workspace_metadata",
        }

    def _select_best_endpoint_candidate(
        self,
        *,
        tool_key: str,
        workspace,
        capabilities: list[Any],
        confirmed: bool,
        offline_policy: str,
    ) -> tuple[EndpointCandidate | None, list[EndpointCandidate]]:
        preferences = self._workspace_preferences(workspace, tool_key=tool_key)
        selected: list[EndpointCandidate] = []
        rejected: list[EndpointCandidate] = []
        connected = self._connected_endpoint_ids()
        for capability in capabilities:
            endpoint = self._endpoint_service.get_by_id(getattr(capability, "endpoint_id", None))
            if endpoint is None:
                continue
            candidate = self._score_endpoint_candidate(
                endpoint=endpoint,
                capability=capability,
                tool_key=tool_key,
                workspace=workspace,
                preferences=preferences,
                connected_endpoint_ids=connected,
                confirmed=confirmed,
                offline_policy=offline_policy,
            )
            if candidate.rejected_reasons:
                rejected.append(candidate)
            else:
                selected.append(candidate)
        if not selected:
            return None, rejected
        selected.sort(key=lambda item: (item.score, -int(getattr(item.endpoint, "priority", 100) or 100), str(getattr(item.endpoint, "endpoint_id", ""))), reverse=True)
        return selected[0], rejected + selected[1:]

    def _score_endpoint_candidate(
        self,
        *,
        endpoint,
        capability,
        tool_key: str,
        workspace,
        preferences: dict[str, Any],
        connected_endpoint_ids: set[str] | None,
        confirmed: bool,
        offline_policy: str,
    ) -> EndpointCandidate:
        policy = self._routing_policy
        endpoint_id = str(getattr(endpoint, "endpoint_id", "") or "").strip()
        provider_type = str(getattr(endpoint, "provider_type", "") or "").strip()
        endpoint_meta = dict(getattr(endpoint, "meta", {}) or {})
        capability_meta = dict(getattr(capability, "meta", {}) or {})
        scope = [str(item or "").strip() for item in (getattr(endpoint, "workspace_scope", []) or []) if str(item or "").strip()]
        workspace_id = str(getattr(workspace, "workspace_id", "") or "").strip()
        rejected: list[str] = []
        breakdown = EndpointScoreBreakdown()

        if connected_endpoint_ids is not None:
            if endpoint_id in connected_endpoint_ids:
                breakdown.online_status = policy.online_weight
            elif offline_policy in {"queue_until_online", "store_in_outbox"}:
                breakdown.online_status = 0
            else:
                rejected.append("endpoint_disconnected")
        elif self._is_db_online(endpoint):
            breakdown.online_status = policy.db_online_weight
        elif offline_policy in {"queue_until_online", "store_in_outbox"}:
            breakdown.online_status = 0
        else:
            rejected.append("endpoint_not_online")

        if workspace_id:
            if not scope:
                breakdown.workspace_match = policy.workspace_open_weight
            elif workspace_id in scope:
                breakdown.workspace_match = policy.workspace_exact_weight
            elif "*" in scope:
                breakdown.workspace_match = policy.workspace_wildcard_weight
            else:
                rejected.append("workspace_mismatch")

        preferred_endpoint_ids = [str(item or "").strip() for item in preferences.get("preferred_target_endpoint_ids", []) if str(item or "").strip()]
        preferred_provider_types = [str(item or "").strip() for item in preferences.get("preferred_endpoint_provider_types", []) if str(item or "").strip()]
        routing_policy = str(preferences.get("tool_target_routing_policy") or "balanced").strip() or "balanced"
        if endpoint_id in preferred_endpoint_ids:
            breakdown.preference += policy.preferred_endpoint_weight
        if provider_type in preferred_provider_types:
            breakdown.preference += policy.preferred_provider_weight
        if routing_policy == "strict_preferred_endpoint":
            has_endpoint_preference = bool(preferred_endpoint_ids)
            has_provider_preference = bool(preferred_provider_types)
            if has_endpoint_preference and endpoint_id not in preferred_endpoint_ids:
                rejected.append("strict_preferred_endpoint_mismatch")
            if not has_endpoint_preference and has_provider_preference and provider_type not in preferred_provider_types:
                rejected.append("strict_preferred_provider_mismatch")

        risk_level = str(getattr(capability, "risk_level", "") or capability_meta.get("risk_level") or "read").strip().lower()
        if bool(getattr(capability, "requires_confirmation", False)) and not confirmed:
            rejected.append("confirmation_required")
        risk_scores = {
            "read": policy.low_risk_weight,
            "low": policy.low_risk_weight,
            "network": policy.low_risk_weight * 0.65,
            "write": policy.low_risk_weight * 0.45,
            "system": policy.low_risk_weight * 0.2,
            "high": 0.0,
        }
        breakdown.risk = risk_scores.get(risk_level, policy.low_risk_weight * 0.35)

        try:
            priority = int(getattr(endpoint, "priority", 100) or 100)
        except (TypeError, ValueError):
            priority = 100
        breakdown.priority = max(-policy.priority_weight, min(policy.priority_weight, (100 - priority) / 100 * policy.priority_weight))

        metrics = endpoint_meta.get("heartbeat_metrics")
        if not isinstance(metrics, dict):
            heartbeat = endpoint_meta.get("heartbeat") if isinstance(endpoint_meta.get("heartbeat"), dict) else {}
            metrics = heartbeat.get("metrics") if isinstance(heartbeat.get("metrics"), dict) else {}
        breakdown.load = self._score_load(metrics, policy=policy)

        stats = endpoint_meta.get("routing_stats") if isinstance(endpoint_meta.get("routing_stats"), dict) else {}
        breakdown.success_rate = self._score_success_rate(stats, policy=policy)
        breakdown.latency = self._score_latency(stats, policy=policy)
        breakdown.trust = self._score_trust(provider_type=provider_type, tool_key=tool_key, policy=policy)
        breakdown.cost = self._score_cost(endpoint_meta, policy=policy)

        target_type = "external" if provider_type in {"external", "webhook", "feishu", "wechatbot", "email"} else "endpoint"
        return EndpointCandidate(
            endpoint=endpoint,
            capability=capability,
            target_type=target_type,
            breakdown=breakdown,
            rejected_reasons=rejected,
        )

    @staticmethod
    def _float_metric(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
        try:
            return float(metrics.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    def _score_load(self, metrics: dict[str, Any], *, policy: EndpointRoutingPolicy) -> float:
        if not isinstance(metrics, dict) or not metrics:
            return 0.0
        active_calls = self._float_metric(metrics, "active_calls")
        cpu_percent = self._float_metric(metrics, "cpu_percent")
        memory_percent = self._float_metric(metrics, "memory_percent")
        penalty = active_calls * 5.0 + max(0.0, cpu_percent - 60.0) / 5.0 + max(0.0, memory_percent - 70.0) / 5.0
        return max(-policy.load_weight, policy.load_weight - penalty)

    def _score_success_rate(self, stats: dict[str, Any], *, policy: EndpointRoutingPolicy) -> float:
        successes = self._float_metric(stats, "success_count")
        failures = self._float_metric(stats, "failure_count")
        total = successes + failures
        if total <= 0:
            return 0.0
        success_rate = successes / total
        return (success_rate - 0.5) * 2 * policy.success_weight

    def _score_latency(self, stats: dict[str, Any], *, policy: EndpointRoutingPolicy) -> float:
        avg_latency_ms = self._float_metric(stats, "average_latency_ms", default=-1)
        if avg_latency_ms < 0:
            return 0.0
        bounded = max(0.0, min(avg_latency_ms, 30000.0))
        return max(-policy.latency_weight, policy.latency_weight * (1 - bounded / 15000.0))

    def _score_trust(self, *, provider_type: str, tool_key: str, policy: EndpointRoutingPolicy) -> float:
        normalized_tool = str(tool_key or "").strip()
        local_tool = normalized_tool.startswith(("file.", "shell.", "workspace.", "utility."))
        delivery_tool = normalized_tool.startswith(("message.", "notice.", "email.", "delivery."))
        if provider_type in {"desktop", "edge"} and local_tool:
            return policy.trust_weight
        if provider_type in {"external", "webhook", "feishu", "wechatbot", "email"} and delivery_tool:
            return policy.trust_weight
        if provider_type in {"external", "webhook", "feishu", "wechatbot", "email"} and local_tool:
            return -policy.trust_weight
        return 0.0

    def _score_cost(self, endpoint_meta: dict[str, Any], *, policy: EndpointRoutingPolicy) -> float:
        cost_level = str(endpoint_meta.get("cost_level") or endpoint_meta.get("cost") or "").strip().lower()
        if cost_level in {"free", "low", "local"}:
            return policy.cost_weight
        if cost_level in {"high", "expensive"}:
            return -policy.cost_weight
        return 0.0

    @staticmethod
    def _call_latency_ms(call_row) -> float | None:
        created_at = getattr(call_row, "created_at", None)
        updated_at = getattr(call_row, "updated_at", None)
        if not isinstance(created_at, datetime) or not isinstance(updated_at, datetime):
            return None
        return max(0.0, (updated_at - created_at).total_seconds() * 1000)

    def _record_endpoint_routing_result(self, call_row, *, success: bool) -> None:
        endpoint_row_id = getattr(call_row, "target_endpoint_id", None)
        recorder = getattr(self._endpoint_service, "record_routing_result", None)
        if endpoint_row_id is None or not callable(recorder):
            return
        recorder(
            endpoint_row_id=endpoint_row_id,
            success=success,
            latency_ms=self._call_latency_ms(call_row),
        )

    def _routing_decision(
        self,
        *,
        tool_key: str,
        selected: EndpointCandidate,
        rejected: list[EndpointCandidate],
        mode: str,
    ) -> dict[str, Any]:
        selected_item = selected.to_decision_item()
        return {
            "mode": mode,
            "tool_key": tool_key,
            "selected_endpoint_id": selected_item["endpoint_id"],
            "score": selected_item["score"],
            "breakdown": selected_item["breakdown"],
            "candidate_count": len(rejected) + 1,
            "rejected_candidates": [item.to_decision_item() for item in rejected[:8]],
        }

    def resolve_execution_targets(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for request in requests or []:
            payload = dict(request or {})
            try:
                target = self.resolve_execution_target(
                    tool_key=str(payload.get("tool_key") or "").strip(),
                    workspace_id=str(payload.get("workspace_id") or "").strip(),
                    execution_target=payload.get("execution_target") if isinstance(payload.get("execution_target"), dict) else None,
                    endpoint_id=str(payload.get("endpoint_id") or payload.get("target_endpoint_id") or "").strip(),
                    offline_policy=str(payload.get("offline_policy") or "fail_fast"),
                    confirmed=bool(payload.get("confirmed", False)),
                )
                results.append({"ok": True, "target": target})
            except ToolRouterError as exc:
                results.append(
                    {
                        "ok": False,
                        "error": {
                            "code": exc.code,
                            "message": exc.message,
                            "details": dict(exc.details or {}),
                            "retryable": exc.retryable,
                        },
                    }
                )
        return results

    async def route_tool_call(
        self,
        *,
        tool_key: str,
        arguments: dict[str, Any],
        workspace_id: str,
        thread_row_id=None,
        requested_by_actor_id=None,
        requested_by_run_id=None,
        execution_target: dict[str, Any] | None = None,
        endpoint_id: str = "",
        title: str = "",
        timeout_seconds: int = 120,
        confirmed: bool = False,
        offline_policy: str = "fail_fast",
        return_operation: bool = False,
    ) -> dict[str, Any]:
        target = self.resolve_execution_target(
            tool_key=tool_key,
            workspace_id=workspace_id,
            execution_target=execution_target,
            endpoint_id=endpoint_id,
            offline_policy=offline_policy,
            confirmed=confirmed,
        )
        if target.target_type == "core":
            return await self._core_executor.execute(tool_key=tool_key, arguments=arguments)
        return await self._dispatch_target(
            target=target,
            tool_key=tool_key,
            arguments=arguments,
            workspace_id=workspace_id,
            thread_row_id=thread_row_id,
            requested_by_actor_id=requested_by_actor_id,
            requested_by_run_id=requested_by_run_id,
            title=title,
            timeout_seconds=timeout_seconds,
            confirmed=confirmed,
            return_operation=return_operation,
        )

    async def _dispatch_target(
        self,
        *,
        target: ExecutionTarget,
        tool_key: str,
        arguments: dict[str, Any],
        workspace_id: str,
        thread_row_id=None,
        requested_by_actor_id=None,
        requested_by_run_id=None,
        title: str = "",
        timeout_seconds: int = 120,
        confirmed: bool = False,
        return_operation: bool = False,
    ) -> dict[str, Any]:
        workspace = self._workspace_service.get_by_workspace_id(workspace_id)
        if workspace is None:
            raise ToolRouterError("workspace_not_found", f"Workspace not found: {workspace_id}")
        capability = target.endpoint_capability
        if capability is not None and bool(getattr(capability, "requires_confirmation", False)) and not confirmed:
            raise ToolRouterError(
                "tool_confirmation_required",
                "Tool call requires explicit confirmation before dispatch.",
                details={
                    "endpoint_id": target.target_id,
                    "tool_key": tool_key,
                    "risk_level": getattr(capability, "risk_level", ""),
                },
            )
        try:
            protected_arguments = protect_sensitive_arguments(arguments, purpose=ENDPOINT_TOOL_ARGUMENTS_PURPOSE)
        except CredentialTransportError as exc:
            raise ToolRouterError(exc.code, exc.message) from exc
        operation = self._operation_service.create_operation(
            thread_id=thread_row_id,
            workspace_id=workspace.id,
            operation_type="tool_call",
            execution_target=target.target_id,
            execution_target_type=target.target_type,
            execution_target_id=target.target_id,
            target_endpoint_id=getattr(target.endpoint, "id", None),
            requested_by_actor_id=requested_by_actor_id,
            requested_by_run_id=requested_by_run_id,
            title=title or f"Tool: {tool_key}",
            status="queued",
            metadata={
                "tool_key": tool_key,
                "execution_target_id": target.target_id,
                "target_endpoint_id": target.target_id,
                "routing_decision": dict(target.routing_decision or {}),
                "arguments": dict(protected_arguments.public_arguments or {}),
                "arguments_encrypted": bool(protected_arguments.encrypted_arguments),
            },
        )
        call = self._operation_call_service.create_call(
            operation_id=operation.id,
            endpoint_capability_id=getattr(capability, "id", None),
            target_endpoint_id=getattr(target.endpoint, "id", None),
            execution_target_id=target.target_id,
            status="queued",
            arguments=dict(protected_arguments.public_arguments or {}),
        )
        frame = {
            "schema": "meetyou.endpoint.ws.v4",
            "type": "tool.call.request",
            "endpoint_id": target.target_id,
            "message_id": f"dispatch-{call.call_id}",
            "payload": {
                "operation_id": operation.operation_id,
                "call_id": call.call_id,
                "workspace_id": workspace.workspace_id,
                "tool_key": str(tool_key or "").strip(),
                "capability_id": str(getattr(capability, "capability_id", "") or ""),
                "arguments": dict(protected_arguments.public_arguments or {}),
                "encrypted_arguments": protected_arguments.encrypted_arguments,
                "timeout_seconds": timeout_seconds,
                "audit_context": {
                    "requested_by_actor_id": str(requested_by_actor_id or ""),
                    "requested_by_run_id": str(requested_by_run_id or ""),
                    "execution_target_id": target.target_id,
                },
            },
        }
        if target.target_type == "external":
            if self._external_transport is None:
                raise ToolRouterError("external_executor_unavailable", "External executor is unavailable", retryable=True)
            result = dict(await self._external_transport(endpoint_id=target.target_id, frame=frame) or {})
            if return_operation:
                return {
                    "status": "succeeded",
                    "operation_id": operation.operation_id,
                    "call_id": call.call_id,
                    "execution_target_id": target.target_id,
                    "result": result,
                }
            return result
        if self._endpoint_transport is None:
            self._operation_call_service.mark_failed(call_id=call.call_id, error={"code": "endpoint_transport_unavailable"})
            raise ToolRouterError("endpoint_transport_unavailable", "Endpoint transport is unavailable", retryable=True)

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        async with self._lock:
            self._pending[call.call_id] = future
        dispatched = await self._endpoint_transport(endpoint_id=target.target_id, payload=frame)
        if not dispatched:
            async with self._lock:
                self._pending.pop(call.call_id, None)
            if target.offline_policy in {"queue_until_online", "store_in_outbox"}:
                self._operation_call_service.mark_failed(call_id=call.call_id, error={"code": "waiting_for_endpoint"})
                return {"status": "waiting_for_endpoint", "operation_id": operation.operation_id, "call_id": call.call_id}
            self._operation_call_service.mark_failed(call_id=call.call_id, error={"code": "target_endpoint_unavailable"})
            raise ToolRouterError("target_endpoint_unavailable", f"Endpoint is unavailable: {target.target_id}", retryable=True)
        self._operation_call_service.mark_dispatched(call_id=call.call_id)
        try:
            result = await asyncio.wait_for(future, timeout=max(5, timeout_seconds))
            if return_operation:
                return {
                    "status": "succeeded",
                    "operation_id": operation.operation_id,
                    "call_id": call.call_id,
                    "execution_target_id": target.target_id,
                    "result": dict(result or {}),
                }
            return result
        except asyncio.TimeoutError as exc:
            self._operation_call_service.mark_failed(call_id=call.call_id, error={"code": "endpoint_tool_timeout"})
            raise ToolRouterError("endpoint_tool_timeout", f"Endpoint tool call timed out after {timeout_seconds} seconds", retryable=True) from exc
        finally:
            async with self._lock:
                self._pending.pop(call.call_id, None)

    async def notify_call_result(self, call_id: str, result: dict[str, Any]):
        call_row = self._operation_call_service.mark_succeeded(call_id=call_id, result=result)
        self._record_endpoint_routing_result(call_row, success=True)
        async with self._lock:
            future = self._pending.get(call_id)
            if future is not None and not future.done():
                future.set_result(dict(result or {}))
        return call_row

    async def notify_call_error(self, call_id: str, error: dict[str, Any]):
        call_row = self._operation_call_service.mark_failed(call_id=call_id, error=error)
        self._record_endpoint_routing_result(call_row, success=False)
        async with self._lock:
            future = self._pending.get(call_id)
            if future is not None and not future.done():
                future.set_exception(
                    ToolRouterError(
                        str(error.get("code") or "endpoint_tool_failed"),
                        str(error.get("message") or "Endpoint tool call failed"),
                        details=dict(error or {}),
                        retryable=bool(error.get("retryable", False)),
                    )
                )
        return call_row
