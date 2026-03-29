"""
飞书输出适配器。
"""

import json
import logging

import aiohttp

from core.io_protocol import EventType, StreamEventType

logger = logging.getLogger("meetyou.feishu_output")


class FeishuOutputAdapter:
    def __init__(self, config):
        self._config = config
        self._session: aiohttp.ClientSession | None = None
        self._tenant_access_token = ""
        self._stream_buffers: dict[str, list[str]] = {}

    async def init(self):
        if self._session is None:
            self._session = aiohttp.ClientSession()

    async def close(self):
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _ensure_token(self):
        if self._tenant_access_token:
            return
        if self._session is None:
            await self.init()
        app_id = self._config.get("feishu_app_id") or ""
        app_secret = self._config.get("feishu_app_secret") or ""
        if not app_id or not app_secret:
            return
        async with self._session.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        ) as resp:
            data = await resp.json()
        self._tenant_access_token = data.get("tenant_access_token", "")

    async def _send_text(self, chat_id: str, text: str):
        if not chat_id or not text:
            return
        await self._ensure_token()
        if not self._tenant_access_token or self._session is None:
            logger.info("飞书凭证缺失，跳过消息发送")
            return
        headers = {
            "Authorization": f"Bearer {self._tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        async with self._session.post(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            headers=headers,
            json=payload,
        ) as resp:
            if resp.status >= 400:
                body = await resp.text()
                logger.error(f"飞书消息发送失败: {resp.status} {body}")

    async def send(self, event):
        chat_id = event.target.id or event.source.id
        stream_event = event.metadata.get("stream_event", "")

        if event.type == EventType.CONFIRM_REQUEST.value:
            request_id = getattr(event, "request_id", "")
            await self._send_text(
                chat_id,
                f"{event.content}\n确认编号: {request_id}\n请回复 y/yes/确认 或 n/no/拒绝。",
            )
            return

        if event.type == EventType.ERROR.value:
            await self._send_text(chat_id, f"[系统错误] {event.content}")
            return

        if event.type == EventType.MESSAGE.value:
            if stream_event == StreamEventType.CHUNK.value:
                self._stream_buffers.setdefault(event.stream_id, []).append(str(event.content))
                return
            await self._send_text(chat_id, str(event.content))
            return

        if event.type == EventType.STATUS.value:
            if stream_event == StreamEventType.START.value:
                self._stream_buffers[event.stream_id] = []
                return
            if stream_event == StreamEventType.END.value:
                text = "".join(self._stream_buffers.pop(event.stream_id, []))
                await self._send_text(chat_id, text)
                return
            if event.content:
                await self._send_text(chat_id, str(event.content))
