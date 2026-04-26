from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from adapters.meetwechat_client import (
    DEFAULT_MEETWECHAT_BASE_URL,
    MeetWeChatClient,
    MeetWeChatEvent,
    MeetWeChatHTTPError,
    MeetWeChatSendResult,
)
from clients.gateway_client import GatewayConversationClient
from core.client_tool_bundles import EXTERNAL_CLIENT_BASIC_TOOL_BUNDLE
from core.interaction_response_service import InteractionResponseService
from core.persistence import atomic_write_json, load_json_with_recovery


logger = logging.getLogger("meetyou.meetwechat")

DEFAULT_STATE_FILE = "user/meetwechat_client_state.json"
DEFAULT_POLL_INTERVAL_SECONDS = 2
DEFAULT_ERROR_BACKOFF_SECONDS = 2
DEFAULT_MAX_ERROR_BACKOFF_SECONDS = 30
DEFAULT_MAX_TEXT_CHARS = 1800
DEFAULT_EVENT_LIMIT = 20
DEFAULT_REPLY_TIMEOUT_SECONDS = 120
DEFAULT_INBOUND_WORKER_COUNT = 4
DEFAULT_INBOUND_QUEUE_SIZE = 500
DEFAULT_OUTBOUND_WORKER_COUNT = 2
DEFAULT_OUTBOUND_QUEUE_SIZE = 500
DEFAULT_OUTBOUND_MIN_INTERVAL_MS = 250
DEFAULT_SEND_TIMEOUT_MS = 10000
DEFAULT_STATE_FLUSH_INTERVAL_MS = 500
DEFAULT_GATEWAY_CLIENT_IDLE_TTL_SECONDS = 600
_MAX_STATE_EVENTS = 4096
_BLOCKED_SEND_STATUSES = {"manual_only", "mute", "read_only", "blocked"}
MEETWECHAT_BASIC_TOOL_BUNDLE = list(EXTERNAL_CLIENT_BASIC_TOOL_BUNDLE)


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


def _safe_non_negative_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if number < 0:
        return float(default)
    return number


