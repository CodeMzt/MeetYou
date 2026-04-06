"""
运行时事件上下文。
"""

from contextvars import ContextVar, Token
from uuid import uuid4


_EVENT_CONTEXT: ContextVar[dict] = ContextVar("event_context", default={})
_CORRELATION_KEYS = ("trace_id", "session_id", "turn_id", "job_id", "tool_call_id")


def _normalize_id(value) -> str:
    return str(value or "").strip()


def new_trace_id() -> str:
    return uuid4().hex


def correlation_context(**overrides) -> dict:
    current = dict(_EVENT_CONTEXT.get())
    resolved = {
        key: _normalize_id(overrides.get(key, current.get(key)))
        for key in _CORRELATION_KEYS
    }
    if not resolved["trace_id"]:
        resolved["trace_id"] = new_trace_id()
    return resolved


def bind_event_context(**kwargs) -> Token:
    current = dict(_EVENT_CONTEXT.get())
    current.update(kwargs)
    if kwargs or any(key in current for key in _CORRELATION_KEYS):
        current.update(correlation_context(**current))
    return _EVENT_CONTEXT.set(current)


def get_event_context() -> dict:
    return dict(_EVENT_CONTEXT.get())


def get_correlation_context(**overrides) -> dict:
    return correlation_context(**overrides)


def reset_event_context(token: Token):
    _EVENT_CONTEXT.reset(token)
