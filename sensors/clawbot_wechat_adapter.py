from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from adapters.clawbot_client import (
    DEFAULT_CLAWBOT_ILINK_LONG_POLL_TIMEOUT_MS,
    DEFAULT_CLAWBOT_ILINK_REQUEST_TIMEOUT_MS,
    ClawBotClient,
    ClawBotMessage,
    ClawBotSessionExpired,
)
from core.delivery_formatting import markdown_to_plain_text
from core.endpoint_tool_bundles import EXTERNAL_ENDPOINT_BASIC_TOOL_BUNDLE
from core.persistence import atomic_write_json, load_json_with_recovery
from endpoint_providers.runtime_connection import EndpointRuntimeConnection, resolve_core_base_url


logger = logging.getLogger("meetyou.clawbot_wechat")

DEFAULT_STATE_FILE = "user/clawbot_ilink_state.json"
DEFAULT_MAX_TEXT_CHARS = 1800
DEFAULT_REPLY_TIMEOUT_SECONDS = 120
DEFAULT_ERROR_BACKOFF_SECONDS = 2
DEFAULT_MAX_ERROR_BACKOFF_SECONDS = 30
DEFAULT_INBOUND_WORKER_COUNT = 4
DEFAULT_INBOUND_QUEUE_SIZE = 500
DEFAULT_OUTBOUND_MIN_INTERVAL_MS = 250
DEFAULT_STATE_FLUSH_INTERVAL_MS = 500
DEFAULT_GATEWAY_ENDPOINT_IDLE_TTL_SECONDS = 600
MAX_PROCESSED_EVENTS = 4096
CLAWBOT_BASIC_TOOL_BUNDLE = list(EXTERNAL_ENDPOINT_BASIC_TOOL_BUNDLE)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _mask(value: str) -> str:
    text = str(value or "")
    if len(text) <= 8:
        return "***" if text else ""
    return f"{text[:4]}...{text[-4:]}"


def _safe_positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return int(default)
    return number if number > 0 else int(default)


def _hash_suffix(*parts: str, length: int = 20) -> str:
    return hashlib.sha256("\n".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:length]


def conversation_ref(bot_id: str, peer_id: str) -> str:
    return f"{bot_id or 'default'}::{peer_id}"


def split_conversation_ref(value: str) -> tuple[str, str]:
    bot_id, separator, peer_id = str(value or "").partition("::")
    if not separator:
        return "", ""
    return bot_id, peer_id


def split_text_naturally(text: str, *, limit: int = DEFAULT_MAX_TEXT_CHARS) -> list[str]:
    content = str(text or "").strip()
    if not content:
        return []
    max_chars = max(int(limit or DEFAULT_MAX_TEXT_CHARS), 1)
    fragments: list[str] = []
    remaining = content
    separators = ("\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ")
    while len(remaining) > max_chars:
        split_at = -1
        window = remaining[:max_chars]
        for separator in separators:
            index = window.rfind(separator)
            if index > 0:
                split_at = index + len(separator)
                break
        if split_at <= 0:
            split_at = max_chars
        fragment = remaining[:split_at].strip()
        if fragment:
            fragments.append(fragment)
        remaining = remaining[split_at:].strip()
    if remaining:
        fragments.append(remaining)
    return fragments


def _parse_confirm_response(text: str) -> bool | None:
    normalized = str(text or "").strip().lower()
    accepted_tokens = {"y", "yes", "ok", "confirm", "approve", "allow", "true", "确认", "同意", "允许"}
    rejected_tokens = {"n", "no", "reject", "deny", "cancel", "false", "拒绝", "取消", "不同意"}
    if normalized in accepted_tokens:
        return True
    if normalized in rejected_tokens:
        return False
    return None


def _infer_preferred_mode(text: str) -> str | None:
    normalized = str(text or "").strip().lower()
    if any(keyword in normalized for keyword in ("danxi", "fduhole", "webvpn")):
        return "danxi"
    return None


def _message_drop_reason(*, bot_user_id: str = "", message: ClawBotMessage) -> str:
    if message.group_id:
        return "group_message_unsupported"
    if message.message_type == 2:
        return "outbound_or_bot_message"
    if not message.is_complete_text():
        return "not_completed_text"
    if not message.text_content():
        return "empty_text"
    peer_id = message.from_user_id or message.to_user_id
    if not peer_id:
        return "missing_peer_id"
    if not message.context_token:
        return "missing_context_token"
    return ""


@dataclass(slots=True)
class ClawBotWechatEvent:
    bot_id: str
    bot_user_id: str
    peer_id: str
    event_id: str
    message_id: str
    seq: int
    text: str
    context_token: str
    create_time_ms: int = 0
    raw: dict[str, Any] | None = None

    @property
    def conversation_ref(self) -> str:
        return conversation_ref(self.bot_id, self.peer_id)


def event_from_message(*, bot_id: str, bot_user_id: str = "", message: ClawBotMessage) -> ClawBotWechatEvent | None:
    if _message_drop_reason(bot_user_id=bot_user_id, message=message):
        return None
    text = message.text_content()
    peer_id = message.from_user_id or message.to_user_id
    identity_seed = "\n".join(
        [
            str(bot_id or "default"),
            str(message.message_id or ""),
            str(message.seq or ""),
            str(message.create_time_ms or ""),
            peer_id,
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
        ]
    )
    event_id = f"clawbot:{hashlib.sha256(identity_seed.encode('utf-8')).hexdigest()[:32]}"
    return ClawBotWechatEvent(
        bot_id=bot_id or "default",
        bot_user_id=bot_user_id,
        peer_id=peer_id,
        event_id=event_id,
        message_id=message.message_id,
        seq=message.seq,
        text=text,
        context_token=message.context_token,
        create_time_ms=message.create_time_ms,
        raw=dict(message.raw or {}),
    )