def _hash_suffix(*parts: str, length: int = 4) -> str:
    digest = hashlib.sha256("\n".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()
    return digest[:length]


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
    accepted_tokens = {"y", "yes", "ok", "confirm", "approve", "allow", "true"}
    rejected_tokens = {"n", "no", "reject", "deny", "cancel", "false"}
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


@dataclass(slots=True)
class MeetWeChatProxyPolicy:
    mode: str = "guarded_auto"
    private_default: str = "auto"
    group_default: str = "mention_only"
    chat_overrides: dict[str, str] | None = None
    merge_window_seconds: float = 1.5
    reply_delay_seconds: float = 1.0
    fragment_pause_seconds: float = 0.8
    reply_timeout_seconds: float = DEFAULT_REPLY_TIMEOUT_SECONDS

    @classmethod
    def from_config(cls, value: Any) -> "MeetWeChatProxyPolicy":
        payload = value if isinstance(value, dict) else {}
        overrides = payload.get("chat_overrides") if isinstance(payload.get("chat_overrides"), dict) else {}
        return cls(
            mode=str(payload.get("mode") or "guarded_auto").strip().lower() or "guarded_auto",
            private_default=str(payload.get("private_default") or payload.get("private") or "auto").strip().lower()
            or "auto",
            group_default=str(payload.get("group_default") or payload.get("group") or "mention_only").strip().lower()
            or "mention_only",
            chat_overrides={
                str(chat_id): str(mode or "").strip().lower()
                for chat_id, mode in dict(overrides).items()
                if str(chat_id).strip() and str(mode or "").strip()
            },
            merge_window_seconds=_safe_non_negative_float(payload.get("merge_window_seconds"), 1.5),
            reply_delay_seconds=_safe_non_negative_float(payload.get("reply_delay_seconds"), 1.0),
            fragment_pause_seconds=_safe_non_negative_float(payload.get("fragment_pause_seconds"), 0.8),
            reply_timeout_seconds=_safe_non_negative_float(
                payload.get("reply_timeout_seconds"),
                DEFAULT_REPLY_TIMEOUT_SECONDS,
            )
            or DEFAULT_REPLY_TIMEOUT_SECONDS,
        )

    def mode_for(self, event: MeetWeChatEvent) -> str:
        raw_mode = event.raw.get("override") or event.raw.get("proxy_mode") or event.raw.get("mode")
        if raw_mode:
            return str(raw_mode).strip().lower()
        overrides = self.chat_overrides or {}
        if event.chat_id in overrides:
            return overrides[event.chat_id]
        if self.mode in {"manual_only", "mute", "read_only", "auto"}:
            return self.mode
        if event.chat_type == "group":
            if event.is_group_mention:
                return "auto" if self.group_default in {"mention_only", "auto"} else self.group_default
            return self.group_default
        return self.private_default

    def should_bridge_to_core(self, event: MeetWeChatEvent) -> bool:
        mode = self.mode_for(event)
        if mode in {"mute", "manual_only"}:
            return False
        if event.chat_type == "group" and not event.is_group_mention and mode != "auto":
            return False
        return mode in {"auto", "read_only", "guarded_auto"}

    def allow_send(self, event: MeetWeChatEvent) -> bool:
        return self.mode_for(event) == "auto"


class MeetWeChatStateStore:
    def __init__(self, state_file: str = DEFAULT_STATE_FILE, *, flush_interval_ms: int = 0):
        self.path = Path(state_file or DEFAULT_STATE_FILE)
        self._lock = asyncio.Lock()
        self._payload = self._load()
        self._flush_interval_seconds = max(int(flush_interval_ms or 0), 0) / 1000
        self._flush_task: asyncio.Task | None = None

    def _empty_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "events": {},
            "ack_pending": [],
            "threads": {},
            "sender_aliases": {},
            "updated_at": "",
        }

    def _load(self) -> dict[str, Any]:
        payload = load_json_with_recovery(
            str(self.path),
            validator=lambda item: isinstance(item, dict),
            default_factory=self._empty_payload,
        )
        if not isinstance(payload.get("events"), dict):
            payload["events"] = {}
        if not isinstance(payload.get("ack_pending"), list):
            payload["ack_pending"] = []
        if not isinstance(payload.get("threads"), dict):
            payload["threads"] = {}
        if not isinstance(payload.get("sender_aliases"), dict):
            payload["sender_aliases"] = {}
        return payload

    def _persist_now_locked(self) -> None:
        events = self._payload.setdefault("events", {})
        if isinstance(events, dict) and len(events) > _MAX_STATE_EVENTS:
            ordered = sorted(
                events.items(),
                key=lambda item: str((item[1] or {}).get("updated_at") or ""),
            )
            self._payload["events"] = dict(ordered[-_MAX_STATE_EVENTS:])
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
            logger.warning("MeetWeChat state flush failed: %s", exc)

    async def _persist_locked(self, *, force: bool = False) -> None:
        if force or self._flush_interval_seconds <= 0:
            if self._flush_task is not None:
                self._flush_task.cancel()
                self._flush_task = None
            self._persist_now_locked()
            return
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_after_delay())

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

    def get_event_status(self, event_id: str) -> str:
        event = self._payload.get("events", {}).get(str(event_id or ""), {})
        return str(event.get("status") or "")

    def list_ack_pending(self) -> list[str]:
        return [str(item) for item in self._payload.get("ack_pending", []) if str(item).strip()]

    async def mark_event_status(
        self,
        event_id: str,
        status: str,
        *,
        chat_id: str = "",
        reason: str = "",
    ) -> None:
        event_key = str(event_id or "").strip()
        if not event_key:
            return
        async with self._lock:
            events = self._payload.setdefault("events", {})
            current = dict(events.get(event_key) or {})
            current.update(
                {
                    "status": str(status or ""),
                    "chat_id": str(chat_id or current.get("chat_id") or ""),
                    "reason": str(reason or ""),
                    "updated_at": _utcnow_iso(),
                }
            )
            events[event_key] = current
            await self._persist_locked()

    async def mark_ack_pending(self, event_ids: list[str]) -> None:
        clean_ids = [str(item).strip() for item in event_ids if str(item).strip()]
        if not clean_ids:
            return
        async with self._lock:
            pending = list(self._payload.setdefault("ack_pending", []))
            for event_id in clean_ids:
                if event_id not in pending:
                    pending.append(event_id)
            self._payload["ack_pending"] = pending
            await self._persist_locked()

    async def clear_ack_pending(self, event_ids: list[str]) -> None:
        clean_ids = {str(item).strip() for item in event_ids if str(item).strip()}
        if not clean_ids:
            return
        async with self._lock:
            pending = [item for item in self._payload.setdefault("ack_pending", []) if item not in clean_ids]
            self._payload["ack_pending"] = pending
            await self._persist_locked()

    def get_thread_id(self, conversation_key: str) -> str:
        return str(self._payload.get("threads", {}).get(str(conversation_key or ""), "") or "")

    async def set_thread_id(self, conversation_key: str, thread_id: str) -> None:
        if not conversation_key or not thread_id:
            return
        async with self._lock:
            self._payload.setdefault("threads", {})[str(conversation_key)] = str(thread_id)
            await self._persist_locked()

    def sender_alias(self, chat_id: str, sender_id: str) -> str:
        key = f"{chat_id}:{sender_id}"
        aliases = self._payload.setdefault("sender_aliases", {})
        alias = str(aliases.get(key) or "")
        if alias:
            return alias
        alias = f"member#{_hash_suffix(chat_id, sender_id)}"
        aliases[key] = alias
        return alias


