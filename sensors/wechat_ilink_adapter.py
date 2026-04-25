"""
WeChat iLink Bot adapters.

The iLink transport is modeled as an external MeetYou client. Inbound messages
enter Core through the same Client API / client websocket chain used by the UI
and Feishu bridge; outbound replies are translated back to iLink sendmessage
calls with the latest per-user context_token.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hashlib
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from adapters.wechat_ilink_client import (
    DEFAULT_CHANNEL_VERSION,
    DEFAULT_ILINK_BASE_URL,
    WeChatIlinkClient,
    WeChatIlinkCredentials,
    WeChatIlinkError,
    WeChatIlinkSessionExpired,
    WeChatQRCodeInfo,
)
from clients.gateway_client import GatewayConversationClient
from core.interaction_response_service import InteractionResponseService
from core.io_protocol import EventType, StreamEventType
from core.persistence import atomic_write_json, atomic_write_text, load_json_with_recovery

logger = logging.getLogger("meetyou.wechat_ilink")

DEFAULT_TOKEN_FILE = "user/wechat_ilink_state.json"
DEFAULT_QR_OUTPUT_PATH = "user/wechat-ilink-login-qr.png"
DEFAULT_POLL_TIMEOUT_MS = 35000
DEFAULT_LOGIN_POLL_INTERVAL_SECONDS = 3
DEFAULT_MAX_TEXT_CHARS = 2000
DEFAULT_INBOUND_WORKER_COUNT = 4
DEFAULT_INBOUND_QUEUE_SIZE = 500
DEFAULT_OUTBOUND_WORKER_COUNT = 2
DEFAULT_OUTBOUND_QUEUE_SIZE = 500
DEFAULT_OUTBOUND_MIN_INTERVAL_MS = 250
DEFAULT_SEND_TIMEOUT_MS = 10000
DEFAULT_STATE_FLUSH_INTERVAL_MS = 500
DEFAULT_GATEWAY_CLIENT_IDLE_TTL_SECONDS = 600
_MAX_DEDUPE_KEYS = 4096
_SUPPORTED_LOGIN_WAIT_STATUSES = {"", "wait", "waiting", "scaned", "scanned", "confirmed_on_phone"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _mask(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 6:
        return "*" * len(text)
    return f"{text[:3]}***{text[-3:]}"


def _safe_positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _normalize_base_url(config) -> str:
    return str(config.get("wechat_ilink_base_url") or DEFAULT_ILINK_BASE_URL).strip() or DEFAULT_ILINK_BASE_URL


def _normalize_channel_version(config) -> str:
    return str(config.get("wechat_ilink_channel_version") or DEFAULT_CHANNEL_VERSION).strip() or DEFAULT_CHANNEL_VERSION


def _extract_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _extract_status(payload: dict[str, Any]) -> str:
    data = _extract_data(payload)
    return str(
        data.get("status")
        or data.get("qrcode_status")
        or data.get("state")
        or payload.get("status")
        or ""
    ).strip().lower()


def _credentials_from_login_payload(payload: dict[str, Any], fallback_base_url: str) -> WeChatIlinkCredentials | None:
    data = _extract_data(payload)
    merged = dict(data)
    for key in ("bot_token", "token", "access_token", "ilink_bot_id", "ilink_user_id", "baseurl", "base_url"):
        if key in payload and key not in merged:
            merged[key] = payload[key]
    merged.setdefault("baseurl", fallback_base_url)
    return WeChatIlinkCredentials.from_json(merged)


def _extract_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = _extract_data(payload)
    candidates = data.get("msgs") or data.get("messages") or payload.get("msgs") or []
    return [item for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []


def _extract_update_buf(payload: dict[str, Any]) -> str:
    data = _extract_data(payload)
    return str(data.get("get_updates_buf") or payload.get("get_updates_buf") or "")


def _extract_timeout_ms(payload: dict[str, Any], default: int) -> int:
    data = _extract_data(payload)
    return _safe_positive_int(data.get("longpolling_timeout_ms") or payload.get("longpolling_timeout_ms"), default)


def _message_field(message: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = message.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def _message_items(message: dict[str, Any]) -> list[dict[str, Any]]:
    items = message.get("item_list") or message.get("items") or []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _extract_text_items(message: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in _message_items(message):
        item_type = item.get("type")
        if item_type not in {1, "1", "text", "TEXT"}:
            continue
        text_item = item.get("text_item") if isinstance(item.get("text_item"), dict) else {}
        text = str(text_item.get("text") or item.get("text") or item.get("content") or "").strip()
        if text:
            result.append(text)
    return result


def split_text_naturally(text: str, *, limit: int = DEFAULT_MAX_TEXT_CHARS) -> list[str]:
    remaining = str(text or "")
    if not remaining:
        return []
    chunks: list[str] = []
    limit = max(int(limit or DEFAULT_MAX_TEXT_CHARS), 1)
    while len(remaining) > limit:
        boundary = max(remaining.rfind("\n", 0, limit), remaining.rfind(" ", 0, limit))
        if boundary <= 0 or boundary < limit // 2:
            boundary = limit
        chunk = remaining[:boundary].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[boundary:].strip()
    if remaining.strip():
        chunks.append(remaining.strip())
    return chunks


@dataclass(slots=True)
class WeChatIlinkState:
    credentials: WeChatIlinkCredentials | None
    get_updates_buf: str
    context_tokens: dict[str, dict[str, str]]
    dedupe_keys: list[str]


@dataclass(slots=True)
class _InboundWorkItem:
    message: dict[str, Any]
    account_id: str
    credentials: WeChatIlinkCredentials | None


@dataclass(slots=True)
class _OutboundTextItem:
    user_id: str
    text: str
    attempt: int = 0


class WeChatIlinkStateStore:
    def __init__(self, token_file: str = DEFAULT_TOKEN_FILE, *, flush_interval_ms: int = DEFAULT_STATE_FLUSH_INTERVAL_MS):
        self.path = Path(token_file or DEFAULT_TOKEN_FILE)
        self._lock = asyncio.Lock()
        self._state = self._load()
        self._dedupe_set = set(self._state.dedupe_keys)
        self._dirty = False
        self._flush_task: asyncio.Task | None = None
        self._flush_interval_seconds = max(_safe_positive_int(flush_interval_ms, DEFAULT_STATE_FLUSH_INTERVAL_MS), 50) / 1000

    def _empty_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "credentials": None,
            "get_updates_buf": "",
            "context_tokens": {},
            "dedupe_keys": [],
            "updated_at": "",
        }

    def _load(self) -> WeChatIlinkState:
        try:
            payload = load_json_with_recovery(
                str(self.path),
                validator=lambda value: isinstance(value, dict),
                default_factory=self._empty_payload,
            )
        except Exception as exc:
            logger.warning("读取 WeChat iLink 状态失败，将使用空状态: %s", exc)
            payload = self._empty_payload()
        context_tokens = payload.get("context_tokens")
        if not isinstance(context_tokens, dict):
            context_tokens = {}
        normalized_contexts: dict[str, dict[str, str]] = {}
        for account_id, user_tokens in context_tokens.items():
            if not isinstance(user_tokens, dict):
                continue
            normalized_contexts[str(account_id)] = {
                str(user_id): str(token)
                for user_id, token in user_tokens.items()
                if str(user_id).strip() and str(token).strip()
            }
        dedupe_keys = payload.get("dedupe_keys")
        if not isinstance(dedupe_keys, list):
            dedupe_keys = []
        return WeChatIlinkState(
            credentials=WeChatIlinkCredentials.from_json(payload.get("credentials")),
            get_updates_buf=str(payload.get("get_updates_buf") or ""),
            context_tokens=normalized_contexts,
            dedupe_keys=[str(item) for item in dedupe_keys[-_MAX_DEDUPE_KEYS:] if str(item).strip()],
        )

    def _to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "credentials": self._state.credentials.to_json() if self._state.credentials else None,
            "get_updates_buf": self._state.get_updates_buf,
            "context_tokens": self._state.context_tokens,
            "dedupe_keys": self._state.dedupe_keys[-_MAX_DEDUPE_KEYS:],
            "updated_at": _utcnow_iso(),
        }

    async def _persist(self) -> None:
        atomic_write_json(str(self.path), self._to_payload())
        with contextlib.suppress(Exception):
            os.chmod(self.path, 0o600)

    async def _mark_dirty_locked(self) -> None:
        self._dirty = True
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_later())

    async def _flush_later(self) -> None:
        await asyncio.sleep(self._flush_interval_seconds)
        await self.flush()

    async def flush(self) -> None:
        async with self._lock:
            if not self._dirty:
                return
            self._dirty = False
            await self._persist()

    async def close(self) -> None:
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
        await self.flush()

    def get_credentials(self) -> WeChatIlinkCredentials | None:
        return self._state.credentials

    async def set_credentials(self, credentials: WeChatIlinkCredentials) -> None:
        async with self._lock:
            self._state.credentials = credentials
            await self._persist()

    async def clear_session(self) -> None:
        async with self._lock:
            self._state.credentials = None
            self._state.get_updates_buf = ""
            self._state.context_tokens = {}
            self._state.dedupe_keys = []
            self._dedupe_set.clear()
            await self._persist()

    def get_update_buf(self) -> str:
        return self._state.get_updates_buf

    async def set_update_buf(self, value: str) -> None:
        async with self._lock:
            self._state.get_updates_buf = str(value or "")
            await self._mark_dirty_locked()

    def get_context_token(self, account_id: str, user_id: str) -> str:
        return self._state.context_tokens.get(account_id, {}).get(user_id, "")

    async def set_context_token(self, account_id: str, user_id: str, token: str) -> None:
        account = str(account_id or "default")
        user = str(user_id or "").strip()
        value = str(token or "").strip()
        if not user or not value:
            return
        async with self._lock:
            self._state.context_tokens.setdefault(account, {})[user] = value
            await self._mark_dirty_locked()

    async def remember_dedupe_key(self, key: str) -> bool:
        normalized = str(key or "").strip()
        if not normalized:
            return False
        async with self._lock:
            keys = self._state.dedupe_keys
            if normalized in self._dedupe_set:
                return True
            keys.append(normalized)
            self._dedupe_set.add(normalized)
            if len(keys) > _MAX_DEDUPE_KEYS:
                expired = keys[: len(keys) - _MAX_DEDUPE_KEYS]
                del keys[: len(keys) - _MAX_DEDUPE_KEYS]
                for item in expired:
                    self._dedupe_set.discard(item)
            await self._mark_dirty_locked()
            return False


class WeChatSessionManager:
    def __init__(
        self,
        *,
        config,
        client: WeChatIlinkClient,
        state_store: WeChatIlinkStateStore,
    ):
        self._config = config
        self._client = client
        self._state_store = state_store
        self._login_lock = asyncio.Lock()

    async def ensure_credentials(self) -> WeChatIlinkCredentials:
        credentials = self._state_store.get_credentials()
        if credentials is not None:
            return credentials
        async with self._login_lock:
            credentials = self._state_store.get_credentials()
            if credentials is not None:
                return credentials
            return await self._login_with_qrcode()

    async def invalidate(self) -> None:
        await self._state_store.clear_session()

    async def _login_with_qrcode(self) -> WeChatIlinkCredentials:
        poll_interval = _safe_positive_int(
            self._config.get("wechat_ilink_login_poll_interval_seconds"),
            DEFAULT_LOGIN_POLL_INTERVAL_SECONDS,
        )
        status_timeout_ms = _safe_positive_int(
            self._config.get("wechat_ilink_poll_timeout_ms"),
            DEFAULT_POLL_TIMEOUT_MS,
        ) + 5000
        while True:
            qr_info = await self._client.get_bot_qrcode(bot_type=3)
            await self._write_qrcode_artifact(qr_info)
            if not qr_info.qrcode:
                raise WeChatIlinkError("iLink 二维码响应缺少 qrcode 字段")
            logger.info("WeChat iLink 登录二维码已更新，请扫码确认。QR=%s", _mask(qr_info.qrcode))
            poll_base_url = _normalize_base_url(self._config)
            while True:
                await asyncio.sleep(poll_interval)
                payload = await self._client.get_qrcode_status(
                    qr_info.qrcode,
                    base_url=poll_base_url,
                    timeout_ms=status_timeout_ms,
                )
                credentials = _credentials_from_login_payload(payload, _normalize_base_url(self._config))
                if credentials is not None:
                    await self._state_store.set_credentials(credentials)
                    logger.info(
                        "WeChat iLink 登录成功: account=%s baseurl=%s",
                        credentials.account_id,
                        credentials.baseurl,
                    )
                    return credentials
                status = _extract_status(payload)
                if status in {"expired", "timeout", "cancelled", "canceled"}:
                    logger.info("WeChat iLink 登录二维码已过期，准备重新获取。")
                    break
                if status == "scaned_but_redirect":
                    data = _extract_data(payload)
                    redirect_host = str(data.get("redirect_host") or payload.get("redirect_host") or "").strip()
                    if redirect_host:
                        poll_base_url = f"https://{redirect_host}"
                        logger.info("WeChat iLink 登录轮询切换到 redirect host: %s", redirect_host)
                    continue
                if status not in _SUPPORTED_LOGIN_WAIT_STATUSES:
                    logger.info("WeChat iLink 登录状态: %s", status or "unknown")

    async def _write_qrcode_artifact(self, qr_info: WeChatQRCodeInfo) -> None:
        output_path = Path(self._config.get("wechat_ilink_qr_output_path") or DEFAULT_QR_OUTPUT_PATH)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        binary = _decode_qrcode_bytes(qr_info)
        if binary:
            output_path.write_bytes(binary)
            logger.info("WeChat iLink 登录二维码图片已写入: %s", output_path.as_posix())
            return
        text_path = output_path if output_path.suffix.lower() == ".txt" else output_path.with_suffix(f"{output_path.suffix}.txt")
        lines = [
            "WeChat iLink login QR information",
            f"updated_at={_utcnow_iso()}",
            f"qrcode={qr_info.qrcode}",
        ]
        if qr_info.qrcode_url:
            lines.append(f"qrcode_url={qr_info.qrcode_url}")
        atomic_write_text(str(text_path), "\n".join(lines) + "\n")
        logger.info("WeChat iLink 登录二维码信息已写入: %s", text_path.as_posix())


def _decode_qrcode_bytes(qr_info: WeChatQRCodeInfo) -> bytes:
    raw = qr_info.qrcode_data or ""
    if not raw and qr_info.qrcode_url.startswith("data:image/"):
        raw = qr_info.qrcode_url
    if not raw and qr_info.qrcode.startswith("data:image/"):
        raw = qr_info.qrcode
    if raw.startswith("data:image/"):
        raw = raw.split(",", 1)[-1]
    if not raw:
        return b""
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return b""


class WeChatLongPoller:
    def __init__(
        self,
        *,
        config,
        client: WeChatIlinkClient,
        session_manager: WeChatSessionManager,
        state_store: WeChatIlinkStateStore,
    ):
        self._config = config
        self._client = client
        self._session_manager = session_manager
        self._state_store = state_store
        self._timeout_ms = _safe_positive_int(config.get("wechat_ilink_poll_timeout_ms"), DEFAULT_POLL_TIMEOUT_MS)

    async def poll_once_with_cursor(self) -> tuple[list[dict[str, Any]], str]:
        credentials = await self._session_manager.ensure_credentials()
        try:
            payload = await self._client.get_updates(
                credentials,
                get_updates_buf=self._state_store.get_update_buf(),
                timeout_ms=self._timeout_ms + 5000,
            )
        except WeChatIlinkSessionExpired:
            await self._session_manager.invalidate()
            raise
        next_buf = _extract_update_buf(payload)
        self._timeout_ms = _extract_timeout_ms(payload, self._timeout_ms)
        return _extract_messages(payload), next_buf

    async def poll_once(self) -> list[dict[str, Any]]:
        messages, next_buf = await self.poll_once_with_cursor()
        await self._state_store.set_update_buf(next_buf)
        return messages


class WeChatOutputService:
    def __init__(
        self,
        *,
        config,
        client: WeChatIlinkClient,
        session_manager: WeChatSessionManager,
        state_store: WeChatIlinkStateStore,
    ):
        self._config = config
        self._client = client
        self._session_manager = session_manager
        self._state_store = state_store
        self._stream_buffers: dict[str, list[str]] = {}
        self._pending_confirm_requests: dict[str, str] = {}
        self._pending_human_input_requests: dict[str, dict[str, Any]] = {}
        self._outbound_queue: asyncio.Queue[_OutboundTextItem] = asyncio.Queue(
            maxsize=_safe_positive_int(config.get("wechat_ilink_outbound_queue_size"), DEFAULT_OUTBOUND_QUEUE_SIZE)
        )
        self._outbound_worker_count = min(
            _safe_positive_int(config.get("wechat_ilink_outbound_worker_count"), DEFAULT_OUTBOUND_WORKER_COUNT),
            8,
        )
        self._outbound_tasks: list[asyncio.Task] = []
        self._closed = False
        self._send_timeout_seconds = max(_safe_positive_int(config.get("wechat_ilink_send_timeout_ms"), DEFAULT_SEND_TIMEOUT_MS), 1000) / 1000
        self._min_interval_seconds = max(
            _safe_positive_int(config.get("wechat_ilink_outbound_min_interval_ms"), DEFAULT_OUTBOUND_MIN_INTERVAL_MS),
            0,
        ) / 1000
        self._last_send_at = 0.0
        self._rate_lock = asyncio.Lock()
        self._user_send_locks: dict[str, asyncio.Lock] = {}

    async def run(self) -> None:
        self._closed = False
        if self._outbound_tasks:
            return
        for index in range(self._outbound_worker_count):
            self._outbound_tasks.append(asyncio.create_task(self._outbound_worker_loop(index)))

    async def close(self) -> None:
        self._closed = True
        if self._outbound_queue is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._outbound_queue.join(), timeout=3)
        for task in self._outbound_tasks:
            task.cancel()
        if self._outbound_tasks:
            await asyncio.gather(*self._outbound_tasks, return_exceptions=True)
        self._outbound_tasks.clear()

    async def _outbound_worker_loop(self, index: int) -> None:
        del index
        while True:
            item = await self._outbound_queue.get()
            try:
                try:
                    await self._send_text_now(item.user_id, item.text)
                except WeChatIlinkSessionExpired:
                    await self._session_manager.invalidate()
                except Exception as exc:
                    if item.attempt < 2 and not self._closed:
                        await asyncio.sleep(min(2 ** item.attempt, 5))
                        await self._outbound_queue.put(_OutboundTextItem(item.user_id, item.text, item.attempt + 1))
                    else:
                        logger.warning("WeChat iLink outbound send failed user=%s: %s", _mask(item.user_id), exc)
            finally:
                self._outbound_queue.task_done()

    async def _respect_send_interval(self) -> None:
        if self._min_interval_seconds <= 0:
            return
        async with self._rate_lock:
            elapsed = time.monotonic() - self._last_send_at
            if elapsed < self._min_interval_seconds:
                await asyncio.sleep(self._min_interval_seconds - elapsed)
            self._last_send_at = time.monotonic()

    def get_pending_confirm_request(self, user_id: str) -> str | None:
        return self._pending_confirm_requests.get(user_id)

    def resolve_human_input(self, user_id: str, raw_text: str) -> dict[str, Any] | None:
        payload = self._pending_human_input_requests.get(user_id)
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

    def _stream_key(self, user_id: str, stream_id: str) -> str:
        return f"{user_id}:{stream_id}" if stream_id else ""

    def _reset_stream_buffer(self, stream_key: str) -> None:
        if stream_key:
            self._stream_buffers[stream_key] = []

    def _append_stream_buffer(self, stream_key: str, content: str) -> None:
        if stream_key:
            self._stream_buffers.setdefault(stream_key, []).append(content)

    async def _flush_stream_buffer(self, user_id: str, stream_key: str, tail: str = "") -> None:
        if not stream_key:
            if tail:
                await self._send_text(user_id, tail)
            return
        text = "".join(self._stream_buffers.pop(stream_key, []))
        if tail:
            text = tail
        if text:
            await self._send_text(user_id, text)

    async def send_client_event(self, user_id: str, payload: dict[str, Any]) -> None:
        if payload.get("schema") != "meetyou.client.ws.v1":
            return
        kind = payload.get("kind")
        if kind == "error":
            error = payload.get("error", {}) or {}
            await self._send_text(user_id, f"[系统错误] {error.get('message', '')}")
            return
        if kind != "event":
            return
        event = payload.get("event", {}) or {}
        event_type = str(event.get("type") or "")
        stream_id = str(event.get("stream_id") or "")
        stream_key = self._stream_key(user_id, stream_id)

        if event_type == "confirm.requested":
            request_id = str(event.get("request_id") or "")
            self._pending_confirm_requests[user_id] = request_id
            await self._send_text(
                user_id,
                f"{event.get('content', '')}\n确认编号: {request_id}\n请回复 y/yes/确认 或 n/no/拒绝。",
            )
            return
        if event_type == "confirm.resolved":
            self._pending_confirm_requests.pop(user_id, None)
            return
        if event_type == "human_input.requested":
            request_id = str(event.get("request_id") or "")
            options = [str(item).strip() for item in event.get("options", []) if str(item).strip()]
            self._pending_human_input_requests[user_id] = {
                "request_id": request_id,
                "options": options,
            }
            option_lines = "\n".join(f"{index}. {option}" for index, option in enumerate(options, start=1))
            suffix = f"\n{option_lines}" if option_lines else ""
            await self._send_text(
                user_id,
                f"{event.get('question', '')}{suffix}\n输入编号或直接回复内容。\n请求编号: {request_id}",
            )
            return
        if event_type == "human_input.resolved":
            self._pending_human_input_requests.pop(user_id, None)
            return
        if event_type in {"message.created", "reasoning.delta", "operation.updated"}:
            return
        if event_type == "activity.status":
            return
        if event_type == "message.delta":
            if str(event.get("channel") or "") == "answer":
                self._append_stream_buffer(stream_key, str(event.get("delta") or ""))
            return
        if event_type == "message.completed":
            message = event.get("message", {}) or {}
            await self._flush_stream_buffer(user_id, stream_key, str(message.get("content") or ""))

    async def _send_text(self, user_id: str, text: str) -> None:
        if not user_id or not text:
            return
        if self._outbound_tasks and not self._closed:
            await self._outbound_queue.put(_OutboundTextItem(user_id=user_id, text=text))
            return
        await self._send_text_now(user_id, text)

    async def _send_text_now(self, user_id: str, text: str) -> None:
        if not user_id or not text:
            return
        lock = self._user_send_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            credentials = await self._session_manager.ensure_credentials()
            context_token = self._state_store.get_context_token(credentials.account_id, user_id)
            if not context_token:
                logger.warning("WeChat iLink 缺少 context_token，无法主动回复 user=%s", _mask(user_id))
                return
            limit = _safe_positive_int(self._config.get("wechat_ilink_max_text_chars"), DEFAULT_MAX_TEXT_CHARS)
            for fragment in split_text_naturally(text, limit=limit):
                await self._respect_send_interval()
                try:
                    await asyncio.wait_for(
                        self._client.send_text(
                            credentials,
                            to_user_id=user_id,
                            context_token=context_token,
                            text=fragment,
                            client_id=f"meetyou-{uuid4().hex}",
                        ),
                        timeout=self._send_timeout_seconds,
                    )
                except WeChatIlinkSessionExpired:
                    await self._session_manager.invalidate()
                    return

    async def send(self, event) -> None:
        user_id = event.target.id or event.source.id
        stream_event = event.metadata.get("stream_event", "")
        activity_kind = str(event.metadata.get("activity_kind") or "").strip().lower()

        if event.type == EventType.CONFIRM_REQUEST.value:
            request_id = getattr(event, "request_id", "")
            await self._send_text(
                user_id,
                f"{event.content}\n确认编号: {request_id}\n请回复 y/yes/确认 或 n/no/拒绝。",
            )
            return
        if event.type == EventType.HUMAN_INPUT_REQUEST.value:
            request_id = getattr(event, "request_id", "")
            prompt = str(getattr(event, "question", "") or event.content or "")
            options = [str(item).strip() for item in getattr(event, "options", []) if str(item).strip()]
            option_lines = "\n".join(f"{index}. {option}" for index, option in enumerate(options, start=1))
            suffix = f"\n{option_lines}" if option_lines else ""
            await self._send_text(user_id, f"{prompt}{suffix}\n输入编号或直接回复内容。\n请求编号: {request_id}")
            return
        if event.type == EventType.ERROR.value:
            if event.stream_id:
                self._stream_buffers.pop(self._stream_key(user_id, event.stream_id), None)
            await self._send_text(user_id, f"[系统错误] {event.content}")
            return
        if event.type == EventType.MESSAGE.value:
            stream_key = self._stream_key(user_id, event.stream_id)
            if stream_event == StreamEventType.START.value:
                self._reset_stream_buffer(stream_key)
                return
            if stream_event == StreamEventType.CHUNK.value:
                self._append_stream_buffer(stream_key, str(event.content or ""))
                return
            if stream_event in {StreamEventType.END.value, StreamEventType.ERROR.value}:
                await self._flush_stream_buffer(user_id, stream_key, str(event.content or ""))
                return
            await self._send_text(user_id, str(event.content))
            return
        if event.type == EventType.STATUS.value:
            if activity_kind in {"search", "tool_chain"}:
                return
            stream_key = self._stream_key(user_id, event.stream_id)
            if stream_event == StreamEventType.START.value:
                self._reset_stream_buffer(stream_key)
                return
            if stream_event in {StreamEventType.END.value, StreamEventType.ERROR.value}:
                await self._flush_stream_buffer(user_id, stream_key, str(event.content or ""))


def _parse_confirm_response(text: str) -> bool | None:
    normalized = text.strip().lower()
    accepted_tokens = {"y", "yes", "确认", "同意", "允许"}
    rejected_tokens = {"n", "no", "拒绝", "取消", "不同意"}
    if normalized in accepted_tokens:
        return True
    if normalized in rejected_tokens:
        return False
    return None


def _infer_preferred_mode(text: str) -> str | None:
    normalized = str(text or "").strip().lower()
    if any(keyword in normalized for keyword in ("danxi", "旦夕", "fduhole", "论坛", "帖子", "webvpn")):
        return "danxi"
    return None


class WeChatInputAdapter:
    def __init__(
        self,
        event_bus,
        session_manager,
        config,
        *,
        ilink_client: WeChatIlinkClient | None = None,
        state_store: WeChatIlinkStateStore | None = None,
        ilink_session_manager: WeChatSessionManager | None = None,
        output_adapter: WeChatOutputService | None = None,
        gateway_client_factory: Callable[..., Any] = GatewayConversationClient,
    ):
        self._event_bus = event_bus
        self._interaction_responses = InteractionResponseService(event_bus)
        self._core_session_manager = session_manager
        self._config = config
        self._gateway_client_factory = gateway_client_factory
        self._client = ilink_client or WeChatIlinkClient(
            base_url=_normalize_base_url(config),
            channel_version=_normalize_channel_version(config),
        )
        self._state_store = state_store or WeChatIlinkStateStore(
            str(config.get("wechat_ilink_token_file") or DEFAULT_TOKEN_FILE)
        )
        self._ilink_session_manager = ilink_session_manager or WeChatSessionManager(
            config=config,
            client=self._client,
            state_store=self._state_store,
        )
        self._output_adapter = output_adapter or WeChatOutputService(
            config=config,
            client=self._client,
            session_manager=self._ilink_session_manager,
            state_store=self._state_store,
        )
        self._poller = WeChatLongPoller(
            config=config,
            client=self._client,
            session_manager=self._ilink_session_manager,
            state_store=self._state_store,
        )
        self._gateway_clients: dict[str, Any] = {}
        self._gateway_client_touched: dict[str, float] = {}
        self._gateway_client_idle_ttl_seconds = _safe_positive_int(
            config.get("wechat_ilink_gateway_client_idle_ttl_seconds"),
            DEFAULT_GATEWAY_CLIENT_IDLE_TTL_SECONDS,
        )
        self._poll_task: asyncio.Task | None = None
        self._inbound_workers: list[asyncio.Task] = []
        self._inbound_worker_count = min(
            _safe_positive_int(config.get("wechat_ilink_inbound_worker_count"), DEFAULT_INBOUND_WORKER_COUNT),
            16,
        )
        self._inbound_queue: asyncio.Queue[_InboundWorkItem] = asyncio.Queue(
            maxsize=_safe_positive_int(config.get("wechat_ilink_inbound_queue_size"), DEFAULT_INBOUND_QUEUE_SIZE)
        )
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._closed = False

        host = str(self._config.get("gateway_host") or "127.0.0.1").strip() or "127.0.0.1"
        if host in {"0.0.0.0", "::", "::0"}:
            host = "127.0.0.1"
        port = int(self._config.get("gateway_port") or 8000)
        self._gateway_base_url = f"http://{host}:{port}"
        self._gateway_access_token = str(self._config.get("gateway_access_token") or "").strip()

    async def run(self) -> None:
        self._closed = False
        await self._client.init()
        if hasattr(self._output_adapter, "run"):
            await self._output_adapter.run()
        if not self._inbound_workers:
            for index in range(self._inbound_worker_count):
                self._inbound_workers.append(asyncio.create_task(self._inbound_worker_loop(index)))
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._run_poll_loop())
        logger.info("WeChat iLink Bot 已启动后台长轮询。")

    async def close(self) -> None:
        self._closed = True
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        if self._inbound_queue is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._inbound_queue.join(), timeout=3)
        for task in self._inbound_workers:
            task.cancel()
        if self._inbound_workers:
            await asyncio.gather(*self._inbound_workers, return_exceptions=True)
        self._inbound_workers.clear()
        for client in self._gateway_clients.values():
            close = getattr(client, "close", None)
            if callable(close):
                await close()
        self._gateway_clients.clear()
        if hasattr(self._output_adapter, "close"):
            await self._output_adapter.close()
        await self._state_store.close()
        await self._client.close()

    async def _run_poll_loop(self) -> None:
        backoff_seconds = 2
        while not self._closed:
            try:
                messages, next_buf = await self._poller.poll_once_with_cursor()
                backoff_seconds = 2
                await self._enqueue_messages(messages)
                await self._state_store.set_update_buf(next_buf)
            except asyncio.CancelledError:
                raise
            except WeChatIlinkSessionExpired:
                logger.info("WeChat iLink 会话已过期，将等待重新扫码登录。")
                await asyncio.sleep(DEFAULT_LOGIN_POLL_INTERVAL_SECONDS)
            except WeChatIlinkError as exc:
                logger.warning("WeChat iLink 轮询失败: %s", exc)
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 30)
            except Exception:
                logger.exception("WeChat iLink 消息处理异常")
                await asyncio.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 30)

    async def _enqueue_messages(self, messages: list[dict[str, Any]]) -> None:
        credentials = self._state_store.get_credentials()
        account_id = credentials.account_id if credentials else "default"
        for message in messages:
            await self._inbound_queue.put(_InboundWorkItem(message=message, account_id=account_id, credentials=credentials))

    async def _inbound_worker_loop(self, index: int) -> None:
        del index
        while True:
            item = await self._inbound_queue.get()
            try:
                from_user_id = _message_field(item.message, "from_user_id", "from_user", "sender_id")
                lock_key = f"{item.account_id}:{from_user_id}" if from_user_id else "unknown"
                lock = self._conversation_locks.setdefault(lock_key, asyncio.Lock())
                async with lock:
                    await self._handle_message(item.message, account_id=item.account_id, credentials=item.credentials)
            except Exception:
                logger.exception("WeChat iLink 入站消息 worker 处理异常")
            finally:
                self._inbound_queue.task_done()

    async def handle_messages(self, messages: list[dict[str, Any]]) -> None:
        credentials = self._state_store.get_credentials()
        account_id = credentials.account_id if credentials else "default"
        for message in messages:
            await self._handle_message(message, account_id=account_id, credentials=credentials)

    async def _handle_message(
        self,
        message: dict[str, Any],
        *,
        account_id: str,
        credentials: WeChatIlinkCredentials | None,
    ) -> None:
        from_user_id = _message_field(message, "from_user_id", "from_user", "sender_id")
        if not from_user_id:
            logger.debug("WeChat iLink 消息缺少发送方字段，keys=%s", sorted(message.keys()))
            return
        if self._is_self_message(from_user_id, credentials):
            logger.debug("WeChat iLink 跳过 bot 自身消息 user=%s", _mask(from_user_id))
            return
        texts = _extract_text_items(message)
        if not texts:
            logger.debug(
                "WeChat iLink 跳过非文本消息 user=%s items=%s",
                _mask(from_user_id),
                len(message.get("item_list") or message.get("items") or []),
            )
            return
        message_id = _message_field(message, "message_id", "msg_id", "client_msg_id", "seq")
        session_id = _message_field(message, "session_id", "conversation_id", "chat_id")
        context_token = _message_field(message, "context_token")
        if context_token:
            await self._state_store.set_context_token(account_id, from_user_id, context_token)
        dedupe_key = self._dedupe_key(message, from_user_id, session_id, message_id, texts[0])
        if await self._remember_dedupe_key(dedupe_key):
            logger.debug("WeChat iLink 跳过重复消息 user=%s message_id=%s", _mask(from_user_id), _mask(message_id))
            return
        logger.info(
            "WeChat iLink 收到文本消息 user=%s message_id_present=%s text_items=%s context_token_present=%s",
            _mask(from_user_id),
            bool(message_id),
            len(texts),
            bool(context_token),
        )
        client = await self._get_gateway_client(account_id, from_user_id)

        text = "\n".join(texts).strip()
        confirm_value = _parse_confirm_response(text)
        pending_confirm = self._output_adapter.get_pending_confirm_request(from_user_id)
        if confirm_value is not None and pending_confirm:
            try:
                await client.submit_confirm_response(request_id=pending_confirm, accepted=confirm_value)
            except Exception:
                await client.send_command(
                    "confirm_response",
                    request_id=pending_confirm,
                    accepted=confirm_value,
                    metadata={"source": "wechat", "from_user_id": from_user_id},
                )
            return
        pending_human_input = self._output_adapter.resolve_human_input(from_user_id, text)
        if pending_human_input is not None:
            try:
                await client.submit_human_input_response(
                    request_id=pending_human_input.get("request_id", ""),
                    answer_text=pending_human_input.get("answer_text", ""),
                    selected_option=pending_human_input.get("selected_option"),
                )
            except Exception:
                await client.send_command(
                    "input_response",
                    request_id=pending_human_input.get("request_id", ""),
                    answer_text=pending_human_input.get("answer_text", ""),
                    selected_option=pending_human_input.get("selected_option"),
                    metadata={"source": "wechat", "from_user_id": from_user_id},
                )
            return
        await client.send_message(
            text,
            metadata={
                "source": "wechat",
                "transport": "ilink",
                "account_id": account_id,
                "from_user_id": from_user_id,
                "wechat_session_id": session_id,
                "wechat_message_id": message_id,
                "context_token_present": bool(context_token),
            },
            preferred_mode=_infer_preferred_mode(text),
            client_message_id=message_id or None,
        )

    def _is_self_message(self, from_user_id: str, credentials: WeChatIlinkCredentials | None) -> bool:
        normalized = str(from_user_id or "").strip()
        if normalized.endswith("@im.bot"):
            return True
        if credentials is None:
            return False
        # Tencent iLink's ilink_user_id is the human user who scanned the QR code,
        # so only the bot id should be treated as a self-message.
        return bool(credentials.ilink_bot_id and normalized == credentials.ilink_bot_id)

    def _dedupe_key(self, message: dict[str, Any], from_user_id: str, session_id: str, message_id: str, text: str) -> str:
        if message_id:
            return f"id:{message_id}"
        create_time = _message_field(message, "create_time", "create_time_ms", "timestamp")
        digest = hashlib.sha256(f"{from_user_id}\n{session_id}\n{create_time}\n{text}".encode("utf-8")).hexdigest()
        return f"hash:{digest}"

    async def _remember_dedupe_key(self, key: str) -> bool:
        return await self._state_store.remember_dedupe_key(key)

    async def _get_gateway_client(self, account_id: str, from_user_id: str) -> Any:
        conversation_key = f"wechat:account:{account_id}:user:{from_user_id}"
        await self._cleanup_idle_gateway_clients()
        client = self._gateway_clients.get(conversation_key)
        if client is None:
            digest = hashlib.sha256(conversation_key.encode("utf-8")).hexdigest()[:20]
            client = self._gateway_client_factory(
                base_url=self._gateway_base_url,
                client_id=f"wechat-{digest}",
                client_type="wechat",
                display_name=f"WeChat {from_user_id}",
                workspace_id="personal",
                access_token=self._gateway_access_token,
                thread_title=f"WeChat {from_user_id}",
                event_handler=lambda payload, user_id=from_user_id: self._output_adapter.send_client_event(user_id, payload),
            )
            self._gateway_clients[conversation_key] = client
        self._gateway_client_touched[conversation_key] = time.monotonic()
        await client.start()
        return client

    async def _cleanup_idle_gateway_clients(self) -> None:
        ttl = max(int(self._gateway_client_idle_ttl_seconds or DEFAULT_GATEWAY_CLIENT_IDLE_TTL_SECONDS), 1)
        now = time.monotonic()
        stale_keys = [
            key
            for key, touched_at in self._gateway_client_touched.items()
            if now - touched_at > ttl
        ]
        for key in stale_keys:
            client = self._gateway_clients.pop(key, None)
            self._gateway_client_touched.pop(key, None)
            close = getattr(client, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    await close()
