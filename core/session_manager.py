"""
会话管理器。
"""

from dataclasses import dataclass, field
import time
from typing import Any
from uuid import uuid4

from core.io_protocol import EventSource, EventTarget, TargetKind


@dataclass(slots=True)
class SessionBinding:
    session_id: str
    source: EventSource
    default_target: EventTarget
    metadata: dict[str, Any] = field(default_factory=dict)


class SessionManager:
    """
    负责来源与会话的绑定关系，以及默认输出目标解析。
    """

    def __init__(self):
        self._bindings: dict[str, SessionBinding] = {}
        self._source_to_session: dict[str, str] = {}
        self._stream_to_session: dict[str, str] = {}
        self._inbound_event_ids: dict[tuple[str, str, str], str] = {}
        self._inbound_event_order: list[tuple[float, tuple[str, str, str]]] = []
        self._max_inbound_event_keys = 2048

    @staticmethod
    def _now_ts() -> float:
        return time.time()

    def _touch_binding(self, binding: SessionBinding):
        binding.metadata["last_active_at"] = self._now_ts()

    def _build_source_key(self, source: EventSource) -> str:
        return f"{source.kind}:{source.id or 'default'}"

    def _build_inbound_event_key(
        self,
        session_id: str,
        source: EventSource,
        external_message_id: str,
    ) -> tuple[str, str, str]:
        return (
            str(session_id or "").strip(),
            self._build_source_key(source),
            str(external_message_id or "").strip(),
        )

    def _prune_inbound_event_ids(self):
        overflow = len(self._inbound_event_order) - self._max_inbound_event_keys
        if overflow <= 0:
            return
        for _ in range(overflow):
            _, key = self._inbound_event_order.pop(0)
            self._inbound_event_ids.pop(key, None)

    def _build_default_target(self, source: EventSource) -> EventTarget:
        target_kind_map = {
            "cli": TargetKind.CLI.value,
            "web": TargetKind.WEB.value,
            "feishu": TargetKind.FEISHU.value,
        }
        return EventTarget(
            kind=target_kind_map.get(source.kind, TargetKind.INTERNAL.value),
            id=source.id,
            metadata=dict(source.metadata),
        )

    def register_source(
        self,
        source: EventSource,
        session_id: str | None = None,
        default_target: EventTarget | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        key = self._build_source_key(source)
        existing = self._source_to_session.get(key)
        if existing:
            self.touch_session(existing)
            return existing

        final_session_id = session_id or f"{source.kind}:{source.id or uuid4().hex}"
        binding = SessionBinding(
            session_id=final_session_id,
            source=source,
            default_target=default_target or self._build_default_target(source),
            metadata=metadata or {},
        )
        self._touch_binding(binding)
        self._bindings[final_session_id] = binding
        self._source_to_session[key] = final_session_id
        return final_session_id

    def get_or_create_session(self, source: EventSource, session_id: str | None = None) -> str:
        if session_id:
            if session_id not in self._bindings:
                self._bindings[session_id] = SessionBinding(
                    session_id=session_id,
                    source=source,
                    default_target=self._build_default_target(source),
                )
                self._source_to_session[self._build_source_key(source)] = session_id
            self.touch_session(session_id)
            return session_id
        return self.register_source(source)

    def get_binding(self, session_id: str) -> SessionBinding | None:
        return self._bindings.get(session_id)

    def touch_session(self, session_id: str):
        binding = self.get_binding(session_id)
        if binding:
            self._touch_binding(binding)

    def get_default_target(self, session_id: str) -> EventTarget:
        binding = self.get_binding(session_id)
        if binding:
            return binding.default_target
        return EventTarget(kind=TargetKind.CURRENT_SESSION.value)

    def set_default_target(self, session_id: str, target: EventTarget):
        binding = self.get_binding(session_id)
        if binding:
            binding.default_target = target
            self._touch_binding(binding)

    def list_recent_bindings(self) -> list[SessionBinding]:
        return sorted(
            self._bindings.values(),
            key=lambda binding: float(binding.metadata.get("last_active_at", 0.0) or 0.0),
            reverse=True,
        )

    def list_default_targets(self) -> list[EventTarget]:
        seen: set[tuple[str, str]] = set()
        targets: list[EventTarget] = []
        for binding in self._bindings.values():
            target = binding.default_target
            key = (target.kind, target.id)
            if key in seen:
                continue
            seen.add(key)
            targets.append(EventTarget(
                kind=target.kind,
                id=target.id,
                metadata=dict(target.metadata),
            ))
        return targets

    def create_stream_id(self, session_id: str) -> str:
        stream_id = uuid4().hex
        self._stream_to_session[stream_id] = session_id
        return stream_id

    def resolve_stream_session(self, stream_id: str) -> str | None:
        return self._stream_to_session.get(stream_id)

    def close_stream(self, stream_id: str):
        self._stream_to_session.pop(stream_id, None)

    def get_recent_inbound_event_id(
        self,
        session_id: str,
        source: EventSource,
        external_message_id: str,
    ) -> str:
        normalized_external_id = str(external_message_id or "").strip()
        if not normalized_external_id:
            return ""
        key = self._build_inbound_event_key(session_id, source, normalized_external_id)
        return self._inbound_event_ids.get(key, "")

    def remember_inbound_event_id(
        self,
        session_id: str,
        source: EventSource,
        external_message_id: str,
        event_id: str,
    ) -> str:
        normalized_external_id = str(external_message_id or "").strip()
        normalized_event_id = str(event_id or "").strip()
        if not normalized_external_id or not normalized_event_id:
            return normalized_event_id

        key = self._build_inbound_event_key(session_id, source, normalized_external_id)
        existing_event_id = self._inbound_event_ids.get(key, "")
        if existing_event_id:
            self.touch_session(session_id)
            return existing_event_id

        self._inbound_event_ids[key] = normalized_event_id
        self._inbound_event_order.append((self._now_ts(), key))
        self._prune_inbound_event_ids()
        self.touch_session(session_id)
        return normalized_event_id
