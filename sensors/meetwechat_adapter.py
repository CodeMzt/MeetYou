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
from endpoint_providers.runtime_connection import EndpointRuntimeConnection, resolve_core_base_url
from core.endpoint_tool_bundles import EXTERNAL_ENDPOINT_BASIC_TOOL_BUNDLE
from core.delivery_formatting import markdown_to_plain_text
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
DEFAULT_DIRECT_SEND_MAX_ATTEMPTS = 5
DEFAULT_DIRECT_SEND_RETRY_BASE_SECONDS = 2.0
DEFAULT_DIRECT_SEND_RETRY_MAX_SECONDS = 30.0
DEFAULT_STATE_FLUSH_INTERVAL_MS = 500
DEFAULT_GATEWAY_ENDPOINT_IDLE_TTL_SECONDS = 600
_MAX_STATE_EVENTS = 4096
_BLOCKED_SEND_STATUSES = {"manual_only", "mute", "read_only", "blocked"}
MEETWECHAT_BASIC_TOOL_BUNDLE = list(EXTERNAL_ENDPOINT_BASIC_TOOL_BUNDLE)


class MeetWeChatSendBlocked(RuntimeError):
    def __init__(self, result: MeetWeChatSendResult):
        self.result = result
        status = str(result.status or "blocked")
        detail = str(result.detail or "")
        message = f"{status}: {detail}" if detail else status
        super().__init__(message)


class MeetWeChatSendUncertain(RuntimeError):
    def __init__(self, result: MeetWeChatSendResult):
        self.result = result
        status = str(result.status or "failed")
        detail = str(result.detail or "")
        message = f"{status}: {detail}" if detail else status
        super().__init__(message)


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


