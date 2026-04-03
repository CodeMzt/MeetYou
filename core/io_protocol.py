"""
统一 I/O 协议数据模型。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


def _new_id() -> str:
    return uuid4().hex


class EventType(str, Enum):
    MESSAGE = "message"
    SIGNAL = "signal"
    CONFIRM_REQUEST = "confirm_request"
    CONFIRM_RESPONSE = "confirm_response"
    HUMAN_INPUT_REQUEST = "human_input_request"
    HUMAN_INPUT_RESPONSE = "human_input_response"
    STATUS = "status"
    REASONING = "reasoning"
    RUNTIME_STATUS = "runtime_status"
    USAGE = "usage"
    CONTROL = "control"
    ERROR = "error"


class SourceKind(str, Enum):
    CLI = "cli"
    HEART = "heart"
    FEISHU = "feishu"
    WEB = "web"
    SYSTEM = "system"


class TargetKind(str, Enum):
    CURRENT_SESSION = "current_session"
    CLI = "cli"
    FEISHU = "feishu"
    WEB = "web"
    BROADCAST = "broadcast"
    INTERNAL = "internal"


class StreamEventType(str, Enum):
    START = "start"
    CHUNK = "chunk"
    END = "end"
    ERROR = "error"


@dataclass(slots=True)
class EventSource:
    kind: str
    id: str = ""
    display_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EventTarget:
    kind: str = TargetKind.CURRENT_SESSION.value
    id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BaseEvent:
    session_id: str
    type: str
    role: str
    content: Any
    source: EventSource
    target: EventTarget = field(default_factory=EventTarget)
    event_id: str = field(default_factory=_new_id)
    stream_id: str = ""
    reply_to: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InboundEvent(BaseEvent):
    pass


@dataclass(slots=True)
class OutboundEvent(BaseEvent):
    pass


@dataclass(slots=True)
class ConfirmRequestEvent(OutboundEvent):
    request_id: str = field(default_factory=_new_id)
    timeout: float = 30.0
    default_decision: bool = False


@dataclass(slots=True)
class ConfirmResponseEvent(InboundEvent):
    request_id: str = ""
    accepted: bool = False


@dataclass(slots=True)
class HumanInputRequestEvent(OutboundEvent):
    request_id: str = field(default_factory=_new_id)
    question: str = ""
    options: list[str] = field(default_factory=list)
    placeholder: str = ""
    timeout: float = 60.0


@dataclass(slots=True)
class HumanInputResponseEvent(InboundEvent):
    request_id: str = ""
    answer_text: str = ""
    selected_option: str | None = None


def event_to_dict(event: BaseEvent) -> dict[str, Any]:
    payload = {
        "event_id": event.event_id,
        "session_id": event.session_id,
        "type": event.type,
        "role": event.role,
        "content": event.content,
        "source": {
            "kind": event.source.kind,
            "id": event.source.id,
            "display_name": event.source.display_name,
            "metadata": dict(event.source.metadata),
        },
        "target": {
            "kind": event.target.kind,
            "id": event.target.id,
            "metadata": dict(event.target.metadata),
        },
        "stream_id": event.stream_id,
        "reply_to": event.reply_to,
        "metadata": dict(event.metadata),
    }
    if isinstance(event, ConfirmRequestEvent):
        payload["confirm"] = {
            "request_id": event.request_id,
            "timeout": event.timeout,
            "default_decision": event.default_decision,
        }
    elif isinstance(event, ConfirmResponseEvent):
        payload["confirm"] = {
            "request_id": event.request_id,
            "accepted": event.accepted,
        }
    elif isinstance(event, HumanInputRequestEvent):
        payload["input_request"] = {
            "request_id": event.request_id,
            "question": event.question,
            "options": list(event.options),
            "placeholder": event.placeholder,
            "timeout": event.timeout,
        }
    elif isinstance(event, HumanInputResponseEvent):
        payload["input_response"] = {
            "request_id": event.request_id,
            "answer_text": event.answer_text,
            "selected_option": event.selected_option,
        }
    return payload


def make_source(kind: str, source_id: str = "", **metadata) -> EventSource:
    return EventSource(kind=kind, id=source_id, metadata=metadata)


def make_target(kind: str = TargetKind.CURRENT_SESSION.value, target_id: str = "", **metadata) -> EventTarget:
    return EventTarget(kind=kind, id=target_id, metadata=metadata)
