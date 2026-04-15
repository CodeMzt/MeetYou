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
        self._pending_confirm_requests: dict[str, str] = {}
        self._pending_human_input_requests: dict[str, dict] = {}

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

    def get_pending_confirm_request(self, chat_id: str) -> str | None:
        return self._pending_confirm_requests.get(chat_id)

    def resolve_human_input(self, chat_id: str, raw_text: str) -> dict | None:
        payload = self._pending_human_input_requests.get(chat_id)
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

    async def send_client_event(self, chat_id: str, payload: dict):
        if payload.get("schema") != "meetyou.client.ws.v1":
            return
        kind = payload.get("kind")
        if kind == "error":
            error = payload.get("error", {}) or {}
            await self._send_text(chat_id, f"[系统错误] {error.get('message', '')}")
            return
        if kind != "event":
            return

        event = payload.get("event", {}) or {}
        event_type = str(event.get("type") or "")
        stream_id = str(event.get("stream_id") or "")
        stream_key = f"{chat_id}:{stream_id}" if stream_id else ""

        if event_type == "confirm.requested":
            request_id = str(event.get("request_id") or "")
            self._pending_confirm_requests[chat_id] = request_id
            await self._send_text(
                chat_id,
                f"{event.get('content', '')}\n确认编号: {request_id}\n请回复 y/yes/确认 或 n/no/拒绝。",
            )
            return

        if event_type == "confirm.resolved":
            self._pending_confirm_requests.pop(chat_id, None)
            return

        if event_type == "human_input.requested":
            request_id = str(event.get("request_id") or "")
            options = [str(item).strip() for item in event.get("options", []) if str(item).strip()]
            self._pending_human_input_requests[chat_id] = {
                "request_id": request_id,
                "options": options,
            }
            option_lines = "\n".join(f"{index}. {option}" for index, option in enumerate(options, start=1))
            suffix = f"\n{option_lines}" if option_lines else ""
            await self._send_text(
                chat_id,
                f"{event.get('question', '')}{suffix}\n输入编号或直接回复内容。\n请求编号: {request_id}",
            )
            return

        if event_type == "human_input.resolved":
            self._pending_human_input_requests.pop(chat_id, None)
            return

        if event_type == "message.created":
            return

        if event_type == "reasoning.delta":
            return

        # Suppress routine runtime/activity chatter in Feishu so the chat only
        # shows user-relevant replies and explicit interaction prompts.
        if event_type == "activity.status":
            return

        if event_type == "message.delta":
            if str(event.get("channel") or "") != "answer":
                return
            self._append_stream_buffer(stream_key, str(event.get("delta") or ""))
            return

        if event_type == "message.completed":
            message = event.get("message", {}) or {}
            await self._flush_stream_buffer(chat_id, stream_key, str(message.get("content") or ""))
            return

        if event_type == "operation.updated":
            return

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

        if event.type == EventType.HUMAN_INPUT_REQUEST.value:
            request_id = getattr(event, "request_id", "")
            prompt = str(getattr(event, "question", "") or event.content or "")
            options = [str(item).strip() for item in getattr(event, "options", []) if str(item).strip()]
            option_lines = "\n".join(f"{index}. {option}" for index, option in enumerate(options, start=1))
            suffix = f"\n{option_lines}" if option_lines else ""
            await self._send_text(
                chat_id,
                f"{prompt}{suffix}\n输入编号或直接回复内容。\n请求编号: {request_id}",
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
            return