@dataclass(slots=True)
class _PendingReply:
    event: MeetWeChatEvent
    allow_send: bool
    participant_key: str
    future: asyncio.Future


@dataclass(slots=True)
class _OutboundMessage:
    pending: _PendingReply
    text: str
    complete_pending: bool = True
    delay_before_send: bool = True
    message_index: int = 1


class MeetWeChatOutputService:
    def __init__(
        self,
        *,
        config,
        client: MeetWeChatClient,
        state_store: MeetWeChatStateStore,
        policy: MeetWeChatProxyPolicy | None = None,
        sleeper: Callable[[float], Any] = asyncio.sleep,
    ):
        self._config = config
        self._client = client
        self._state_store = state_store
        self._policy = policy or MeetWeChatProxyPolicy.from_config(config.get("meetwechat_proxy_policy") or {})
        self._sleeper = sleeper
        self._stream_buffers: dict[str, list[str]] = {}
        self._pending_replies: dict[str, _PendingReply] = {}
        self._pending_confirm_requests: dict[str, str] = {}
        self._pending_human_input_requests: dict[str, dict[str, Any]] = {}
        self._outbound_queue: asyncio.Queue[_OutboundMessage] = asyncio.Queue(
            maxsize=_safe_positive_int(
                config.get("meetwechat_outbound_queue_size"),
                DEFAULT_OUTBOUND_QUEUE_SIZE,
            )
        )
        self._outbound_worker_count = _safe_positive_int(
            config.get("meetwechat_outbound_worker_count"),
            DEFAULT_OUTBOUND_WORKER_COUNT,
        )
        self._send_timeout_seconds = (
            _safe_positive_int(config.get("meetwechat_send_timeout_ms"), DEFAULT_SEND_TIMEOUT_MS) / 1000
        )
        self._min_send_interval_seconds = (
            _safe_positive_int(
                config.get("meetwechat_outbound_min_interval_ms"),
                DEFAULT_OUTBOUND_MIN_INTERVAL_MS,
            )
            / 1000
        )
        self._outbound_workers: list[asyncio.Task] = []
        self._outbound_locks: dict[str, asyncio.Lock] = {}
        self._outbound_message_counts: dict[str, int] = {}
        self._rate_lock = asyncio.Lock()
        self._last_send_at = 0.0

    async def close(self) -> None:
        for worker in self._outbound_workers:
            worker.cancel()
        for worker in self._outbound_workers:
            with contextlib.suppress(asyncio.CancelledError):
                await worker
        self._outbound_workers.clear()
        for pending in list(self._pending_replies.values()):
            if not pending.future.done():
                pending.future.cancel()
        self._pending_replies.clear()

    def begin_event(self, event: MeetWeChatEvent, *, allow_send: bool) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        participant_key = self.participant_key(event)
        self._pending_replies[event.chat_id] = _PendingReply(
            event=event,
            allow_send=allow_send,
            participant_key=participant_key,
            future=future,
        )
        return future

    def participant_key(self, event: MeetWeChatEvent) -> str:
        if event.chat_type == "group":
            return f"{event.chat_id}:{event.sender_id}"
        return event.chat_id

    def get_pending_confirm_request(self, participant_key: str) -> str | None:
        return self._pending_confirm_requests.get(participant_key)

    def clear_pending_confirm_request(self, participant_key: str, request_id: str = "") -> None:
        current_request_id = self._pending_confirm_requests.get(participant_key)
        if current_request_id and (not request_id or current_request_id == request_id):
            self._pending_confirm_requests.pop(participant_key, None)

    def resolve_human_input(self, participant_key: str, raw_text: str) -> dict[str, Any] | None:
        payload = self._pending_human_input_requests.pop(participant_key, None)
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

    def _stream_key(self, chat_id: str, stream_id: str) -> str:
        return f"{chat_id}:{stream_id}" if stream_id else ""

    def _append_stream_buffer(self, stream_key: str, content: str) -> None:
        if stream_key:
            self._stream_buffers.setdefault(stream_key, []).append(content)

    def _complete_pending(self, chat_id: str, ok: bool, detail: str = "") -> None:
        pending = self._pending_replies.pop(chat_id, None)
        if pending is None or pending.future.done():
            return
        pending.future.set_result({"ok": ok, "detail": detail})

    async def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        result = self._sleeper(seconds)
        if asyncio.iscoroutine(result):
            await result

    async def send_client_event(self, chat_id: str, payload: dict[str, Any]) -> None:
        if payload.get("schema") != "meetyou.client.ws.v1":
            return
        kind = payload.get("kind")
        if kind == "error":
            self._complete_pending(chat_id, False, "client websocket error")
            return
        if kind != "event":
            return
        event = payload.get("event", {}) or {}
        event_type = str(event.get("type") or "")
        stream_id = str(event.get("stream_id") or "")
        stream_key = self._stream_key(chat_id, stream_id)
        pending = self._pending_replies.get(chat_id)

        if event_type == "confirm.requested":
            if pending is not None:
                request_id = str(event.get("request_id") or "")
                self._pending_confirm_requests[pending.participant_key] = request_id
                text = f"{event.get('content', '')}\nConfirm ID: {request_id}\nReply y/yes to approve, n/no to reject."
                self._enqueue_outbound(pending, text, delay_before_send=False)
            return
        if event_type == "confirm.resolved":
            request_id = str(event.get("request_id") or "")
            for key, value in list(self._pending_confirm_requests.items()):
                if not request_id or value == request_id:
                    self._pending_confirm_requests.pop(key, None)
            return
        if event_type == "human_input.requested":
            if pending is not None:
                request_id = str(event.get("request_id") or "")
                options = [str(item).strip() for item in event.get("options", []) if str(item).strip()]
                self._pending_human_input_requests[pending.participant_key] = {
                    "request_id": request_id,
                    "options": options,
                }
                option_lines = "\n".join(f"{index}. {option}" for index, option in enumerate(options, start=1))
                suffix = f"\n{option_lines}" if option_lines else ""
                text = f"{event.get('question', '')}{suffix}\nReply with a number or text.\nRequest ID: {request_id}"
                self._enqueue_outbound(pending, text, delay_before_send=False)
            return
        if event_type == "human_input.resolved":
            request_id = str(event.get("request_id") or "")
            for key, value in list(self._pending_human_input_requests.items()):
                if not request_id or value.get("request_id") == request_id:
                    self._pending_human_input_requests.pop(key, None)
            return
        if event_type == "message.created":
            message = event.get("message", {}) or {}
            channel = str(message.get("channel") or "")
            if channel in {"short_reply", "notice"} and pending is not None:
                self._enqueue_outbound(
                    pending,
                    str(message.get("content") or ""),
                    delay_before_send=False,
                    complete_pending=False,
                )
            elif channel in {"short_reply", "notice"}:
                content = str(message.get("content") or "")
                if content.strip():
                    try:
                        await self._send_direct_text(chat_id, content)
                    except Exception as exc:
                        logger.warning("MeetWeChat direct notice send failed chat=%s error=%s", _mask(chat_id), exc)
            return
        if event_type in {"reasoning.delta", "operation.updated", "activity.status"}:
            return
        if event_type == "message.delta":
            if str(event.get("channel") or "") == "answer":
                self._append_stream_buffer(stream_key, str(event.get("delta") or ""))
            return
        if event_type == "message.completed":
            message = event.get("message", {}) or {}
            text = "".join(self._stream_buffers.pop(stream_key, [])) if stream_key else ""
            text += str(message.get("content") or "")
            if pending is None:
                return
            self._enqueue_outbound(pending, text)

    def _ensure_outbound_workers(self) -> None:
        self._outbound_workers = [worker for worker in self._outbound_workers if not worker.done()]
        while len(self._outbound_workers) < self._outbound_worker_count:
            self._outbound_workers.append(asyncio.create_task(self._run_outbound_worker()))

    def _enqueue_outbound(
        self,
        pending: _PendingReply,
        text: str,
        *,
        delay_before_send: bool = True,
        complete_pending: bool = True,
    ) -> None:
        content = str(text or "").strip()
        if not content or not pending.allow_send:
            if complete_pending:
                self._complete_pending(pending.event.chat_id, True)
            return
        self._ensure_outbound_workers()
        try:
            message_index = self._next_outbound_message_index(pending.event.event_id)
            self._outbound_queue.put_nowait(
                _OutboundMessage(
                    pending=pending,
                    text=content,
                    complete_pending=complete_pending,
                    delay_before_send=delay_before_send,
                    message_index=message_index,
                )
            )
        except asyncio.QueueFull:
            logger.warning(
                "MeetWeChat outbound queue full chat=%s event=%s",
                _mask(pending.event.chat_id),
                _mask(pending.event.event_id),
            )
            if complete_pending:
                self._complete_pending(pending.event.chat_id, False, "outbound queue full")

    async def _send_direct_text(self, chat_id: str, text: str) -> None:
        content = str(text or "").strip()
        if not chat_id or not content:
            return
        limit = _safe_positive_int(self._config.get("meetwechat_max_text_chars"), DEFAULT_MAX_TEXT_CHARS)
        fragments = split_text_naturally(content, limit=limit)
        seed = hashlib.sha256(f"{chat_id}:{content}:{datetime.now(timezone.utc).isoformat()}".encode("utf-8")).hexdigest()[:16]
        for index, fragment in enumerate(fragments, start=1):
            await self._wait_global_send_slot()
            result = await asyncio.wait_for(
                self._client.send_text(
                    chat_id=chat_id,
                    text=fragment,
                    idempotency_key=f"meetyou:direct:{seed}:{index}",
                    is_group_mention=False,
                ),
                timeout=self._send_timeout_seconds,
            )
            self._check_send_result(result)

    def _next_outbound_message_index(self, event_id: str) -> int:
        key = str(event_id or "").strip()
        if not key:
            return 1
        next_value = int(self._outbound_message_counts.get(key, 0) or 0) + 1
        self._outbound_message_counts[key] = next_value
        return next_value

    async def _run_outbound_worker(self) -> None:
        while True:
            item = await self._outbound_queue.get()
            try:
                lock = self._outbound_locks.setdefault(item.pending.event.chat_id, asyncio.Lock())
                async with lock:
                    await self._send_for_pending(
                        item.pending,
                        item.text,
                        delay_before_send=item.delay_before_send,
                        message_index=item.message_index,
                    )
                if item.complete_pending:
                    self._complete_pending(item.pending.event.chat_id, True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "MeetWeChat send failed chat=%s event=%s error=%s",
                    _mask(item.pending.event.chat_id),
                    _mask(item.pending.event.event_id),
                    exc,
                )
                if item.complete_pending:
                    self._complete_pending(item.pending.event.chat_id, False, "send failed")
            finally:
                self._outbound_queue.task_done()

    async def _send_for_pending(
        self,
        pending: _PendingReply,
        text: str,
        *,
        delay_before_send: bool = True,
        message_index: int = 1,
    ) -> None:
        content = str(text or "").strip()
        if not content:
            return
        if not pending.allow_send:
            return
        if delay_before_send:
            await self._sleep(self._policy.reply_delay_seconds)
        limit = _safe_positive_int(self._config.get("meetwechat_max_text_chars"), DEFAULT_MAX_TEXT_CHARS)
        fragments = split_text_naturally(content, limit=limit)
        for index, fragment in enumerate(fragments, start=1):
            await self._send_fragment_with_retry(
                pending,
                fragment,
                message_index=message_index,
                index=index,
            )
            if index < len(fragments):
                await self._sleep(self._policy.fragment_pause_seconds)

    async def _wait_global_send_slot(self) -> None:
        async with self._rate_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait_seconds = self._min_send_interval_seconds - (now - self._last_send_at)
            if wait_seconds > 0:
                await self._sleep(wait_seconds)
            self._last_send_at = loop.time()

    @staticmethod
    def _idempotency_key(event_id: str, *, message_index: int, fragment_index: int) -> str:
        if int(message_index or 1) <= 1:
            return f"meetyou:{event_id}:{fragment_index}"
        return f"meetyou:{event_id}:{message_index}:{fragment_index}"

    async def _send_fragment_with_retry(self, pending: _PendingReply, fragment: str, *, message_index: int, index: int) -> None:
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                await self._wait_global_send_slot()
                result = await asyncio.wait_for(
                    self._client.send_text(
                        chat_id=pending.event.chat_id,
                        text=fragment,
                        idempotency_key=self._idempotency_key(
                            pending.event.event_id,
                            message_index=message_index,
                            fragment_index=index,
                        ),
                        is_group_mention=pending.event.chat_type == "group",
                    ),
                    timeout=self._send_timeout_seconds,
                )
                self._check_send_result(result)
                return
            except Exception as exc:
                if attempt >= max_attempts - 1 or not self._is_transient_send_error(exc):
                    raise
                await self._sleep(min(0.5 * (2**attempt), 3.0))

    def _is_transient_send_error(self, exc: Exception) -> bool:
        if isinstance(exc, asyncio.TimeoutError):
            return True
        if isinstance(exc, MeetWeChatHTTPError):
            return exc.status == 429 or exc.status >= 500
        return isinstance(exc, (ConnectionError, OSError))

    def _check_send_result(self, result: MeetWeChatSendResult) -> None:
        if result.ok:
            return
        if result.status in _BLOCKED_SEND_STATUSES:
            return
        raise RuntimeError(result.detail or result.status or "MeetWeChat send rejected")


