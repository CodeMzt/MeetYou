"""
运行时事件上下文。
"""

from contextvars import ContextVar, Token


_EVENT_CONTEXT: ContextVar[dict] = ContextVar("event_context", default={})


def bind_event_context(**kwargs) -> Token:
    current = dict(_EVENT_CONTEXT.get())
    current.update(kwargs)
    return _EVENT_CONTEXT.set(current)


def get_event_context() -> dict:
    return dict(_EVENT_CONTEXT.get())


def reset_event_context(token: Token):
    _EVENT_CONTEXT.reset(token)