def _event_identity_key(event: MeetWeChatEvent) -> str:
    scoped_parts = [
        str(event.chat_type or "").strip().lower(),
        str(event.chat_id or "").strip(),
        str(event.sender_id or "").strip(),
    ]
    for label, value in (
        ("dedup", event.dedup_key),
        ("message", event.message_id),
        ("raw", event.raw_hash),
        ("event", event.event_id),
    ):
        normalized = str(value or "").strip()
        if not normalized:
            continue
        digest = hashlib.sha256("\n".join([*scoped_parts, label, normalized]).encode("utf-8")).hexdigest()[:32]
        return f"meetwechat:{label}:{digest}"
    fallback = "\n".join(
        [
            *scoped_parts,
            str(event.timestamp or "").strip(),
            str(event.content_type or "").strip().lower(),
            hashlib.sha256(str(event.text or "").encode("utf-8")).hexdigest(),
        ]
    )
    digest = hashlib.sha256(fallback.encode("utf-8")).hexdigest()[:32]
    return f"meetwechat:fallback:{digest}"


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
        mode = self.mode_for(event)
        if mode in {"mute", "manual_only", "read_only"}:
            return False
        if event.chat_type == "group" and not event.is_group_mention and mode != "auto":
            return False
        return mode in {"auto", "guarded_auto"}


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
            "event_identities": {},
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
        if not isinstance(payload.get("event_identities"), dict):
            payload["event_identities"] = {}
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
        identities = self._payload.setdefault("event_identities", {})
        if isinstance(identities, dict):
            live_event_ids = set((self._payload.get("events") or {}).keys())
            self._payload["event_identities"] = {
                str(identity): str(event_id)
                for identity, event_id in identities.items()
                if str(event_id) in live_event_ids
            }
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

    def _event_record(self, event_id: str, *, identity_key: str = "") -> dict[str, Any]:
        events = self._payload.get("events", {})
        event = events.get(str(event_id or ""), {})
        if event:
            return dict(event or {})
        identity = str(identity_key or "").strip()
        if identity:
            canonical_event_id = str(self._payload.get("event_identities", {}).get(identity) or "").strip()
            if canonical_event_id:
                return dict(events.get(canonical_event_id, {}) or {})
        return {}

    def get_event_status(self, event_id: str, *, identity_key: str = "") -> str:
        event = self._event_record(event_id, identity_key=identity_key)
        return str(event.get("status") or "")

    def list_ack_pending(self) -> list[str]:
        return [str(item) for item in self._payload.get("ack_pending", []) if str(item).strip()]

    def event_is_acked(self, event_id: str, *, identity_key: str = "") -> bool:
        event = self._event_record(event_id, identity_key=identity_key)
        return bool(event.get("acked"))

    async def mark_event_status(
        self,
        event_id: str,
        status: str,
        *,
        chat_id: str = "",
        reason: str = "",
        identity_key: str = "",
        core_message_id: str = "",
    ) -> None:
        event_key = str(event_id or "").strip()
        if not event_key:
            return
        identity = str(identity_key or "").strip()
        async with self._lock:
            events = self._payload.setdefault("events", {})
            current = dict(events.get(event_key) or {})
            current.update(
                {
                    "status": str(status or ""),
                    "chat_id": str(chat_id or current.get("chat_id") or ""),
                    "reason": str(reason or current.get("reason") or ""),
                    "updated_at": _utcnow_iso(),
                }
            )
            if identity:
                current["identity_key"] = identity
                self._payload.setdefault("event_identities", {})[identity] = event_key
            if core_message_id:
                current["core_message_id"] = str(core_message_id)
            events[event_key] = current
            await self._persist_locked()

    async def mark_events_acked(self, event_ids: list[str]) -> None:
        clean_ids = [str(item).strip() for item in event_ids if str(item).strip()]
        if not clean_ids:
            return
        async with self._lock:
            events = self._payload.setdefault("events", {})
            acked_at = _utcnow_iso()
            for event_id in clean_ids:
                current = dict(events.get(event_id) or {})
                if not str(current.get("status") or "").strip():
                    current["status"] = "acked"
                current["acked"] = True
                current["acked_at"] = acked_at
                current["updated_at"] = acked_at
                events[event_id] = current
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
        delivery_result_sender: Callable[..., Any] | None = None,
    ):
        self._config = config
        self._client = client
        self._state_store = state_store
        self._policy = policy or MeetWeChatProxyPolicy.from_config(config.get("meetwechat_proxy_policy") or {})
        self._sleeper = sleeper
        self._delivery_result_sender = delivery_result_sender
        self._stream_buffers: dict[str, list[str]] = {}
        self._queued_final_keys: set[str] = set()
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

    def set_delivery_result_sender(self, sender: Callable[..., Any] | None) -> None:
        self._delivery_result_sender = sender

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
        previous = self._pending_replies.get(event.chat_id)
        if previous is not None and not previous.future.done():
            previous.future.cancel()
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

    def _complete_pending(self, chat_id: str, ok: bool, detail: str = "", *, terminal: bool = False) -> None:
        pending = self._pending_replies.pop(chat_id, None)
        if pending is None or pending.future.done():
            return
        pending.future.set_result({"ok": ok, "detail": detail, "terminal": bool(terminal)})

    def discard_pending(self, chat_id: str, event_id: str) -> None:
        pending = self._pending_replies.get(chat_id)
        if pending is None or pending.event.event_id != event_id:
            return
        self._pending_replies.pop(chat_id, None)
        if not pending.future.done():
            pending.future.cancel()

    async def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        result = self._sleeper(seconds)
        if asyncio.iscoroutine(result):
            await result

    @staticmethod
    def _delivery_id(payload: dict[str, Any], body_payload: dict[str, Any]) -> str:
        return str(body_payload.get("delivery_id") or payload.get("delivery_id") or "").strip()

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
            logger.warning("MeetWeChat delivery result report failed delivery=%s error=%s", _mask(delivery_id), exc)

    async def send_runtime_event(self, chat_id: str, payload: dict[str, Any]) -> None:
        if payload.get("schema") != "meetyou.endpoint.ws.v4":
            return
        frame_type = str(payload.get("type") or "")
        body_payload = payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}
        delivery_id = self._delivery_id(payload, body_payload)
        target_chat_id = str(body_payload.get("target_external_ref") or "").strip()
        if target_chat_id:
            # Address-targeted delivery may arrive on either the provider-level
            # connection or the chat thread subscription. A chat-scoped handler
            # should only ignore frames for a different chat; final-message
            # dedupe below prevents duplicate sends when both receive it.
            if chat_id and chat_id != target_chat_id:
                return
            chat_id = target_chat_id
        if not chat_id and frame_type.startswith("delivery."):
            return
        pending = self._pending_replies.get(chat_id)
        if frame_type == "endpoint.error":
            self._complete_pending(chat_id, False, "endpoint websocket error")
            return
        if frame_type == "delivery.notice":
            notice = payload.get("payload", {}) or {}
            content = str(notice.get("content") or notice.get("text") or "").strip()
            if not content and isinstance(notice.get("message"), dict):
                content = str(notice["message"].get("content") or "").strip()
            if not content:
                return
            if pending is not None:
                self._enqueue_outbound(
                    pending,
                    content,
                    delay_before_send=False,
                    complete_pending=False,
                )
            else:
                try:
                    await self._send_direct_text(chat_id, content)
                    await self._report_delivery_result(
                        delivery_id,
                        status="sent",
                        metadata={"provider_type": "wechat", "chat_id": _mask(chat_id), "frame_type": frame_type},
                    )
                except Exception as exc:
                    await self._report_delivery_result(
                        delivery_id,
                        status="failed",
                        error={"message": str(exc), "type": exc.__class__.__name__},
                        metadata={"provider_type": "wechat", "chat_id": _mask(chat_id), "frame_type": frame_type},
                    )
                    logger.warning("MeetWeChat direct notice send failed chat=%s error=%s", _mask(chat_id), exc)
            return
        if frame_type == "delivery.message":
            message = payload.get("payload", {}) or {}
            role = str(message.get("role") or "").strip().lower()
            if role and role != "assistant":
                return
            text = str(message.get("content") or "").strip()
            if not text:
                return
            if pending is None:
                final_key = self._final_delivery_key(
                    chat_id,
                    message_id=str(message.get("message_id") or ""),
                    stream_key="",
                )
                if final_key and final_key in self._queued_final_keys:
                    return
                try:
                    await self._send_direct_text(chat_id, text)
                    if final_key:
                        self._mark_final_delivery(final_key)
                    await self._report_delivery_result(
                        delivery_id,
                        status="sent",
                        metadata={"provider_type": "wechat", "chat_id": _mask(chat_id), "frame_type": frame_type},
                    )
                except Exception as exc:
                    await self._report_delivery_result(
                        delivery_id,
                        status="failed",
                        error={"message": str(exc), "type": exc.__class__.__name__},
                        metadata={"provider_type": "wechat", "chat_id": _mask(chat_id), "frame_type": frame_type},
                    )
                    logger.warning("MeetWeChat direct message send failed chat=%s error=%s", _mask(chat_id), exc)
                return
            if not self._remember_final_delivery(
                chat_id,
                message_id=str(message.get("message_id") or ""),
                stream_key="",
            ):
                return
            self._enqueue_outbound(pending, text)
            return
        if frame_type != "delivery.run_event":
            return
        event = payload.get("payload", {}) or {}
        event_type = str(event.get("type") or "")
        body = event.get("payload") if isinstance(event.get("payload"), dict) else event
        stream_id = str(event.get("stream_id") or "")
        stream_key = self._stream_key(chat_id, stream_id)

        if event_type == "confirm.requested":
            if pending is not None:
                request_id = str(body.get("request_id") or "")
                self._pending_confirm_requests[pending.participant_key] = request_id
                text = f"{body.get('content', '')}\n确认编号: {request_id}\n请回复 y/yes/确认 或 n/no/拒绝。"
                self._enqueue_outbound(pending, text, delay_before_send=False)
            return
        if event_type == "confirm.resolved":
            request_id = str(body.get("request_id") or "")
            for key, value in list(self._pending_confirm_requests.items()):
                if not request_id or value == request_id:
                    self._pending_confirm_requests.pop(key, None)
            return
        if event_type == "human_input.requested":
            if pending is not None:
                request_id = str(body.get("request_id") or "")
                options = [str(item).strip() for item in body.get("options", []) if str(item).strip()]
                self._pending_human_input_requests[pending.participant_key] = {
                    "request_id": request_id,
                    "options": options,
                }
                option_lines = "\n".join(f"{index}. {option}" for index, option in enumerate(options, start=1))
                suffix = f"\n{option_lines}" if option_lines else ""
                text = f"{body.get('question', '')}{suffix}\n请回复编号或直接输入内容。\n请求编号: {request_id}"
                self._enqueue_outbound(pending, text, delay_before_send=False)
            return
        if event_type == "human_input.resolved":
            request_id = str(body.get("request_id") or "")
            for key, value in list(self._pending_human_input_requests.items()):
                if not request_id or value.get("request_id") == request_id:
                    self._pending_human_input_requests.pop(key, None)
            return
        if event_type == "assistant.progress_notice":
            content = str(body.get("content") or body.get("text") or "").strip()
            if not content:
                return
            if pending is not None:
                self._enqueue_outbound(
                    pending,
                    content,
                    delay_before_send=False,
                    complete_pending=False,
                )
            else:
                try:
                    await self._send_direct_text(chat_id, content)
                    await self._report_delivery_result(
                        delivery_id,
                        status="sent",
                        metadata={"provider_type": "wechat", "chat_id": _mask(chat_id), "frame_type": frame_type},
                    )
                except Exception as exc:
                    await self._report_delivery_result(
                        delivery_id,
                        status="failed",
                        error={"message": str(exc), "type": exc.__class__.__name__},
                        metadata={"provider_type": "wechat", "chat_id": _mask(chat_id), "frame_type": frame_type},
                    )
                    logger.warning("MeetWeChat direct notice send failed chat=%s error=%s", _mask(chat_id), exc)
            return
        if event_type in {"reasoning.delta", "operation.updated", "activity.status"}:
            return
        if event_type == "message.delta":
            if str(body.get("channel") or "") in {"", "answer"}:
                self._append_stream_buffer(stream_key, str(body.get("delta") or body.get("content") or ""))
            return
        if event_type == "message.completed":
            message = body.get("message", {}) if isinstance(body.get("message"), dict) else body
            buffered = "".join(self._stream_buffers.pop(stream_key, [])) if stream_key else ""
            text = str(message.get("content") or "").strip() or buffered
            if pending is None:
                return
            if not self._remember_final_delivery(
                chat_id,
                message_id=str(message.get("message_id") or ""),
                stream_key=stream_key,
            ):
                return
            self._enqueue_outbound(pending, text)

    def _final_delivery_key(self, chat_id: str, *, message_id: str = "", stream_key: str = "") -> str:
        key = str(message_id or stream_key or "").strip()
        if not key:
            return ""
        return f"{chat_id}:{key}"

    def _mark_final_delivery(self, scoped_key: str) -> None:
        if not scoped_key:
            return
        if len(self._queued_final_keys) > 4096:
            self._queued_final_keys.clear()
        self._queued_final_keys.add(scoped_key)

    def _remember_final_delivery(self, chat_id: str, *, message_id: str = "", stream_key: str = "") -> bool:
        scoped_key = self._final_delivery_key(chat_id, message_id=message_id, stream_key=stream_key)
        if not scoped_key:
            return True
        if scoped_key in self._queued_final_keys:
            return False
        self._mark_final_delivery(scoped_key)
        return True

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
        content = markdown_to_plain_text(text)
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
        content = markdown_to_plain_text(text)
        if not chat_id or not content:
            return
        limit = _safe_positive_int(self._config.get("meetwechat_max_text_chars"), DEFAULT_MAX_TEXT_CHARS)
        fragments = split_text_naturally(content, limit=limit)
        seed = hashlib.sha256(f"{chat_id}:{content}:{datetime.now(timezone.utc).isoformat()}".encode("utf-8")).hexdigest()[:16]
        for index, fragment in enumerate(fragments, start=1):
            await self._send_direct_fragment_with_retry(
                chat_id=chat_id,
                fragment=fragment,
                idempotency_key=f"meetyou:direct:{seed}:{index}",
            )

    async def _send_direct_fragment_with_retry(self, *, chat_id: str, fragment: str, idempotency_key: str) -> None:
        max_attempts = _safe_positive_int(
            self._config.get("meetwechat_direct_send_max_attempts"),
            DEFAULT_DIRECT_SEND_MAX_ATTEMPTS,
        )
        base_delay = _safe_non_negative_float(
            self._config.get("meetwechat_direct_send_retry_base_seconds"),
            DEFAULT_DIRECT_SEND_RETRY_BASE_SECONDS,
        )
        max_delay = _safe_non_negative_float(
            self._config.get("meetwechat_direct_send_retry_max_seconds"),
            DEFAULT_DIRECT_SEND_RETRY_MAX_SECONDS,
        )
        for attempt in range(max_attempts):
            try:
                await self._wait_global_send_slot()
                result = await asyncio.wait_for(
                    self._client.send_text(
                        chat_id=chat_id,
                        text=fragment,
                        idempotency_key=idempotency_key,
                        is_group_mention=False,
                    ),
                    timeout=self._send_timeout_seconds,
                )
                self._check_send_result(result)
                return
            except Exception as exc:
                if attempt >= max_attempts - 1 or not self._is_transient_send_error(exc):
                    raise
                delay = min(max_delay, base_delay * (2**attempt))
                if delay > 0:
                    await self._sleep(delay)

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
                if isinstance(exc, MeetWeChatSendBlocked):
                    detail = f"send blocked: {exc}"
                else:
                    detail = f"{exc.__class__.__name__}: {exc}".strip()
                logger.warning(
                    "MeetWeChat send failed chat=%s event=%s error=%s",
                    _mask(item.pending.event.chat_id),
                    _mask(item.pending.event.event_id),
                    detail,
                )
                if item.complete_pending:
                    self._complete_pending(
                        item.pending.event.chat_id,
                        False,
                        detail or "send failed",
                        terminal=isinstance(exc, MeetWeChatSendBlocked),
                    )
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
        content = markdown_to_plain_text(text)
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
        if isinstance(exc, MeetWeChatSendUncertain):
            return True
        if isinstance(exc, asyncio.TimeoutError):
            return True
        if isinstance(exc, MeetWeChatHTTPError):
            return exc.status == 429 or exc.status >= 500
        return isinstance(exc, (ConnectionError, OSError))

    def _check_send_result(self, result: MeetWeChatSendResult) -> None:
        if result.ok:
            return
        if result.status in _BLOCKED_SEND_STATUSES:
            raise MeetWeChatSendBlocked(result)
        status = str(result.status or "").strip().lower()
        detail = str(result.detail or "").strip().lower()
        if status in {"failed", "timeout", "unknown", "pending"} or any(
            marker in detail
            for marker in (
                "sidecar",
                "unreachable",
                "timeout",
                "timed out",
                "connection",
                "temporarily",
                "dispatcher",
            )
        ):
            raise MeetWeChatSendUncertain(result)
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
        endpoint_connection_factory: Callable[..., Any] = EndpointRuntimeConnection,
    ):
        self._event_bus = event_bus
        self._interaction_responses = InteractionResponseService(event_bus)
        self._core_session_manager = session_manager
        self._config = config
        self._endpoint_connection_factory = endpoint_connection_factory
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
        self._output_adapter.set_delivery_result_sender(self._send_delivery_result)
        self._endpoint_connections: dict[str, Any] = {}
        self._provider_endpoint_connection: Any | None = None
        self._endpoint_connection_last_used: dict[str, float] = {}
        self._gateway_endpoint_idle_ttl_seconds = _safe_positive_int(
            config.get("meetwechat_gateway_endpoint_idle_ttl_seconds"),
            DEFAULT_GATEWAY_ENDPOINT_IDLE_TTL_SECONDS,
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

        self._core_base_url = resolve_core_base_url(self._config)
        self._core_access_token = str(self._config.get("gateway_access_token") or "").strip()

    @property
    def _provider_endpoint_id(self) -> str:
        return "wechat.provider.ui"

    def _address_payload(self, *, chat_id: str, chat_type: str = "", display_name: str = "") -> dict[str, Any]:
        normalized_chat_id = str(chat_id or "").strip()
        normalized_type = str(chat_type or "private").strip().lower() or "private"
        address_type = "group" if normalized_type == "group" else "direct"
        return {
            "address_id": f"addr.wechat.{address_type}.{normalized_chat_id}",
            "provider_type": "wechat",
            "address_type": address_type,
            "external_ref": normalized_chat_id,
            "display_name": display_name or f"WeChat {normalized_type} {_mask(normalized_chat_id)}",
            "workspace_ids": ["personal"],
            "status": "sendable",
            "capabilities": ["receive_message"],
            "supports_markdown": False,
            "metadata": {"chat_type": normalized_type, "supports_markdown": False},
        }

    async def _send_delivery_result(
        self,
        *,
        delivery_id: str,
        status: str,
        error: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        connection = await self._ensure_provider_endpoint_connection()
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

    async def _discover_address_snapshot(self) -> list[dict[str, Any]]:
        addresses: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            for item in await self._client.list_chats():
                if not isinstance(item, dict):
                    continue
                chat_id = str(item.get("chat_id") or item.get("id") or "").strip()
                if not chat_id:
                    continue
                addresses.append(
                    self._address_payload(
                        chat_id=chat_id,
                        chat_type=str(item.get("chat_type") or item.get("type") or "private"),
                        display_name=str(item.get("display_name") or item.get("name") or ""),
                    )
                )
        return addresses

    async def _get_provider_endpoint_connection(self) -> Any:
        if self._provider_endpoint_connection is None:
            self._provider_endpoint_connection = self._endpoint_connection_factory(
                base_url=self._core_base_url,
                provider_id="meetwechat-provider",
                provider_type="wechat",
                display_name="MeetWeChat Provider",
                workspace_id="personal",
                access_token=self._core_access_token,
                thread_title="MeetWeChat Provider",
                endpoint_id=self._provider_endpoint_id,
                endpoint_addresses=await self._discover_address_snapshot(),
                supports_markdown=False,
                bind_thread=False,
                event_handler=lambda payload: self._output_adapter.send_runtime_event("", payload),
            )
        await self._provider_endpoint_connection.start()
        return self._provider_endpoint_connection

    async def run(self) -> None:
        self._closed = False
        self._persistent_workers = True
        await self._client.init()
        await self._get_provider_endpoint_connection()
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
        for client in self._endpoint_connections.values():
            close = getattr(client, "close", None)
            if callable(close):
                await close()
        self._endpoint_connections.clear()
        if self._provider_endpoint_connection is not None:
            close = getattr(self._provider_endpoint_connection, "close", None)
            if callable(close):
                await close()
            self._provider_endpoint_connection = None
        self._endpoint_connection_last_used.clear()
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
                if events:
                    await self.handle_events(events)
                    if not self._events_are_complete_for_cursor_advance(events):
                        logger.warning(
                            "MeetWeChat cursor held because %s event(s) are not complete",
                            len(events),
                        )
                        await asyncio.sleep(backoff_seconds)
                        backoff_seconds = min(backoff_seconds * 2, DEFAULT_MAX_ERROR_BACKOFF_SECONDS)
                        continue
                if cursor:
                    self._cursor = cursor
                backoff_seconds = base_backoff
                await self._close_idle_endpoint_connections()
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

    def _events_are_complete_for_cursor_advance(self, events: list[MeetWeChatEvent]) -> bool:
        for event in events:
            if not event.event_id:
                continue
            status = self._state_store.get_event_status(event.event_id, identity_key=_event_identity_key(event))
            if status not in {"acked", "sent", "skipped", "read_only", "blocked", "submitted"}:
                return False
        return True

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
        identity_key = _event_identity_key(event)
        status = self._state_store.get_event_status(event.event_id, identity_key=identity_key)
        if status in {"acked", "sent", "skipped", "read_only", "blocked", "submitted"}:
            await self._ack_event(event.event_id, status=status)
            return
        if event.is_self or event.content_type != "text" or not event.text.strip():
            await self._state_store.mark_event_status(
                event.event_id,
                "skipped",
                chat_id=event.chat_id,
                identity_key=identity_key,
            )
            await self._ack_event(event.event_id, status="skipped")
            return

        mode = self._policy.mode_for(event)
        if mode in {"mute", "manual_only"}:
            await self._state_store.mark_event_status(
                event.event_id,
                "skipped",
                chat_id=event.chat_id,
                reason=mode,
                identity_key=identity_key,
            )
            await self._ack_event(event.event_id, status="skipped")
            return
        participant_key = self._output_adapter.participant_key(event)
        text = str(event.text or "").strip()

        confirm_value = _parse_confirm_response(text)
        pending_confirm = self._output_adapter.get_pending_confirm_request(participant_key)
        if confirm_value is not None and pending_confirm:
            client = await self._get_endpoint_connection(event)
            await self._submit_confirm(client, pending_confirm, confirm_value, event)
            self._output_adapter.clear_pending_confirm_request(participant_key, pending_confirm)
            await self._state_store.mark_event_status(
                event.event_id,
                "sent",
                chat_id=event.chat_id,
                identity_key=identity_key,
            )
            await self._ack_event(event.event_id, status="sent")
            return

        pending_human_input = self._output_adapter.resolve_human_input(participant_key, text)
        if pending_human_input is not None:
            client = await self._get_endpoint_connection(event)
            await self._submit_human_input(client, pending_human_input, event)
            await self._state_store.mark_event_status(
                event.event_id,
                "sent",
                chat_id=event.chat_id,
                identity_key=identity_key,
            )
            await self._ack_event(event.event_id, status="sent")
            return

        if event.chat_type == "group" and not event.is_group_mention and mode != "auto":
            await self._state_store.mark_event_status(
                event.event_id,
                "skipped",
                chat_id=event.chat_id,
                reason="group_not_mentioned",
                identity_key=identity_key,
            )
            await self._ack_event(event.event_id, status="skipped")
            return

        await self._state_store.mark_event_status(
            event.event_id,
            "processing",
            chat_id=event.chat_id,
            identity_key=identity_key,
        )
        client = await self._get_endpoint_connection(event)
        with contextlib.suppress(Exception):
            await client.upsert_address(
                self._address_payload(
                    chat_id=event.chat_id,
                    chat_type=event.chat_type,
                    display_name=f"MeetWeChat {event.chat_type} {_mask(event.chat_id)}",
                )
            )
        await self._sleep(self._policy.merge_window_seconds)
        allow_send = self._policy.allow_send(event)
        future = self._output_adapter.begin_event(event, allow_send=allow_send)
        try:
            message_response = await client.send_message(
                self._format_inbound_text(event),
                metadata=self._metadata_for(event),
                preferred_mode=_infer_preferred_mode(text),
                endpoint_message_id=identity_key,
            )
            await self._remember_endpoint_connection_thread(event, client)
        except Exception as exc:
            self._output_adapter.discard_pending(event.chat_id, event.event_id)
            reason = f"bridge:{exc.__class__.__name__}"
            logger.warning(
                "MeetWeChat Core bridge failed chat=%s event=%s error=%s:%s",
                _mask(event.chat_id),
                _mask(event.event_id),
                exc.__class__.__name__,
                exc,
            )
            await self._state_store.mark_event_status(
                event.event_id,
                "failed",
                chat_id=event.chat_id,
                reason=reason,
                identity_key=identity_key,
            )
            return
        core_message_id = str((message_response or {}).get("message_id") or "")
        if bool((message_response or {}).get("idempotent_replay")):
            self._output_adapter.discard_pending(event.chat_id, event.event_id)
            await self._state_store.mark_event_status(
                event.event_id,
                "submitted",
                chat_id=event.chat_id,
                reason="core_idempotent_replay",
                identity_key=identity_key,
                core_message_id=core_message_id,
            )
            await self._ack_event(event.event_id, status="submitted")
            return
        await self._state_store.mark_event_status(
            event.event_id,
            "submitted",
            chat_id=event.chat_id,
            reason="core_accepted",
            identity_key=identity_key,
            core_message_id=core_message_id,
        )
        try:
            result = await asyncio.wait_for(future, timeout=self._policy.reply_timeout_seconds)
        except Exception as exc:
            self._output_adapter.discard_pending(event.chat_id, event.event_id)
            reason = f"reply:{exc.__class__.__name__}"
            logger.warning(
                "MeetWeChat reply delivery wait failed chat=%s event=%s error=%s:%s",
                _mask(event.chat_id),
                _mask(event.event_id),
                exc.__class__.__name__,
                exc,
            )
            await self._state_store.mark_event_status(
                event.event_id,
                "submitted",
                chat_id=event.chat_id,
                reason=reason,
                identity_key=identity_key,
                core_message_id=core_message_id,
            )
            await self._ack_event(event.event_id, status="submitted")
            return
        if not bool(result.get("ok")):
            reason = str(result.get("detail") or "reply")
            if bool(result.get("terminal")):
                await self._state_store.mark_event_status(
                    event.event_id,
                    "blocked",
                    chat_id=event.chat_id,
                    reason=reason,
                    identity_key=identity_key,
                    core_message_id=core_message_id,
                )
                await self._ack_event(event.event_id, status="blocked")
                return
            await self._state_store.mark_event_status(
                event.event_id,
                "submitted",
                chat_id=event.chat_id,
                reason=reason,
                identity_key=identity_key,
                core_message_id=core_message_id,
            )
            await self._ack_event(event.event_id, status="submitted")
            return
        final_status = "sent" if allow_send else "read_only"
        await self._state_store.mark_event_status(
            event.event_id,
            final_status,
            chat_id=event.chat_id,
            identity_key=identity_key,
            core_message_id=core_message_id,
        )
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
        if status != "failed":
            await self._state_store.mark_events_acked(clean_ids)

    def _conversation_key(self, event: MeetWeChatEvent) -> str:
        prefix = "group" if event.chat_type == "group" else "chat"
        return f"wechat:meetwechat:{prefix}:{event.chat_id}"

    async def _close_idle_endpoint_connections(self) -> None:
        if self._gateway_endpoint_idle_ttl_seconds <= 0 or not self._endpoint_connections:
            return
        now = asyncio.get_running_loop().time()
        stale_keys = [
            key
            for key, last_used in self._endpoint_connection_last_used.items()
            if now - float(last_used or 0) >= self._gateway_endpoint_idle_ttl_seconds
        ]
        for conversation_key in stale_keys:
            client = self._endpoint_connections.pop(conversation_key, None)
            self._endpoint_connection_last_used.pop(conversation_key, None)
            if client is None:
                continue
            close = getattr(client, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    await close()

    async def _get_endpoint_connection(self, event: MeetWeChatEvent) -> Any:
        conversation_key = self._conversation_key(event)
        client = self._endpoint_connections.get(conversation_key)
        if client is None:
            digest = hashlib.sha256(conversation_key.encode("utf-8")).hexdigest()[:20]
            thread_id = self._state_store.get_thread_id(conversation_key)
            client = self._endpoint_connection_factory(
                base_url=self._core_base_url,
                provider_id=f"meetwechat-{digest}",
                provider_type="wechat",
                display_name=f"MeetWeChat {event.chat_type} {_mask(event.chat_id)}",
                workspace_id="personal",
                access_token=self._core_access_token,
                thread_title=f"MeetWeChat {event.chat_type} {_mask(event.chat_id)}",
                thread_id=thread_id,
                endpoint_id=self._provider_endpoint_id,
                conversation_key=conversation_key,
                address_id=self._address_payload(
                    chat_id=event.chat_id,
                    chat_type=event.chat_type,
                    display_name=f"MeetWeChat {event.chat_type} {_mask(event.chat_id)}",
                ).get("address_id", ""),
                thread_strategy="per_conversation",
                supports_markdown=False,
                event_handler=lambda payload, chat_id=event.chat_id: self._output_adapter.send_runtime_event(
                    chat_id,
                    payload,
                ),
            )
            self._endpoint_connections[conversation_key] = client
        await client.start()
        self._endpoint_connection_last_used[conversation_key] = asyncio.get_running_loop().time()
        thread_id = str(getattr(client, "thread_id", "") or "")
        if thread_id:
            await self._state_store.set_thread_id(conversation_key, thread_id)
        return client

    async def _remember_endpoint_connection_thread(self, event: MeetWeChatEvent, client: Any) -> None:
        thread_id = str(getattr(client, "thread_id", "") or "")
        if not thread_id:
            return
        await self._state_store.set_thread_id(self._conversation_key(event), thread_id)

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
            "response_transport": "non_streaming_endpoint_provider",
            "supports_streaming_reply": False,
            "supports_markdown": False,
            "progress_notice_policy": "prefer_before_nontrivial_final",
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