class ClawBotWechatStateStore:
    def __init__(self, state_file: str = DEFAULT_STATE_FILE, *, flush_interval_ms: int = 0):
        self.path = Path(state_file or DEFAULT_STATE_FILE)
        self._lock = asyncio.Lock()
        self._payload = self._load()
        self._flush_interval_seconds = max(int(flush_interval_ms or 0), 0) / 1000
        self._flush_task: asyncio.Task | None = None

    def _empty_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "ilink": {},
            "conversations": {},
            "processed_events": {},
            "updated_at": "",
        }

    def _load(self) -> dict[str, Any]:
        payload = load_json_with_recovery(
            str(self.path),
            validator=lambda item: isinstance(item, dict),
            default_factory=self._empty_payload,
        )
        for key, default in (("ilink", {}), ("conversations", {}), ("processed_events", {})):
            if not isinstance(payload.get(key), dict):
                payload[key] = default
        return payload

    async def _persist_locked(self, *, force: bool = False) -> None:
        if force or self._flush_interval_seconds <= 0:
            if self._flush_task is not None:
                self._flush_task.cancel()
                self._flush_task = None
            self._persist_now_locked()
            return
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_after_delay())

    def _persist_now_locked(self) -> None:
        processed = self._payload.setdefault("processed_events", {})
        if isinstance(processed, dict) and len(processed) > MAX_PROCESSED_EVENTS:
            ordered = sorted(processed.items(), key=lambda item: str((item[1] or {}).get("updated_at") or ""))
            self._payload["processed_events"] = dict(ordered[-MAX_PROCESSED_EVENTS:])
        self._payload["updated_at"] = _utcnow_iso()
        atomic_write_json(str(self.path), self._payload)

    async def _flush_after_delay(self) -> None:
        try:
            await asyncio.sleep(self._flush_interval_seconds)
            async with self._lock:
                self._flush_task = None
                self._persist_now_locked()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("ClawBot iLink state flush failed: %s", exc)

    async def flush(self) -> None:
        task = self._flush_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        async with self._lock:
            self._flush_task = None
            self._persist_now_locked()

    async def close(self) -> None:
        await self.flush()

    def get_updates_buf(self) -> str:
        return str(self._payload.get("ilink", {}).get("get_updates_buf") or "")

    def get_longpolling_timeout_ms(self, default: int) -> int:
        return _safe_positive_int(self._payload.get("ilink", {}).get("longpolling_timeout_ms"), default)

    async def set_cursor(self, *, get_updates_buf: str, longpolling_timeout_ms: int = 0) -> None:
        async with self._lock:
            ilink = self._payload.setdefault("ilink", {})
            if str(get_updates_buf or ""):
                ilink["get_updates_buf"] = str(get_updates_buf or "")
            if longpolling_timeout_ms > 0:
                ilink["longpolling_timeout_ms"] = int(longpolling_timeout_ms)
            ilink["updated_at"] = _utcnow_iso()
            await self._persist_locked()

    async def clear_cursor(self, *, reason: str = "") -> None:
        async with self._lock:
            self._payload["ilink"] = {"cleared_at": _utcnow_iso(), "reason": str(reason or "")}
            await self._persist_locked(force=True)

    async def remember_context(self, event: ClawBotWechatEvent) -> None:
        async with self._lock:
            record = self._payload.setdefault("conversations", {}).setdefault(event.conversation_ref, {})
            record.update(
                {
                    "bot_id": event.bot_id,
                    "bot_user_id": event.bot_user_id,
                    "peer_id": event.peer_id,
                    "context_token": event.context_token,
                    "last_message_id": event.message_id,
                    "last_event_id": event.event_id,
                    "updated_at": _utcnow_iso(),
                }
            )
            await self._persist_locked()

    def get_context_token(self, bot_id: str, peer_id: str) -> str:
        record = self._payload.get("conversations", {}).get(conversation_ref(bot_id, peer_id), {})
        return str(record.get("context_token") or "")

    def get_thread_id(self, ref: str) -> str:
        record = self._payload.get("conversations", {}).get(str(ref or ""), {})
        return str(record.get("thread_id") or "")

    async def set_thread_id(self, ref: str, thread_id: str) -> None:
        if not ref or not thread_id:
            return
        async with self._lock:
            record = self._payload.setdefault("conversations", {}).setdefault(ref, {})
            record["thread_id"] = str(thread_id or "")
            record["updated_at"] = _utcnow_iso()
            await self._persist_locked()

    def event_status(self, event_id: str) -> str:
        record = self._payload.get("processed_events", {}).get(str(event_id or ""), {})
        return str(record.get("status") or "")

    async def mark_event_status(self, event: ClawBotWechatEvent, status: str, *, reason: str = "", core_message_id: str = "") -> None:
        async with self._lock:
            self._payload.setdefault("processed_events", {})[event.event_id] = {
                "status": str(status or ""),
                "reason": str(reason or ""),
                "bot_id": event.bot_id,
                "peer_id": event.peer_id,
                "message_id": event.message_id,
                "core_message_id": str(core_message_id or ""),
                "updated_at": _utcnow_iso(),
            }
            await self._persist_locked()

    def list_address_records(self) -> list[dict[str, str]]:
        records: list[dict[str, str]] = []
        for ref, payload in (self._payload.get("conversations") or {}).items():
            if not isinstance(payload, dict):
                continue
            bot_id = str(payload.get("bot_id") or "")
            peer_id = str(payload.get("peer_id") or "")
            if bot_id and peer_id:
                records.append({"conversation_ref": str(ref), "bot_id": bot_id, "peer_id": peer_id})
        return records


