"""
统一输出路由器。
"""

from copy import copy
from typing import Protocol

from core.io_protocol import (
    EventSource,
    EventTarget,
    EventType,
    OutboundEvent,
    StreamEventType,
    TargetKind,
)


class OutputAdapter(Protocol):
    async def send(self, event: OutboundEvent): ...


class Speaker:
    """
    负责把统一输出事件路由到具体输出适配器。
    """

    def __init__(self, session_manager):
        self._session_manager = session_manager
        self._adapters: dict[str, list[OutputAdapter]] = {}

    def register_adapter(self, target_kind: str, adapter: OutputAdapter):
        self._adapters.setdefault(target_kind, []).append(adapter)

    def _resolve_targets(self, event: OutboundEvent) -> list[EventTarget]:
        target = event.target
        if target.kind == TargetKind.CURRENT_SESSION.value:
            return [self._session_manager.get_default_target(event.session_id)]
        if target.kind == TargetKind.BROADCAST.value:
            targets = self._session_manager.list_default_targets()
            if targets:
                return targets
            return [EventTarget(kind=kind) for kind in self._adapters]
        return [target]

    async def emit(self, event: OutboundEvent):
        """
        发送事件到所有适配器。
        """
        for target in self._resolve_targets(event):
            for adapter in self._adapters.get(target.kind, []):
                routed = copy(event)
                routed.target = target
                routed.metadata = dict(event.metadata)
                await adapter.send(routed)

    async def emit_text(
        self,
        session_id: str,
        content: str,
        source: EventSource,
        target: EventTarget | None = None,
        stream_id: str = "",
        metadata: dict | None = None,
        stream_channel: str = "",
    ):
        """
        发送文本消息事件。
        """
        payload = dict(metadata or {})
        if stream_channel:
            payload["stream_channel"] = stream_channel
        await self.emit(
            OutboundEvent(
                session_id=session_id,
                type=EventType.MESSAGE.value,
                role="assistant",
                content=content,
                source=source,
                target=target or EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                stream_id=stream_id,
                metadata=payload,
            )
        )

    async def emit_status(
        self,
        session_id: str,
        content: str,
        source: EventSource,
        target: EventTarget | None = None,
        metadata: dict | None = None,
    ):
        """
        发送状态消息事件。
        """
        await self.emit(
            OutboundEvent(
                session_id=session_id,
                type=EventType.STATUS.value,
                role="system",
                content=content,
                source=source,
                target=target or EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                metadata=metadata or {},
            )
        )

    async def emit_error(
        self,
        session_id: str,
        content: str,
        source: EventSource,
        target: EventTarget | None = None,
        stream_id: str = "",
        metadata: dict | None = None,
    ):
        """
        发送错误消息事件。
        """
        payload = dict(metadata or {})
        payload.setdefault("stream_event", StreamEventType.ERROR.value)
        await self.emit(
            OutboundEvent(
                session_id=session_id,
                type=EventType.ERROR.value,
                role="system",
                content=content,
                source=source,
                target=target or EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                stream_id=stream_id,
                metadata=payload,
            )
        )

    async def emit_stream_start(
        self,
        session_id: str,
        source: EventSource,
        target: EventTarget | None = None,
        stream_channel: str = "",
        event_type: str = EventType.MESSAGE.value,
        role: str = "assistant",
    ) -> str:
        """
        发送流开始事件。
        """
        stream_id = self._session_manager.create_stream_id(session_id)
        metadata = {"stream_event": StreamEventType.START.value}
        if stream_channel:
            metadata["stream_channel"] = stream_channel
        await self.emit(
            OutboundEvent(
                session_id=session_id,
                type=event_type,
                role=role,
                content="",
                source=source,
                target=target or EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                stream_id=stream_id,
                metadata=metadata,
            )
        )
        return stream_id

    async def emit_stream_chunk(
        self,
        session_id: str,
        content: str,
        source: EventSource,
        stream_id: str,
        target: EventTarget | None = None,
        stream_channel: str = "",
    ):
        """
        发送流事件的文本块。
        """
        await self.emit_text(
            session_id=session_id,
            content=content,
            source=source,
            target=target,
            stream_id=stream_id,
            metadata={"stream_event": StreamEventType.CHUNK.value},
            stream_channel=stream_channel,
        )

    async def emit_stream_end(
        self,
        session_id: str,
        source: EventSource,
        stream_id: str,
        target: EventTarget | None = None,
        stream_channel: str = "",
        event_type: str = EventType.MESSAGE.value,
        role: str = "assistant",
        metadata: dict | None = None,
    ):
        """
        发送流结束事件。
        """
        payload = {"stream_event": StreamEventType.END.value, **dict(metadata or {})}
        if stream_channel:
            payload["stream_channel"] = stream_channel
        await self.emit(
            OutboundEvent(
                session_id=session_id,
                type=event_type,
                role=role,
                content="",
                source=source,
                target=target or EventTarget(kind=TargetKind.CURRENT_SESSION.value),
                stream_id=stream_id,
                metadata=payload,
            )
        )
        self._session_manager.close_stream(stream_id)
