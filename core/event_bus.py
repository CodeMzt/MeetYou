"""
事件总线：统一输入事件与内部发布订阅。
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from core.io_protocol import (
    ConfirmRequestEvent,
    EventTarget,
    EventType,
    HumanInputRequestEvent,
    TargetKind,
    make_source,
)

logger = logging.getLogger("meetyou.event_bus")


@dataclass(slots=True)
class _PendingRequest:
    request_id: str
    session_id: str
    kind: str
    future: asyncio.Future
    event: Any


class EventBus:
    """
    发布/订阅模式的事件总线。

    事件类型常量定义了系统内所有标准事件。
    模块通过 subscribe() 注册监听，通过 publish() 发布事件。
    """

    # ---- 事件类型常量 ----
    SYSTEM_OUTPUT = "system_output"
    AI_OUTPUT = "ai_output"
    SHUTDOWN = "shutdown"
    ERROR = "error"
    STATUS_CHANGE = "status_change"
    CONFIRM_REQUEST = EventType.CONFIRM_REQUEST.value
    CONFIRM_RESPONSE = EventType.CONFIRM_RESPONSE.value
    HUMAN_INPUT_REQUEST = EventType.HUMAN_INPUT_REQUEST.value
    HUMAN_INPUT_RESPONSE = EventType.HUMAN_INPUT_RESPONSE.value

    def __init__(self):
        self._subscribers: dict[str, list] = defaultdict(list)
        self._shutdown_event = asyncio.Event()
        self._inbound_queue: asyncio.Queue = asyncio.Queue()
        self._pending_requests: dict[str, _PendingRequest] = {}
        self._pending_request_by_session: dict[str, str] = {}

    def _find_pending_request(self, *, kind: str | None = None, session_id: str = "") -> _PendingRequest | None:
        for pending in self._pending_requests.values():
            if kind and pending.kind != kind:
                continue
            if session_id and pending.session_id != session_id:
                continue
            if pending.future.done():
                continue
            return pending
        return None

    def _register_pending_request(
        self,
        *,
        request_id: str,
        session_id: str,
        kind: str,
        future: asyncio.Future,
        event: Any,
    ) -> _PendingRequest:
        existing_request_id = self._pending_request_by_session.get(session_id, "")
        if existing_request_id:
            existing = self._pending_requests.get(existing_request_id)
            if existing is not None and not existing.future.done():
                raise RuntimeError(f"Another interactive request is already pending for session {session_id}")
            self._pending_requests.pop(existing_request_id, None)
        pending = _PendingRequest(
            request_id=request_id,
            session_id=session_id,
            kind=kind,
            future=future,
            event=event,
        )
        self._pending_requests[request_id] = pending
        self._pending_request_by_session[session_id] = request_id
        return pending

    def _clear_pending_request(self, request_id: str):
        pending = self._pending_requests.pop(request_id, None)
        if pending is None:
            return
        session_request_id = self._pending_request_by_session.get(pending.session_id, "")
        if session_request_id == request_id:
            self._pending_request_by_session.pop(pending.session_id, None)

    def _resolve_pending_request(
        self,
        *,
        kind: str,
        value: Any,
        request_id: str = "",
        session_id: str = "",
        publish_event_type: str = "",
        publish_payload: dict[str, Any] | None = None,
    ) -> bool:
        pending: _PendingRequest | None = None
        if request_id:
            pending = self._pending_requests.get(request_id)
        elif session_id:
            pending_request_id = self._pending_request_by_session.get(session_id, "")
            if pending_request_id:
                pending = self._pending_requests.get(pending_request_id)
        else:
            pending = self._find_pending_request(kind=kind)

        if pending is None or pending.kind != kind:
            return False
        if session_id and pending.session_id != session_id:
            return False
        if request_id and pending.request_id != request_id:
            return False
        if pending.future.done():
            self._clear_pending_request(pending.request_id)
            return False

        pending.future.set_result(value)
        if publish_event_type:
            asyncio.create_task(self.publish(publish_event_type, publish_payload or {}))
        return True

    # ---- 核心信号 ----

    @property
    def shutdown_event(self) -> asyncio.Event:
        """全局关闭信号"""
        return self._shutdown_event

    @property
    def inbound_queue(self) -> asyncio.Queue:
        """统一输入事件队列"""
        return self._inbound_queue

    def request_shutdown(self):
        """触发全局关闭"""
        self._shutdown_event.set()
        logger.info("全局关闭信号已触发")

    # ---- 用户确认机制 ----

    async def request_confirmation(
        self,
        prompt: str,
        timeout: float = 30.0,
        session_id: str = "system:confirm",
        source=None,
        target: EventTarget | None = None,
    ) -> bool:
        """
        请求用户确认。

        发布 CONFIRM_REQUEST 事件（由当前输出目标展示给用户），
        然后等待统一输入链路回传确认结果。

        Args:
            prompt: 展示给用户的确认提示文本
            timeout: 等待超时秒数，超时视为拒绝

        Returns:
            bool: 用户是否确认
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        event = ConfirmRequestEvent(
            session_id=session_id,
            type=EventType.CONFIRM_REQUEST.value,
            role="system",
            content=prompt,
            source=source or make_source("system", "confirm"),
            target=target or EventTarget(kind=TargetKind.CURRENT_SESSION.value),
            timeout=timeout,
        )
        self._register_pending_request(
            request_id=event.request_id,
            session_id=event.session_id,
            kind="confirm",
            future=future,
            event=event,
        )
        await self.publish(self.CONFIRM_REQUEST, event)

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.info("User confirmation timed out (%ss), defaulting to reject", timeout)
            return False
        finally:
            self._clear_pending_request(event.request_id)

    def resolve_confirmation(
        self,
        accepted: bool,
        request_id: str = "",
        session_id: str = "",
        client_id: str = "",
        approval_id: str = "",
        reason: str = "",
    ) -> bool:
        """
        由 CLI、前端或飞书输入适配器调用：用户回复了确认请求。

        Args:
            accepted: 用户是否同意
        """
        pending = self._find_pending_request(kind="confirm", session_id=session_id)
        if request_id and pending is None:
            pending = self._pending_requests.get(request_id)
        if pending is None or pending.kind != "confirm":
            return False
        return self._resolve_pending_request(
            kind="confirm",
            value=accepted,
            request_id=request_id or pending.request_id,
            session_id=session_id or pending.session_id,
            publish_event_type=self.CONFIRM_RESPONSE,
            publish_payload={
                "accepted": accepted,
                "request_id": pending.request_id,
                "session_id": pending.session_id,
                "client_id": str(client_id or "").strip(),
                "approval_id": str(approval_id or "").strip(),
                "reason": str(reason or "").strip(),
            },
        )

    def submit_confirmation_response(
        self,
        accepted: bool,
        request_id: str = "",
        session_id: str = "",
        client_id: str = "",
        approval_id: str = "",
        reason: str = "",
    ) -> bool:
        """
        立即处理确认回执。
        用于输入适配器在入口处直接完成确认，避免等待主处理循环再次消费队列。
        """
        return self.resolve_confirmation(
            accepted,
            request_id=request_id,
            session_id=session_id,
            client_id=client_id,
            approval_id=approval_id,
            reason=reason,
        )

    @property
    def has_pending_confirmation(self) -> bool:
        """是否有等待中的确认请求"""
        return self._find_pending_request(kind="confirm") is not None

    @property
    def pending_request_id(self) -> str:
        pending = self._find_pending_request(kind="confirm")
        return pending.request_id if pending is not None else ""

    @property
    def pending_confirmation_session_id(self) -> str:
        pending = self._find_pending_request(kind="confirm")
        return pending.session_id if pending is not None else ""

    async def request_human_input(
        self,
        question: str,
        *,
        options: list[str] | None = None,
        placeholder: str = "",
        timeout: float = 60.0,
        session_id: str = "system:human_input",
        source=None,
        target: EventTarget | None = None,
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        clean_options = [str(item).strip() for item in (options or []) if str(item).strip()]
        event = HumanInputRequestEvent(
            session_id=session_id,
            type=EventType.HUMAN_INPUT_REQUEST.value,
            role="system",
            content=question,
            source=source or make_source("system", "human_input"),
            target=target or EventTarget(kind=TargetKind.CURRENT_SESSION.value),
            question=question,
            options=clean_options,
            placeholder=str(placeholder or "").strip(),
            timeout=timeout,
        )
        self._register_pending_request(
            request_id=event.request_id,
            session_id=event.session_id,
            kind="human_input",
            future=future,
            event=event,
        )
        await self.publish(self.HUMAN_INPUT_REQUEST, event)

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return dict(result or {})
        except asyncio.TimeoutError:
            logger.info("Human input timed out (%ss) for session=%s", timeout, session_id)
            return {
                "answered": False,
                "timed_out": True,
                "selected_option": None,
                "answer_text": "",
                "request_id": event.request_id,
            }
        finally:
            self._clear_pending_request(event.request_id)

    @staticmethod
    def _match_option_from_text(text: str, options: list[str]) -> str | None:
        stripped = text.strip()
        if not stripped or not options:
            return None
        if stripped.isdigit():
            index = int(stripped) - 1
            if 0 <= index < len(options):
                return options[index]
        lowered = stripped.casefold()
        for option in options:
            if lowered == str(option).strip().casefold():
                return option
        return None

    def get_pending_human_input_request(self, session_id: str = "") -> HumanInputRequestEvent | None:
        pending = self._find_pending_request(kind="human_input", session_id=session_id)
        if pending is None or not isinstance(pending.event, HumanInputRequestEvent):
            return None
        return pending.event

    @property
    def has_pending_human_input(self) -> bool:
        return self._find_pending_request(kind="human_input") is not None

    def normalize_human_input_text(self, text: str, session_id: str = "") -> dict[str, Any] | None:
        event = self.get_pending_human_input_request(session_id=session_id)
        if event is None:
            return None
        raw_text = str(text or "").strip()
        selected_option = self._match_option_from_text(raw_text, list(event.options))
        answer_text = selected_option or raw_text
        return {
            "request_id": event.request_id,
            "answer_text": answer_text,
            "selected_option": selected_option,
            "session_id": event.session_id,
        }

    def submit_human_input_response(
        self,
        answer_text: str = "",
        *,
        request_id: str = "",
        session_id: str = "",
        selected_option: str | None = None,
    ) -> bool:
        pending = self.get_pending_human_input_request(session_id=session_id)
        if request_id and (pending is None or pending.request_id != request_id):
            maybe_pending = self._pending_requests.get(request_id)
            if maybe_pending is None or maybe_pending.kind != "human_input":
                return False
            pending = maybe_pending.event if isinstance(maybe_pending.event, HumanInputRequestEvent) else None
        if pending is None:
            return False

        normalized_selected = None
        if selected_option is not None:
            normalized_selected = self._match_option_from_text(str(selected_option), list(pending.options))
            if normalized_selected is None and str(selected_option).strip() in pending.options:
                normalized_selected = str(selected_option).strip()
        if normalized_selected is None:
            normalized_selected = self._match_option_from_text(str(answer_text), list(pending.options))

        final_answer_text = str(answer_text or "").strip()
        if normalized_selected and not final_answer_text:
            final_answer_text = normalized_selected
        if normalized_selected and final_answer_text.isdigit():
            final_answer_text = normalized_selected

        response_payload = {
            "answered": True,
            "timed_out": False,
            "selected_option": normalized_selected,
            "answer_text": final_answer_text,
            "request_id": pending.request_id,
            "session_id": pending.session_id,
        }
        return self._resolve_pending_request(
            kind="human_input",
            value=response_payload,
            request_id=request_id or pending.request_id,
            session_id=session_id or pending.session_id,
            publish_event_type=self.HUMAN_INPUT_RESPONSE,
            publish_payload=response_payload,
        )

    # ---- 发布/订阅 ----

    def subscribe(self, event_type: str, callback):
        """
        订阅事件。

        Args:
            event_type: 事件类型字符串
            callback: 回调函数（支持同步和异步）
        """
        self._subscribers[event_type].append(callback)

    async def publish(self, event_type: str, data=None):
        """
        发布事件，依次通知所有订阅者。

        Args:
            event_type: 事件类型字符串
            data: 要传递给回调的数据
        """
        for callback in self._subscribers[event_type]:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:
                logger.error(f"事件回调异常 [{event_type}]: {e}")