@dataclass(slots=True)
class _PendingReply:
    event: ClawBotWechatEvent
    allow_send: bool
    future: asyncio.Future


class ClawBotWechatOutputService:
    def __init__(
        self,
        *,
        config,
        client: ClawBotClient,
        state_store: ClawBotWechatStateStore,
        delivery_result_sender: Callable[..., Any] | None = None,
        sleeper: Callable[[float], Any] = asyncio.sleep,
    ):
        self._config = config
        self._client = client
        self._state_store = state_store
        self._delivery_result_sender = delivery_result_sender
        self._sleeper = sleeper
        self._pending_replies: dict[str, _PendingReply] = {}
        self._pending_confirm_requests: dict[str, str] = {}
        self._pending_human_input_requests: dict[str, dict[str, Any]] = {}
        self._stream_buffers: dict[str, list[str]] = {}
        self._sent_final_keys: set[str] = set()
        self._send_lock = asyncio.Lock()
        self._last_send_at = 0.0

    def set_delivery_result_sender(self, sender: Callable[..., Any] | None) -> None:
        self._delivery_result_sender = sender

    async def close(self) -> None:
        for pending in list(self._pending_replies.values()):
            if not pending.future.done():
                pending.future.cancel()
        self._pending_replies.clear()

    def begin_event(self, event: ClawBotWechatEvent, *, allow_send: bool) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        previous = self._pending_replies.get(event.conversation_ref)
        if previous is not None and not previous.future.done():
            previous.future.cancel()
        self._pending_replies[event.conversation_ref] = _PendingReply(event=event, allow_send=allow_send, future=future)
        return future

    def discard_pending(self, event: ClawBotWechatEvent) -> None:
        pending = self._pending_replies.get(event.conversation_ref)
        if pending is None or pending.event.event_id != event.event_id:
            return
        self._pending_replies.pop(event.conversation_ref, None)
        if not pending.future.done():
            pending.future.cancel()

    def get_pending_confirm_request(self, ref: str) -> str | None:
        return self._pending_confirm_requests.get(ref)

    def clear_pending_confirm_request(self, ref: str, request_id: str = "") -> None:
        current = self._pending_confirm_requests.get(ref)
        if current and (not request_id or request_id == current):
            self._pending_confirm_requests.pop(ref, None)

    def resolve_human_input(self, ref: str, raw_text: str) -> dict[str, Any] | None:
        payload = self._pending_human_input_requests.pop(ref, None)
        if payload is None:
            return None
        text = str(raw_text or "").strip()
        options = [str(item).strip() for item in payload.get("options", []) if str(item).strip()]
        selected_option = None
        if text.isdigit():
            index = int(text)
            if 1 <= index <= len(options):
                selected_option = options[index - 1]
        if selected_option is None and text in options:
            selected_option = text
        return {
            "request_id": payload.get("request_id", ""),
            "answer_text": selected_option or text,
            "selected_option": selected_option,
        }

    async def send_runtime_event(self, ref: str, payload: dict[str, Any]) -> None:
        if payload.get("schema") != "meetyou.endpoint.ws.v4":
            return
        frame_type = str(payload.get("type") or "")
        body_payload = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
        delivery_id = str(body_payload.get("delivery_id") or payload.get("delivery_id") or "").strip()
        target_ref = str(body_payload.get("target_external_ref") or "").strip()
        if target_ref:
            if ref and ref != target_ref:
                return
            ref = target_ref
        if not ref and frame_type.startswith("delivery."):
            return
        pending = self._pending_replies.get(ref)
        if frame_type == "endpoint.error":
            logger.warning("ClawBot iLink endpoint websocket error target=%s payload=%s", _mask(ref), body_payload)
            self._complete_pending(ref, False, "endpoint websocket error")
            return
        if frame_type == "delivery.notice":
            notice = body_payload
            text = str(notice.get("content") or notice.get("text") or "").strip()
            if not text and isinstance(notice.get("message"), dict):
                text = str(notice["message"].get("content") or "").strip()
            await self._handle_outbound_text(ref, text, pending=pending, delivery_id=delivery_id, frame_type=frame_type, complete_pending=False)
            return
        if frame_type == "delivery.message":
            message = body_payload
            role = str(message.get("role") or "").strip().lower()
            if role and role != "assistant":
                return
            text = str(message.get("content") or "").strip()
            message_id = str(message.get("message_id") or "")
            if not self._remember_final_delivery(ref, message_id=message_id, stream_key=""):
                return
            logger.info(
                "ClawBot iLink received Core delivery.message target=%s delivery=%s message=%s chars=%d",
                _mask(ref),
                _mask(delivery_id),
                _mask(message_id),
                len(text),
            )
            await self._handle_outbound_text(ref, text, pending=pending, delivery_id=delivery_id, frame_type=frame_type, complete_pending=True)
            return
        if frame_type != "delivery.run_event":
            return
        event = body_payload
        event_type = str(event.get("type") or "")
        body = event.get("payload") if isinstance(event.get("payload"), dict) else event
        stream_id = str(event.get("stream_id") or "")
        stream_key = f"{ref}:{stream_id}" if stream_id else ""
        if event_type == "confirm.requested":
            if pending is not None:
                request_id = str(body.get("request_id") or "")
                self._pending_confirm_requests[ref] = request_id
                text = f"{body.get('content', '')}\n确认编号: {request_id}\n请回复 y/yes/确认 或 n/no/拒绝。"
                await self._handle_outbound_text(ref, text, pending=pending, delivery_id=delivery_id, frame_type=frame_type, complete_pending=False)
            return
        if event_type == "confirm.resolved":
            request_id = str(body.get("request_id") or "")
            if not request_id or self._pending_confirm_requests.get(ref) == request_id:
                self._pending_confirm_requests.pop(ref, None)
            return
        if event_type == "human_input.requested":
            if pending is not None:
                request_id = str(body.get("request_id") or "")
                options = [str(item).strip() for item in body.get("options", []) if str(item).strip()]
                self._pending_human_input_requests[ref] = {"request_id": request_id, "options": options}
                option_lines = "\n".join(f"{index}. {option}" for index, option in enumerate(options, start=1))
                suffix = f"\n{option_lines}" if option_lines else ""
                text = f"{body.get('question', '')}{suffix}\n请回复编号或直接输入内容。\n请求编号: {request_id}"
                await self._handle_outbound_text(ref, text, pending=pending, delivery_id=delivery_id, frame_type=frame_type, complete_pending=False)
            return
        if event_type == "human_input.resolved":
            request_id = str(body.get("request_id") or "")
            current = self._pending_human_input_requests.get(ref, {})
            if not request_id or current.get("request_id") == request_id:
                self._pending_human_input_requests.pop(ref, None)
            return
        if event_type == "assistant.progress_notice":
            text = str(body.get("content") or body.get("text") or "").strip()
            await self._handle_outbound_text(ref, text, pending=pending, delivery_id=delivery_id, frame_type=frame_type, complete_pending=False)
            return
        if event_type in {"reasoning.delta", "operation.updated", "activity.status"}:
            return
        if event_type == "message.delta":
            if str(body.get("channel") or "") in {"", "answer"} and stream_key:
                self._stream_buffers.setdefault(stream_key, []).append(str(body.get("delta") or body.get("content") or ""))
            return
        if event_type == "message.completed":
            message = body.get("message", {}) if isinstance(body.get("message"), dict) else body
            buffered = "".join(self._stream_buffers.pop(stream_key, [])) if stream_key else ""
            text = str(message.get("content") or "").strip() or buffered
            message_id = str(message.get("message_id") or "")
            if not self._remember_final_delivery(ref, message_id=message_id, stream_key=stream_key):
                return
            logger.info(
                "ClawBot iLink received Core message.completed target=%s delivery=%s message=%s chars=%d",
                _mask(ref),
                _mask(delivery_id),
                _mask(message_id),
                len(text),
            )
            await self._handle_outbound_text(ref, text, pending=pending, delivery_id=delivery_id, frame_type=frame_type, complete_pending=True)

    async def _handle_outbound_text(
        self,
        ref: str,
        text: str,
        *,
        pending: _PendingReply | None,
        delivery_id: str,
        frame_type: str,
        complete_pending: bool,
    ) -> None:
        content = markdown_to_plain_text(text)
        if not content:
            if pending is not None and complete_pending:
                self._complete_pending(ref, True)
            return
        if pending is not None and not pending.allow_send:
            if complete_pending:
                self._complete_pending(ref, True)
            return
        try:
            await self._send_direct_text(ref, content)
            logger.info(
                "ClawBot iLink sent outbound text target=%s delivery=%s frame=%s chars=%d",
                _mask(ref),
                _mask(delivery_id),
                frame_type,
                len(content),
            )
            if pending is not None and complete_pending:
                self._complete_pending(ref, True)
            await self._report_delivery_result(
                delivery_id,
                status="sent",
                metadata={"provider_type": "wechat", "transport": "clawbot_ilink", "target": _mask(ref), "frame_type": frame_type},
            )
        except Exception as exc:
            if pending is not None and complete_pending:
                self._complete_pending(ref, False, f"{exc.__class__.__name__}: {exc}")
            await self._report_delivery_result(
                delivery_id,
                status="failed",
                error={"message": str(exc), "type": exc.__class__.__name__},
                metadata={"provider_type": "wechat", "transport": "clawbot_ilink", "target": _mask(ref), "frame_type": frame_type},
            )
            logger.warning("ClawBot iLink send failed target=%s error=%s", _mask(ref), exc)

    def _complete_pending(self, ref: str, ok: bool, detail: str = "", *, terminal: bool = False) -> None:
        pending = self._pending_replies.pop(ref, None)
        if pending is None or pending.future.done():
            return
        pending.future.set_result({"ok": ok, "detail": detail, "terminal": bool(terminal)})

    def _remember_final_delivery(self, ref: str, *, message_id: str = "", stream_key: str = "") -> bool:
        key = str(message_id or stream_key or "").strip()
        if not key:
            return True
        scoped = f"{ref}:{key}"
        if scoped in self._sent_final_keys:
            return False
        if len(self._sent_final_keys) > 4096:
            self._sent_final_keys.clear()
        self._sent_final_keys.add(scoped)
        return True

    async def _send_direct_text(self, ref: str, text: str) -> None:
        bot_id, peer_id = split_conversation_ref(ref)
        if not bot_id or not peer_id:
            raise RuntimeError("missing ClawBot iLink bot or peer id")
        context_token = self._state_store.get_context_token(bot_id, peer_id)
        if not context_token:
            raise RuntimeError("ClawBot iLink context_token is not available for this conversation")
        limit = _safe_positive_int(self._config.get("clawbot_ilink_max_text_chars"), DEFAULT_MAX_TEXT_CHARS)
        fragments = split_text_naturally(markdown_to_plain_text(text), limit=limit)
        for index, fragment in enumerate(fragments, start=1):
            await self._wait_global_send_slot()
            logger.info(
                "ClawBot iLink sendmessage target=%s fragment=%d/%d chars=%d",
                _mask(ref),
                index,
                len(fragments),
                len(fragment),
            )
            await self._client.send_text(
                to_user_id=peer_id,
                context_token=context_token,
                text=fragment,
                timeout_ms=_safe_positive_int(
                    self._config.get("clawbot_ilink_send_timeout_ms"),
                    DEFAULT_CLAWBOT_ILINK_REQUEST_TIMEOUT_MS,
                ),
            )
            if index < len(fragments):
                await self._sleep(0.8)

    async def _wait_global_send_slot(self) -> None:
        min_interval = _safe_positive_int(
            self._config.get("clawbot_ilink_outbound_min_interval_ms"),
            DEFAULT_OUTBOUND_MIN_INTERVAL_MS,
        ) / 1000
        async with self._send_lock:
            now = asyncio.get_running_loop().time()
            delay = min_interval - (now - self._last_send_at)
            if delay > 0:
                await self._sleep(delay)
            self._last_send_at = asyncio.get_running_loop().time()

    async def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        result = self._sleeper(seconds)
        if asyncio.iscoroutine(result):
            await result

    async def _report_delivery_result(
        self,
        delivery_id: str,
        *,
        status: str,
        error: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not delivery_id or self._delivery_result_sender is None:
            return
        try:
            result = self._delivery_result_sender(
                delivery_id=delivery_id,
                status=status,
                error=dict(error or {}),
                metadata=dict(metadata or {}),
            )
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.warning("ClawBot iLink delivery result report failed delivery=%s error=%s", _mask(delivery_id), exc)


class ClawBotWechatInputAdapter:
    def __init__(
        self,
        event_bus,
        session_manager,
        config,
        *,
        client: ClawBotClient | None = None,
        state_store: ClawBotWechatStateStore | None = None,
        output_adapter: ClawBotWechatOutputService | None = None,
        endpoint_connection_factory: Callable[..., Any] = EndpointRuntimeConnection,
    ):
        del event_bus, session_manager
        self._config = config
        self._endpoint_connection_factory = endpoint_connection_factory
        self._client = client or ClawBotClient(
            base_url=str(config.get("clawbot_ilink_base_url") or ""),
            bot_token=str(config.get("clawbot_ilink_bot_token") or ""),
            bot_id=str(config.get("clawbot_ilink_bot_id") or ""),
            ilink_user_id=str(config.get("clawbot_ilink_user_id") or ""),
            channel_version=str(config.get("clawbot_ilink_channel_version") or ""),
            ilink_app_client_version=str(config.get("clawbot_ilink_app_client_version") or ""),
            route_tag=str(config.get("clawbot_ilink_route_tag") or ""),
            request_timeout_ms=_safe_positive_int(
                config.get("clawbot_ilink_send_timeout_ms"),
                DEFAULT_CLAWBOT_ILINK_REQUEST_TIMEOUT_MS,
            ),
            long_poll_timeout_ms=_safe_positive_int(
                config.get("clawbot_ilink_poll_timeout_ms"),
                DEFAULT_CLAWBOT_ILINK_LONG_POLL_TIMEOUT_MS,
            ),
        )
        self._state_store = state_store or ClawBotWechatStateStore(
            str(config.get("clawbot_ilink_state_file") or DEFAULT_STATE_FILE),
            flush_interval_ms=_safe_positive_int(
                config.get("clawbot_ilink_state_flush_interval_ms"),
                DEFAULT_STATE_FLUSH_INTERVAL_MS,
            ),
        )
        self._output_adapter = output_adapter or ClawBotWechatOutputService(
            config=config,
            client=self._client,
            state_store=self._state_store,
        )
        self._output_adapter.set_delivery_result_sender(self._send_delivery_result)
        self._provider_endpoint_connection: Any | None = None
        self._endpoint_connections: dict[str, Any] = {}
        self._endpoint_connection_last_used: dict[str, float] = {}
        self._last_empty_poll_log_at = 0.0
        self._gateway_endpoint_idle_ttl_seconds = _safe_positive_int(
            config.get("clawbot_ilink_gateway_endpoint_idle_ttl_seconds"),
            DEFAULT_GATEWAY_ENDPOINT_IDLE_TTL_SECONDS,
        )
        self._poll_task: asyncio.Task | None = None
        self._closed = False
        self._inbound_worker_count = _safe_positive_int(
            config.get("clawbot_ilink_inbound_worker_count"),
            DEFAULT_INBOUND_WORKER_COUNT,
        )
        self._inbound_queue: asyncio.Queue[ClawBotWechatEvent] = asyncio.Queue(
            maxsize=_safe_positive_int(
                config.get("clawbot_ilink_inbound_queue_size"),
                DEFAULT_INBOUND_QUEUE_SIZE,
            )
        )
        self._inbound_workers: list[asyncio.Task] = []
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._core_base_url = resolve_core_base_url(config)
        self._core_access_token = str(config.get("gateway_access_token") or config.get("client_access_token") or "").strip()

    @property
    def _provider_endpoint_id(self) -> str:
        return "wechat.clawbot.provider.ui"

    @property
    def _bot_id(self) -> str:
        return str(self._client.bot_id or self._config.get("clawbot_ilink_bot_id") or "clawbot").strip() or "clawbot"

    @property
    def _bot_user_id(self) -> str:
        return str(self._client.ilink_user_id or self._config.get("clawbot_ilink_user_id") or "").strip()

    async def run(self) -> None:
        self._closed = False
        await self._client.init()
        await self._get_provider_endpoint_connection()
        self._ensure_inbound_workers()
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._run_poll_loop())
        logger.info("ClawBot iLink Endpoint Provider started")

    async def close(self) -> None:
        self._closed = True
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        await self._stop_inbound_workers()
        for connection in self._endpoint_connections.values():
            close = getattr(connection, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    await close()
        self._endpoint_connections.clear()
        if self._provider_endpoint_connection is not None:
            close = getattr(self._provider_endpoint_connection, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    await close()
            self._provider_endpoint_connection = None
        await self._output_adapter.close()
        await self._state_store.close()
        await self._client.close()

    async def _run_poll_loop(self) -> None:
        backoff_seconds = DEFAULT_ERROR_BACKOFF_SECONDS
        while not self._closed:
            try:
                timeout_ms = self._state_store.get_longpolling_timeout_ms(
                    _safe_positive_int(
                        self._config.get("clawbot_ilink_poll_timeout_ms"),
                        DEFAULT_CLAWBOT_ILINK_LONG_POLL_TIMEOUT_MS,
                    )
                )
                result = await self._client.get_updates(
                    get_updates_buf=self._state_store.get_updates_buf(),
                    timeout_ms=timeout_ms,
                )
                events: list[ClawBotWechatEvent] = []
                drop_counts: dict[str, int] = {}
                for message in result.messages:
                    event = event_from_message(bot_id=self._bot_id, bot_user_id=self._bot_user_id, message=message)
                    if event is None:
                        reason = _message_drop_reason(bot_user_id=self._bot_user_id, message=message) or "unknown"
                        drop_counts[reason] = drop_counts.get(reason, 0) + 1
                        continue
                    events.append(event)
                if result.messages or events or drop_counts:
                    logger.info(
                        "ClawBot iLink getupdates messages=%d accepted=%d dropped=%d reasons=%s cursor_present=%s",
                        len(result.messages),
                        len(events),
                        sum(drop_counts.values()),
                        drop_counts,
                        bool(result.get_updates_buf),
                    )
                elif asyncio.get_running_loop().time() - self._last_empty_poll_log_at >= 60:
                    self._last_empty_poll_log_at = asyncio.get_running_loop().time()
                    logger.info(
                        "ClawBot iLink polling alive messages=0 cursor_present=%s timeout_ms=%d",
                        bool(result.get_updates_buf),
                        timeout_ms,
                    )
                if events:
                    await self.handle_events(events)
                await self._state_store.set_cursor(
                    get_updates_buf=result.get_updates_buf,
                    longpolling_timeout_ms=result.longpolling_timeout_ms,
                )
                backoff_seconds = DEFAULT_ERROR_BACKOFF_SECONDS
                await self._close_idle_endpoint_connections()
            except asyncio.CancelledError:
                raise
            except ClawBotSessionExpired as exc:
                logger.error("ClawBot iLink session expired. Run `python -m endpoint_providers.clawbot login` again: %s", exc)
                await self._state_store.clear_cursor(reason="session_expired")
                await asyncio.sleep(DEFAULT_MAX_ERROR_BACKOFF_SECONDS)
            except asyncio.TimeoutError:
                logger.info("ClawBot iLink getupdates timed out after %d ms; continuing.", timeout_ms)
            except Exception as exc:
                logger.warning("ClawBot iLink polling failed: %s", exc)
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, DEFAULT_MAX_ERROR_BACKOFF_SECONDS)

    async def handle_events(self, events: list[ClawBotWechatEvent]) -> None:
        self._ensure_inbound_workers()
        for event in events:
            await self._inbound_queue.put(event)
        await self._inbound_queue.join()

    def _ensure_inbound_workers(self) -> None:
        self._inbound_workers = [worker for worker in self._inbound_workers if not worker.done()]
        while len(self._inbound_workers) < self._inbound_worker_count:
            self._inbound_workers.append(asyncio.create_task(self._run_inbound_worker()))

    async def _stop_inbound_workers(self) -> None:
        for worker in self._inbound_workers:
            worker.cancel()
        for worker in self._inbound_workers:
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        self._inbound_workers.clear()

    async def _run_inbound_worker(self) -> None:
        while not self._closed:
            event = await self._inbound_queue.get()
            try:
                lock = self._conversation_locks.setdefault(event.conversation_ref, asyncio.Lock())
                async with lock:
                    await self._handle_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("ClawBot iLink inbound worker failed target=%s error=%s", _mask(event.conversation_ref), exc)
            finally:
                self._inbound_queue.task_done()

    async def _handle_event(self, event: ClawBotWechatEvent) -> None:
        status = self._state_store.event_status(event.event_id)
        if status in {"sent", "submitted", "skipped", "read_only", "failed"}:
            logger.info(
                "ClawBot iLink inbound event already processed target=%s event=%s status=%s",
                _mask(event.conversation_ref),
                _mask(event.event_id),
                status,
            )
            return
        await self._state_store.remember_context(event)
        ref = event.conversation_ref
        logger.info(
            "ClawBot iLink inbound event target=%s event=%s text_chars=%d",
            _mask(ref),
            _mask(event.event_id),
            len(event.text),
        )
        confirm_value = _parse_confirm_response(event.text)
        pending_confirm = self._output_adapter.get_pending_confirm_request(ref)
        if confirm_value is not None and pending_confirm:
            client = await self._get_endpoint_connection(event)
            await self._submit_confirm(client, pending_confirm, confirm_value, event)
            self._output_adapter.clear_pending_confirm_request(ref, pending_confirm)
            await self._state_store.mark_event_status(event, "sent")
            return
        pending_human_input = self._output_adapter.resolve_human_input(ref, event.text)
        if pending_human_input is not None:
            client = await self._get_endpoint_connection(event)
            await self._submit_human_input(client, pending_human_input, event)
            await self._state_store.mark_event_status(event, "sent")
            return
        await self._state_store.mark_event_status(event, "processing")
        client = await self._get_endpoint_connection(event)
        with contextlib.suppress(Exception):
            await client.upsert_address(self._address_payload(bot_id=event.bot_id, peer_id=event.peer_id))
        future = self._output_adapter.begin_event(event, allow_send=True)
        try:
            message_response = await client.send_message(
                event.text,
                metadata=self._metadata_for(event),
                preferred_mode=_infer_preferred_mode(event.text),
                endpoint_message_id=event.event_id,
            )
            await self._remember_endpoint_connection_thread(event, client)
            logger.info(
                "ClawBot iLink submitted event to Core target=%s event=%s core_message=%s thread=%s session=%s",
                _mask(ref),
                _mask(event.event_id),
                _mask(str((message_response or {}).get("message_id") or "")),
                _mask(str(getattr(client, "thread_id", "") or "")),
                _mask(str(getattr(client, "session_id", "") or "")),
            )
        except Exception as exc:
            self._output_adapter.discard_pending(event)
            logger.warning(
                "ClawBot iLink Core bridge failed target=%s event=%s error=%s:%s",
                _mask(ref),
                _mask(event.event_id),
                exc.__class__.__name__,
                exc,
            )
            await self._state_store.mark_event_status(event, "failed", reason=f"bridge:{exc.__class__.__name__}")
            return
        core_message_id = str((message_response or {}).get("message_id") or "")
        if bool((message_response or {}).get("idempotent_replay")):
            self._output_adapter.discard_pending(event)
            await self._state_store.mark_event_status(event, "submitted", reason="core_idempotent_replay", core_message_id=core_message_id)
            return
        try:
            result = await asyncio.wait_for(
                future,
                timeout=_safe_positive_int(
                    self._config.get("clawbot_ilink_reply_timeout_seconds"),
                    DEFAULT_REPLY_TIMEOUT_SECONDS,
                ),
            )
        except Exception as exc:
            self._output_adapter.discard_pending(event)
            logger.warning("ClawBot iLink reply wait failed target=%s event=%s error=%s", _mask(ref), _mask(event.event_id), exc)
            await self._state_store.mark_event_status(event, "submitted", reason=f"reply:{exc.__class__.__name__}", core_message_id=core_message_id)
            return
        if not bool(result.get("ok")):
            logger.warning(
                "ClawBot iLink Core reply did not send target=%s event=%s detail=%s",
                _mask(ref),
                _mask(event.event_id),
                result.get("detail"),
            )
            await self._state_store.mark_event_status(
                event,
                "submitted",
                reason=str(result.get("detail") or "reply_failed"),
                core_message_id=core_message_id,
            )
            return
        logger.info("ClawBot iLink event completed target=%s event=%s", _mask(ref), _mask(event.event_id))
        await self._state_store.mark_event_status(event, "sent", core_message_id=core_message_id)

    def _conversation_key(self, event: ClawBotWechatEvent) -> str:
        return f"wechat:clawbot:direct:{event.bot_id}:{event.peer_id}"

    def _address_payload(self, *, bot_id: str, peer_id: str) -> dict[str, Any]:
        ref = conversation_ref(bot_id, peer_id)
        digest = _hash_suffix(bot_id, peer_id, length=24)
        return {
            "address_id": f"addr.wechat.direct.{digest}",
            "provider_type": "wechat",
            "address_type": "direct",
            "external_ref": ref,
            "display_name": f"WeChat direct {_mask(peer_id)}",
            "workspace_ids": ["personal"],
            "status": "sendable",
            "capabilities": ["send_text"],
            "metadata": {
                "transport": "clawbot_ilink",
                "bot_id": bot_id,
                "peer_id_present": bool(peer_id),
            },
        }

    async def _discover_address_snapshot(self) -> list[dict[str, Any]]:
        return [
            self._address_payload(bot_id=record["bot_id"], peer_id=record["peer_id"])
            for record in self._state_store.list_address_records()
        ]

    async def _get_provider_endpoint_connection(self) -> Any:
        if self._provider_endpoint_connection is None:
            self._provider_endpoint_connection = self._endpoint_connection_factory(
                base_url=self._core_base_url,
                provider_id="clawbot-wechat-provider",
                provider_type="wechat",
                display_name="ClawBot iLink WeChat Provider",
                workspace_id="personal",
                access_token=self._core_access_token,
                thread_title="ClawBot iLink WeChat Provider",
                endpoint_id=self._provider_endpoint_id,
                endpoint_addresses=await self._discover_address_snapshot(),
                supports_markdown=False,
                bind_thread=False,
                event_handler=lambda payload: self._output_adapter.send_runtime_event("", payload),
            )
        await self._provider_endpoint_connection.start()
        return self._provider_endpoint_connection

    async def _get_endpoint_connection(self, event: ClawBotWechatEvent) -> Any:
        ref = event.conversation_ref
        client = self._endpoint_connections.get(ref)
        if client is None:
            thread_id = self._state_store.get_thread_id(ref)
            digest = _hash_suffix(ref, length=20)
            client = self._endpoint_connection_factory(
                base_url=self._core_base_url,
                provider_id=f"clawbot-wechat-{digest}",
                provider_type="wechat",
                display_name=f"ClawBot WeChat {_mask(event.peer_id)}",
                workspace_id="personal",
                access_token=self._core_access_token,
                thread_title=f"WeChat {_mask(event.peer_id)}",
                thread_id=thread_id,
                endpoint_id=self._provider_endpoint_id,
                conversation_key=self._conversation_key(event),
                address_id=self._address_payload(bot_id=event.bot_id, peer_id=event.peer_id).get("address_id", ""),
                thread_strategy="per_conversation",
                supports_markdown=False,
                event_handler=lambda payload, ref=ref: self._output_adapter.send_runtime_event(ref, payload),
            )
            self._endpoint_connections[ref] = client
        await client.start()
        self._endpoint_connection_last_used[ref] = asyncio.get_running_loop().time()
        thread_id = str(getattr(client, "thread_id", "") or "")
        if thread_id:
            await self._state_store.set_thread_id(ref, thread_id)
        logger.info(
            "ClawBot iLink Core endpoint session ready target=%s thread=%s session=%s",
            _mask(ref),
            _mask(thread_id),
            _mask(str(getattr(client, "session_id", "") or "")),
        )
        return client

    async def _close_idle_endpoint_connections(self) -> None:
        if self._gateway_endpoint_idle_ttl_seconds <= 0 or not self._endpoint_connections:
            return
        now = asyncio.get_running_loop().time()
        stale_refs = [
            ref
            for ref, last_used in self._endpoint_connection_last_used.items()
            if now - float(last_used or 0) >= self._gateway_endpoint_idle_ttl_seconds
        ]
        for ref in stale_refs:
            client = self._endpoint_connections.pop(ref, None)
            self._endpoint_connection_last_used.pop(ref, None)
            if client is None:
                continue
            close = getattr(client, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    await close()

    async def _remember_endpoint_connection_thread(self, event: ClawBotWechatEvent, client: Any) -> None:
        thread_id = str(getattr(client, "thread_id", "") or "")
        if thread_id:
            await self._state_store.set_thread_id(event.conversation_ref, thread_id)

    async def _send_delivery_result(
        self,
        *,
        delivery_id: str,
        status: str,
        error: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        connection = await self._get_provider_endpoint_connection()
        sender = getattr(connection, "send_delivery_result", None)
        if callable(sender):
            result = sender(
                delivery_id=delivery_id,
                status=status,
                error=dict(error or {}),
                metadata=dict(metadata or {}),
            )
            if asyncio.iscoroutine(result):
                await result

    async def _submit_confirm(self, client: Any, request_id: str, accepted: bool, event: ClawBotWechatEvent) -> None:
        try:
            await client.submit_confirm_response(request_id=request_id, accepted=accepted)
        except Exception:
            await client.send_command("confirm_response", request_id=request_id, accepted=accepted, metadata=self._metadata_for(event))

    async def _submit_human_input(self, client: Any, payload: dict[str, Any], event: ClawBotWechatEvent) -> None:
        try:
            await client.submit_human_input_response(
                request_id=payload.get("request_id", ""),
                answer_text=payload.get("answer_text", ""),
                selected_option=payload.get("selected_option"),
            )
        except Exception:
            await client.send_command(
                "input_response",
                request_id=payload.get("request_id", ""),
                answer_text=payload.get("answer_text", ""),
                selected_option=payload.get("selected_option"),
                metadata=self._metadata_for(event),
            )

    def _metadata_for(self, event: ClawBotWechatEvent) -> dict[str, Any]:
        return {
            "source": "wechat",
            "transport": "clawbot_ilink",
            "provider": "official_clawbot",
            "response_transport": "non_streaming_endpoint_provider",
            "supports_streaming_reply": False,
            "supports_markdown": False,
            "progress_notice_policy": "prefer_before_nontrivial_final",
            "tool_scope": "basic",
            "allowed_tool_bundle": list(CLAWBOT_BASIC_TOOL_BUNDLE),
            "allowed_mcp_servers": [],
            "bot_id": event.bot_id,
            "peer_id_present": bool(event.peer_id),
            "event_id": event.event_id,
            "message_id": event.message_id,
            "seq": event.seq,
        }
