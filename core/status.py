"""
Runtime status and usage tracking helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def utcnow_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class RuntimeStatus(str, Enum):
    INITIALIZING = "initializing"
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALLING = "tool_calling"
    ANSWERING = "answering"
    WAITING_CONFIRM = "waiting_confirm"
    HEARTBEAT = "heartbeat"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"


@dataclass
class UsageCounters:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: "UsageCounters") -> None:
        self.prompt_tokens += int(other.prompt_tokens)
        self.completion_tokens += int(other.completion_tokens)
        self.reasoning_tokens += int(other.reasoning_tokens)
        self.total_tokens += int(other.total_tokens)

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": int(self.prompt_tokens),
            "completion_tokens": int(self.completion_tokens),
            "reasoning_tokens": int(self.reasoning_tokens),
            "total_tokens": int(self.total_tokens),
        }


@dataclass
class SessionUsageTotals(UsageCounters):
    turn_count: int = 0

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload["turn_count"] = int(self.turn_count)
        return payload


@dataclass
class ContextBreakdown:
    system: int = 0
    history: int = 0
    tool_history: int = 0
    memory_context: int = 0
    policy: int = 0
    current_input: int = 0
    proprioception: int = 0
    total: int = 0

    @classmethod
    def from_mapping(cls, data: dict | None = None) -> "ContextBreakdown":
        data = data or {}
        breakdown = cls(
            system=int(data.get("system", 0) or 0),
            history=int(data.get("history", 0) or 0),
            tool_history=int(data.get("tool_history", 0) or 0),
            memory_context=int(data.get("memory_context", 0) or 0),
            policy=int(data.get("policy", 0) or 0),
            current_input=int(data.get("current_input", 0) or 0),
            proprioception=int(data.get("proprioception", 0) or 0),
        )
        breakdown.total = int(
            data.get("total")
            or (
                breakdown.system
                + breakdown.history
                + breakdown.tool_history
                + breakdown.memory_context
                + breakdown.policy
                + breakdown.current_input
                + breakdown.proprioception
            )
        )
        return breakdown

    def to_dict(self) -> dict:
        return {
            "system": int(self.system),
            "history": int(self.history),
            "tool_history": int(self.tool_history),
            "memory_context": int(self.memory_context),
            "policy": int(self.policy),
            "current_input": int(self.current_input),
            "proprioception": int(self.proprioception),
            "total": int(self.total),
        }


@dataclass
class RuntimeStateSnapshot:
    session_id: str = ""
    status: str = RuntimeStatus.IDLE.value
    detail: str = ""
    active_tools: list[str] = field(default_factory=list)
    current_mode: str = ""
    route_reason: str = ""
    action_risk: str = "read"
    source_profile: str = ""
    stream_id: str = ""
    turn_id: str = ""
    updated_at: str = field(default_factory=utcnow_iso)

    def update(
        self,
        *,
        status: str | RuntimeStatus,
        detail: str = "",
        active_tools: list[str] | None = None,
        current_mode: str | None = None,
        route_reason: str | None = None,
        action_risk: str | None = None,
        source_profile: str | None = None,
        stream_id: str | None = None,
        turn_id: str | None = None,
    ) -> "RuntimeStateSnapshot":
        self.status = status.value if isinstance(status, RuntimeStatus) else str(status)
        self.detail = detail
        if active_tools is not None:
            self.active_tools = list(active_tools)
        if current_mode is not None:
            self.current_mode = str(current_mode)
        if route_reason is not None:
            self.route_reason = str(route_reason)
        if action_risk is not None:
            self.action_risk = str(action_risk)
        if source_profile is not None:
            self.source_profile = str(source_profile)
        if stream_id is not None:
            self.stream_id = stream_id
        if turn_id is not None:
            self.turn_id = turn_id
        self.updated_at = utcnow_iso()
        return self

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "detail": self.detail,
            "active_tools": list(self.active_tools),
            "current_mode": self.current_mode,
            "route_reason": self.route_reason,
            "action_risk": self.action_risk,
            "source_profile": self.source_profile,
            "stream_id": self.stream_id,
            "turn_id": self.turn_id,
            "updated_at": self.updated_at,
        }


@dataclass
class UsageSnapshot:
    session_id: str = ""
    context_limit_tokens: int = 0
    current_context_tokens_estimated: int = 0
    context_breakdown: ContextBreakdown = field(default_factory=ContextBreakdown)
    last_turn_usage: UsageCounters = field(default_factory=UsageCounters)
    session_totals: SessionUsageTotals = field(default_factory=SessionUsageTotals)
    usage_source: str = "estimated"
    updated_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "context_limit_tokens": int(self.context_limit_tokens),
            "current_context_tokens_estimated": int(self.current_context_tokens_estimated),
            "context_breakdown": self.context_breakdown.to_dict(),
            "last_turn_usage": self.last_turn_usage.to_dict(),
            "session_totals": self.session_totals.to_dict(),
            "usage_source": self.usage_source,
            "updated_at": self.updated_at,
        }


class StatusManager:
    """
    Tracks runtime-wide state that is not bound to a single conversation session.
    """

    def __init__(self):
        self._global_state = RuntimeStateSnapshot(
            session_id="system:global",
            status=RuntimeStatus.INITIALIZING.value,
        )
        self._heartbeat_state = RuntimeStateSnapshot(
            session_id="system:heart",
            status=RuntimeStatus.IDLE.value,
        )

    def set_global(
        self,
        status: str | RuntimeStatus,
        detail: str = "",
    ) -> dict:
        return self._global_state.update(status=status, detail=detail).to_dict()

    def set_heartbeat(
        self,
        status: str | RuntimeStatus,
        detail: str = "",
    ) -> dict:
        active_tools = [] if status != RuntimeStatus.HEARTBEAT else ["heartbeat"]
        return self._heartbeat_state.update(
            status=status,
            detail=detail,
            active_tools=active_tools,
        ).to_dict()

    def get_global(self) -> dict:
        return self._global_state.to_dict()

    def get_heartbeat(self) -> dict:
        return self._heartbeat_state.to_dict()