class MeetWeChatInputAdapter:
    def __init__(
        self,
        event_bus,
        session_manager,
        config,
        *,
        client: MeetWeChatClient | None = None,
        state_store: MeetWeChatStateStore | None = None,
        output_adapter: MeetWeChatOutputService | None = None,
        gateway_client_factory: Callable[..., Any] = GatewayConversationClient,
    ):
        self._event_bus = event_bus
        self._interaction_responses = InteractionResponseService(event_bus)
        self._core_session_manager = session_manager
        self._config = config
        self._gateway_client_factory = gateway_client_factory
        self._policy = MeetWeChatProxyPolicy.from_config(config.get("meetwechat_proxy_policy") or {})
        self._client = client or MeetWeChatClient(
            base_url=str(config.get("meetwechat_base_url") or DEFAULT_MEETWECHAT_BASE_URL),
        )
        self._state_store = state_store or MeetWeChatStateStore(
            str(config.get("meetwechat_state_file") or DEFAULT_STATE_FILE),
            flush_interval_ms=_safe_positive_int(
                config.get("meetwechat_state_flush_interval_ms"),
                DEFAULT_STATE_FLUSH_INTERVAL_MS,
            ),
        )
        self._output_adapter = output_adapter or MeetWeChatOutputService(
            config=config,
            client=self._client,
            state_store=self._state_store,
            policy=self._policy,
        )
        self._gateway_clients: dict[str, Any] = {}
        self._gateway_client_last_used: dict[str, float] = {}
        self._gateway_client_idle_ttl_seconds = _safe_positive_int(
            config.get("meetwechat_gateway_client_idle_ttl_seconds"),
            DEFAULT_GATEWAY_CLIENT_IDLE_TTL_SECONDS,
        )
        self._poll_task: asyncio.Task | None = None
        self._closed = False
        self._persistent_workers = False
        self._inbound_worker_count = _safe_positive_int(
            config.get("meetwechat_inbound_worker_count"),
            DEFAULT_INBOUND_WORKER_COUNT,
        )
        self._inbound_queue: asyncio.Queue[MeetWeChatEvent] = asyncio.Queue(
            maxsize=_safe_positive_int(
                config.get("meetwechat_inbound_queue_size"),
                DEFAULT_INBOUND_QUEUE_SIZE,
            )
        )
        self._inbound_workers: list[asyncio.Task] = []
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._cursor = ""

        host = str(self._config.get("gateway_host") or "127.0.0.1").strip() or "127.0.0.1"
        if host in {"0.0.0.0", "::", "::0"}:
            host = "127.0.0.1"
        port = int(self._config.get("gateway_port") or 8000)
        self._gateway_base_url = f"http://{host}:{port}"
        self._gateway_access_token = str(self._config.get("gateway_access_token") or "").strip()

    async def run(self) -> None:
        self._closed = False
        self._persistent_workers = True
        await self._client.init()
        self._ensure_inbound_workers()
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._run_poll_loop())
        logger.info("MeetWeChat Client polling started")

    async def close(self) -> None:
        self._closed = True
        self._persistent_workers = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        await self._stop_inbound_workers()
        for client in self._gateway_clients.values():
            close = getattr(client, "close", None)
            if callable(close):
                await close()
        self._gateway_clients.clear()
        self._gateway_client_last_used.clear()
        await self._output_adapter.close()
        await self._state_store.close()
        await self._client.close()

    async def _run_poll_loop(self) -> None:
        base_backoff = _safe_positive_int(
            self._config.get("meetwechat_error_backoff_seconds"),
            DEFAULT_ERROR_BACKOFF_SECONDS,
        )
        backoff_seconds = base_backoff
        while not self._closed:
            try:
                await self._ack_pending_events()
                events, cursor = await self._client.get_events(limit=DEFAULT_EVENT_LIMIT, cursor=self._cursor)
                if not self._enqueue_events_nowait(events):
                    logger.warning("MeetWeChat inbound queue full; cursor is not advanced")
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, DEFAULT_MAX_ERROR_BACKOFF_SECONDS)
                    continue
                if cursor:
                    self._cursor = cursor
                backoff_seconds = base_backoff
                await self._close_idle_gateway_clients()
                await asyncio.sleep(
                    _safe_positive_int(
                        self._config.get("meetwechat_poll_interval_seconds"),
                        DEFAULT_POLL_INTERVAL_SECONDS,
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("MeetWeChat polling failed: %s", exc)
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, DEFAULT_MAX_ERROR_BACKOFF_SECONDS)

    async def handle_events(self, events: list[MeetWeChatEvent]) -> None:
        self._ensure_inbound_workers()
        for event in events:
            await self._inbound_queue.put(event)
        await self._inbound_queue.join()
        if not self._persistent_workers:
            await self._stop_inbound_workers()

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

    def _enqueue_events_nowait(self, events: list[MeetWeChatEvent]) -> bool:
        if not events:
            return True
        self._ensure_inbound_workers()
        maxsize = int(self._inbound_queue.maxsize or 0)
        if maxsize > 0 and self._inbound_queue.qsize() + len(events) > maxsize:
            return False
        try:
            for event in events:
                self._inbound_queue.put_nowait(event)
        except asyncio.QueueFull:
            return False
        return True

    def _event_order_key(self, event: MeetWeChatEvent) -> str:
        return event.chat_id or event.sender_id or "__missing__"

    async def _run_inbound_worker(self) -> None:
        while not self._closed:
            event = await self._inbound_queue.get()
            order_key = self._event_order_key(event)
            try:
                lock = self._conversation_locks.setdefault(order_key, asyncio.Lock())
                async with lock:
                    await self._handle_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("MeetWeChat inbound worker failed chat=%s error=%s", _mask(order_key), exc)
            finally:
                self._inbound_queue.task_done()

    async def _handle_event(self, event: MeetWeChatEvent) -> None:
        if not event.event_id:
            logger.debug("MeetWeChat skipped event without event_id chat=%s", _mask(event.chat_id))
            return
        status = self._state_store.get_event_status(event.event_id)
        if status in {"acked", "sent", "skipped", "read_only"}:
            await self._ack_event(event.event_id, status=status)
            return
        if event.is_self or event.content_type != "text" or not event.text.strip():
            await self._state_store.mark_event_status(event.event_id, "skipped", chat_id=event.chat_id)
            await self._ack_event(event.event_id, status="skipped")
            return

        mode = self._policy.mode_for(event)
        if mode in {"mute", "manual_only"}:
            await self._state_store.mark_event_status(event.event_id, "skipped", chat_id=event.chat_id, reason=mode)
            await self._ack_event(event.event_id, status="skipped")
            return
        participant_key = self._output_adapter.participant_key(event)
        text = str(event.text or "").strip()

        confirm_value = _parse_confirm_response(text)
        pending_confirm = self._output_adapter.get_pending_confirm_request(participant_key)
        if confirm_value is not None and pending_confirm:
            client = await self._get_gateway_client(event)
            await self._submit_confirm(client, pending_confirm, confirm_value, event)
            self._output_adapter.clear_pending_confirm_request(participant_key, pending_confirm)
            await self._state_store.mark_event_status(event.event_id, "sent", chat_id=event.chat_id)
            await self._ack_event(event.event_id, status="sent")
            return

        pending_human_input = self._output_adapter.resolve_human_input(participant_key, text)
        if pending_human_input is not None:
            client = await self._get_gateway_client(event)
            await self._submit_human_input(client, pending_human_input, event)
            await self._state_store.mark_event_status(event.event_id, "sent", chat_id=event.chat_id)
            await self._ack_event(event.event_id, status="sent")
            return

        if event.chat_type == "group" and not event.is_group_mention and mode != "auto":
            await self._state_store.mark_event_status(
                event.event_id,
                "skipped",
                chat_id=event.chat_id,
                reason="group_not_mentioned",
            )
            await self._ack_event(event.event_id, status="skipped")
            return

        await self._state_store.mark_event_status(event.event_id, "processing", chat_id=event.chat_id)
        client = await self._get_gateway_client(event)
        await self._sleep(self._policy.merge_window_seconds)
        allow_send = self._policy.allow_send(event)
        future = self._output_adapter.begin_event(event, allow_send=allow_send)
        try:
            await client.send_message(
                self._format_inbound_text(event),
                metadata=self._metadata_for(event),
                preferred_mode=_infer_preferred_mode(text),
                client_message_id=event.event_id,
            )
            result = await asyncio.wait_for(future, timeout=self._policy.reply_timeout_seconds)
        except Exception as exc:
            logger.warning(
                "MeetWeChat Core bridge failed chat=%s event=%s error=%s",
                _mask(event.chat_id),
                _mask(event.event_id),
                exc,
            )
            await self._state_store.mark_event_status(event.event_id, "failed", chat_id=event.chat_id, reason="bridge")
            return
        if not bool(result.get("ok")):
            await self._state_store.mark_event_status(event.event_id, "failed", chat_id=event.chat_id, reason="reply")
            return
        final_status = "sent" if allow_send else "read_only"
        await self._state_store.mark_event_status(event.event_id, final_status, chat_id=event.chat_id)
        await self._ack_event(event.event_id, status=final_status)

    async def _submit_confirm(self, client: Any, request_id: str, accepted: bool, event: MeetWeChatEvent) -> None:
        try:
            await client.submit_confirm_response(request_id=request_id, accepted=accepted)
        except Exception:
            await client.send_command(
                "confirm_response",
                request_id=request_id,
                accepted=accepted,
                metadata=self._metadata_for(event),
            )

    async def _submit_human_input(self, client: Any, payload: dict[str, Any], event: MeetWeChatEvent) -> None:
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

    async def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        await asyncio.sleep(seconds)

    async def _ack_pending_events(self) -> None:
        pending = self._state_store.list_ack_pending()
        if pending:
            await self._ack_event_ids(pending, status="acked")

    async def _ack_event(self, event_id: str, *, status: str) -> None:
        await self._ack_event_ids([event_id], status=status)

    async def _ack_event_ids(self, event_ids: list[str], *, status: str) -> None:
        clean_ids = [str(item).strip() for item in event_ids if str(item).strip()]
        if not clean_ids:
            return
        try:
            await self._client.ack_events(clean_ids)
        except Exception as exc:
            logger.warning("MeetWeChat ACK failed events=%s error=%s", len(clean_ids), exc)
            await self._state_store.mark_ack_pending(clean_ids)
            return
        await self._state_store.clear_ack_pending(clean_ids)
        for event_id in clean_ids:
            await self._state_store.mark_event_status(event_id, "acked" if status != "failed" else status)

    def _conversation_key(self, event: MeetWeChatEvent) -> str:
        prefix = "group" if event.chat_type == "group" else "chat"
        return f"wechat:meetwechat:{prefix}:{event.chat_id}"

    async def _close_idle_gateway_clients(self) -> None:
        if self._gateway_client_idle_ttl_seconds <= 0 or not self._gateway_clients:
            return
        now = asyncio.get_running_loop().time()
        stale_keys = [
            key
            for key, last_used in self._gateway_client_last_used.items()
            if now - float(last_used or 0) >= self._gateway_client_idle_ttl_seconds
        ]
        for conversation_key in stale_keys:
            client = self._gateway_clients.pop(conversation_key, None)
            self._gateway_client_last_used.pop(conversation_key, None)
            if client is None:
                continue
            close = getattr(client, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    await close()

    async def _get_gateway_client(self, event: MeetWeChatEvent) -> Any:
        conversation_key = self._conversation_key(event)
        client = self._gateway_clients.get(conversation_key)
        if client is None:
            digest = hashlib.sha256(conversation_key.encode("utf-8")).hexdigest()[:20]
            thread_id = self._state_store.get_thread_id(conversation_key)
            client = self._gateway_client_factory(
                base_url=self._gateway_base_url,
                client_id=f"meetwechat-{digest}",
                client_type="wechat",
                display_name=f"MeetWeChat {event.chat_type} {_mask(event.chat_id)}",
                workspace_id="personal",
                access_token=self._gateway_access_token,
                thread_title=f"MeetWeChat {event.chat_type} {_mask(event.chat_id)}",
                thread_id=thread_id,
                event_handler=lambda payload, chat_id=event.chat_id: self._output_adapter.send_client_event(
                    chat_id,
                    payload,
                ),
            )
            self._gateway_clients[conversation_key] = client
        await client.start()
        self._gateway_client_last_used[conversation_key] = asyncio.get_running_loop().time()
        thread_id = str(getattr(client, "thread_id", "") or "")
        if thread_id:
            await self._state_store.set_thread_id(conversation_key, thread_id)
        return client

    def _sender_alias(self, event: MeetWeChatEvent) -> str:
        if event.chat_type != "group":
            return ""
        return self._state_store.sender_alias(event.chat_id, event.sender_id)

    def _format_inbound_text(self, event: MeetWeChatEvent) -> str:
        text = str(event.text or "").strip()
        if event.chat_type != "group":
            return text
        alias = self._sender_alias(event)
        return f"{alias}: {text}" if alias else text

    def _metadata_for(self, event: MeetWeChatEvent) -> dict[str, Any]:
        alias = self._sender_alias(event)
        return {
            "source": "wechat",
            "transport": "meetwechat",
            "response_transport": "non_streaming_external_client",
            "supports_streaming_reply": False,
            "short_reply_policy": "prefer_before_nontrivial_final",
            "tool_scope": "basic",
            "allowed_tool_bundle": list(MEETWECHAT_BASIC_TOOL_BUNDLE),
            "allowed_mcp_servers": [],
            "chat_id": event.chat_id,
            "chat_type": event.chat_type,
            "sender_id": event.sender_id,
            "sender_name_present": bool(event.sender_name),
            "sender_alias": alias,
            "event_id": event.event_id,
            "message_id": event.message_id,
            "dedup_key": event.dedup_key,
            "raw_hash": event.raw_hash,
            "is_group_mention": event.is_group_mention,
        }
