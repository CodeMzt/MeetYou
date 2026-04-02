"""
Feishu output adapter.
"""

import asyncio
import json
import logging
from time import monotonic

try:
    import aiohttp
except ImportError:  # pragma: no cover - optional dependency
    aiohttp = None

from core.io_protocol import EventType, StreamEventType

logger = logging.getLogger("meetyou.feishu_output")


class _FallbackClientSession:
    async def close(self):
        return None


class FeishuOutputAdapter:
    _TOKEN_REFRESH_SKEW_SECONDS = 60
    _FALLBACK_TOKEN_TTL_SECONDS = 300

    def __init__(self, config):
        self._config = config
        self._session: aiohttp.ClientSession | None = None
        self._tenant_access_token = ""
        self._tenant_access_token_expire_at = 0.0
        self._token_lock = asyncio.Lock()
        self._stream_buffers: dict[str, list[str]] = {}

    async def init(self):
        if self._session is None:
            self._session = aiohttp.ClientSession() if aiohttp is not None else _FallbackClientSession()

    async def close(self):
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._clear_token()

    def _clear_token(self):
        self._tenant_access_token = ""
        self._tenant_access_token_expire_at = 0.0

    def _reset_stream_buffer(self, stream_id: str):
        if stream_id:
            self._stream_buffers[stream_id] = []

    def _append_stream_buffer(self, stream_id: str, content: str):
        if stream_id:
            self._stream_buffers.setdefault(stream_id, []).append(content)

    async def _flush_stream_buffer(self, chat_id: str, stream_id: str, tail: str = ""):
        if not stream_id:
            if tail:
                await self._send_text(chat_id, tail)
            return
        text = "".join(self._stream_buffers.pop(stream_id, []))
        if tail:
            text += tail
        if text:
            await self._send_text(chat_id, text)

    def _has_valid_token(self) -> bool:
        return bool(
            self._tenant_access_token
            and monotonic() < self._tenant_access_token_expire_at
        )

    @staticmethod
    def _extract_token_ttl_seconds(data: dict) -> int:
        raw_ttl = data.get("expire") or data.get("expires_in") or 0
        try:
            ttl = int(raw_ttl)
        except (TypeError, ValueError):
            ttl = 0
        return ttl if ttl > 0 else FeishuOutputAdapter._FALLBACK_TOKEN_TTL_SECONDS

    @staticmethod
    def _is_invalid_token_response(status: int, body: str) -> bool:
        if status in {401, 403}:
            return True
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        code = payload.get("code")
        message = str(payload.get("msg") or payload.get("message") or body)
        return code == 99991663 or "Invalid access token" in message

    async def _ensure_token(self, force_refresh: bool = False) -> bool:
        if not force_refresh and self._has_valid_token():
            return True
        if self._session is None:
            await self.init()
        app_id = self._config.get("feishu_app_id") or ""
        app_secret = self._config.get("feishu_app_secret") or ""
        if not app_id or not app_secret:
            return False

        async with self._token_lock:
            if not force_refresh and self._has_valid_token():
                return True

            async with self._session.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            ) as resp:
                data = await resp.json()

            if data.get("code", 0) != 0:
                self._clear_token()
                logger.error("Feishu tenant_access_token fetch failed: %s", data)
                return False

            token = str(data.get("tenant_access_token", "")).strip()
            if not token:
                self._clear_token()
                logger.error("Feishu tenant_access_token response missing token: %s", data)
                return False

            ttl = self._extract_token_ttl_seconds(data)
            refresh_after = max(ttl - self._TOKEN_REFRESH_SKEW_SECONDS, 1)
            self._tenant_access_token = token
            self._tenant_access_token_expire_at = monotonic() + refresh_after
            return True

    async def _send_text(self, chat_id: str, text: str):
        if not chat_id or not text:
            return

        if not await self._ensure_token():
            logger.info("Feishu credentials unavailable, skipping message send")
            return

        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }

        for attempt in range(2):
            if not self._tenant_access_token or self._session is None:
                logger.info("Feishu credentials unavailable, skipping message send")
                return

            headers = {
                "Authorization": f"Bearer {self._tenant_access_token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            async with self._session.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                headers=headers,
                json=payload,
            ) as resp:
                body = await resp.text()

            if resp.status < 400:
                return

            if attempt == 0 and self._is_invalid_token_response(resp.status, body):
                logger.warning("Feishu access token expired, refreshing and retrying send")
                self._clear_token()
                if await self._ensure_token(force_refresh=True):
                    continue

            logger.error("Feishu message send failed: %s %s", resp.status, body)
            return

    async def send(self, event):
        chat_id = event.target.id or event.source.id
        stream_event = event.metadata.get("stream_event", "")
        activity_kind = str(event.metadata.get("activity_kind") or "").strip().lower()

        if event.type == EventType.CONFIRM_REQUEST.value:
            request_id = getattr(event, "request_id", "")
            await self._send_text(
                chat_id,
                f"{event.content}\n确认编号: {request_id}\n请回复 y/yes/确认 或 n/no/拒绝。",
            )
            return

        if event.type == EventType.ERROR.value:
            if event.stream_id:
                self._stream_buffers.pop(event.stream_id, None)
            await self._send_text(chat_id, f"[系统错误] {event.content}")
            return

        if event.type == EventType.MESSAGE.value:
            if stream_event == StreamEventType.START.value:
                self._reset_stream_buffer(event.stream_id)
                return
            if stream_event == StreamEventType.CHUNK.value:
                self._append_stream_buffer(event.stream_id, str(event.content or ""))
                return
            if stream_event in {StreamEventType.END.value, StreamEventType.ERROR.value}:
                await self._flush_stream_buffer(
                    chat_id,
                    event.stream_id,
                    str(event.content or ""),
                )
                return
            await self._send_text(chat_id, str(event.content))
            return

        if event.type == EventType.STATUS.value:
            if activity_kind in {"search", "tool_chain"}:
                return
            if stream_event == StreamEventType.START.value:
                self._reset_stream_buffer(event.stream_id)
                return
            if stream_event in {StreamEventType.END.value, StreamEventType.ERROR.value}:
                await self._flush_stream_buffer(
                    chat_id,
                    event.stream_id,
                    str(event.content or ""),
                )
                return
            if event.content:
                await self._send_text(chat_id, str(event.content))
