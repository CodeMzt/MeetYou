"""
基于 gateway HTTP/WebSocket 的 CIL 客户端。
"""

import asyncio
import json
import logging
from uuid import uuid4

import aiohttp
from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import TextArea

from core.logger import setup_logger

logger = logging.getLogger("meetyou.cil")

_ACCEPTED_CONFIRM_TOKENS = {"y", "yes", "确认", "同意", "允许"}
_REJECTED_CONFIRM_TOKENS = {"n", "no", "拒绝", "取消", "不同意"}


class CILClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        setup_logger(enable_console=False, component="cil")

        self.base_url = base_url.rstrip("/")
        self.ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        self.source_id = f"cil-{uuid4().hex[:8]}"
        self.session_id = f"cil-session-{uuid4().hex[:8]}"
        self._http_session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._closed = False
        self._pending_confirm_request_id: str | None = None
        self._ws_task: asyncio.Task | None = None
        self._streaming = False
        self._connection_logged = False

        self.output_field = TextArea(text="", read_only=True, scrollbar=True)
        self.input_field = TextArea(height=5, prompt="CIL> ")

        container = HSplit([
            self.output_field,
            Window(height=1, char="="),
            self.input_field,
        ])
        self.layout = Layout(container, focused_element=self.input_field)
        self.kb = KeyBindings()

        @self.kb.add("c-c")
        def handle_exit(event):
            event.app.exit()

        @self.kb.add(Keys.ScrollUp)
        def scroll_up(event):
            self.output_field.buffer.cursor_up(count=3)

        @self.kb.add(Keys.ScrollDown)
        def scroll_down(event):
            self.output_field.buffer.cursor_down(count=3)

        @self.kb.add(Keys.PageUp)
        def page_up(event):
            self.output_field.buffer.cursor_up(count=10)

        @self.kb.add(Keys.PageDown)
        def page_down(event):
            self.output_field.buffer.cursor_down(count=10)

        @self.kb.add("enter")
        def handle_enter(event):
            text = self.input_field.text.strip()
            self.input_field.text = ""
            if not text:
                return
            if text.lower() == "exit":
                event.app.exit()
                return
            asyncio.create_task(self.handle_input(text))

        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            full_screen=True,
            mouse_support=True,
        )

    def _append(self, text: str):
        self.output_field.text += text
        self.output_field.buffer.cursor_position = len(self.output_field.text)
        try:
            self.app.invalidate()
        except Exception:
            pass

    def _render_banner(self):
        self._append(
            "MeetYou CIL 已启动\n"
            "命令: /help | /config list | /config get <key> | /config set <key> <value> | exit\n"
            f"目标 gateway: {self.base_url}\n\n"
        )

    async def _ensure_http_session(self):
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession()

    async def _connect_ws(self):
        await self._ensure_http_session()
        url = f"{self.ws_url}/ws?session_id={self.session_id}&source_id={self.source_id}"
        self._ws = await self._http_session.ws_connect(url)
        self._connection_logged = False

    async def _maintain_connection(self):
        while not self._closed:
            try:
                if self._ws is None or self._ws.closed:
                    await self._connect_ws()
                await self._read_ws()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("CIL WebSocket 连接异常: %s", e)
                self._append(f"\n[系统] 与 gateway 连接中断: {e}\n")
                await asyncio.sleep(2)

    async def _read_ws(self):
        if self._ws is None:
            return
        async for message in self._ws:
            if message.type == aiohttp.WSMsgType.TEXT:
                await self._handle_ws_payload(message.json())
            elif message.type == aiohttp.WSMsgType.ERROR:
                raise RuntimeError("gateway WebSocket 错误")
            elif message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                raise RuntimeError("gateway WebSocket 已关闭")

    async def _handle_ws_payload(self, data: dict):
        if data.get("schema") != "meetyou.ws.v1":
            return

        if data.get("kind") == "connection":
            session_id = data.get("connection", {}).get("session_id")
            if session_id:
                self.session_id = session_id
            if not self._connection_logged:
                self._append(f"[系统] 已连接 gateway，会话 {self.session_id}\n")
                self._connection_logged = True
            return

        if data.get("kind") == "error":
            error = data.get("error", {})
            self._append(f"[系统错误] {error.get('code', 'gateway_error')}: {error.get('message', '')}\n")
            return

        if data.get("kind") != "event":
            return

        evt = data.get("event", {})
        stream = data.get("stream", {})
        confirm = data.get("confirm", {})
        event_type = evt.get("type")
        stream_phase = stream.get("phase", "")

        if event_type == "confirm_request":
            self._pending_confirm_request_id = confirm.get("request_id")
            self._append(
                "\n"
                + "=" * 50
                + "\n"
                + str(evt.get("content", ""))
                + "\n回复 y/yes/确认 或 n/no/拒绝\n"
                + "=" * 50
                + "\n"
            )
            return

        if event_type == "error":
            if self._streaming:
                self._append("\n")
                self._streaming = False
            self._append(f"[系统错误] {evt.get('content', '')}\n")
            return

        if event_type == "status":
            if stream_phase == "start":
                self._append("Mozart: ")
                self._streaming = True
                return
            if stream_phase == "end":
                self._append("\n")
                self._streaming = False
                return
            if evt.get("content"):
                self._append(f"[系统] {evt['content']}\n")
            return

        if event_type == "message":
            content = str(evt.get("content", "")).replace("\r", "")
            if stream_phase == "chunk":
                self._append(content)
                self._streaming = True
                return
            if self._streaming:
                self._append("\n")
                self._streaming = False
            self._append(f"Mozart: {content}\n")

    async def _send_ws_json(self, payload: dict):
        if self._ws is None or self._ws.closed:
            raise RuntimeError("尚未连接到 gateway")
        await self._ws.send_json(payload)

    async def _send_message(self, text: str):
        await self._ensure_http_session()
        self._append(f"You: {text}\n")
        async with self._http_session.post(
            f"{self.base_url}/inputs",
            json={
                "content": text,
                "session_id": self.session_id,
                "source_id": self.source_id,
                "role": "user",
            },
        ) as response:
            if response.status >= 400:
                body = await response.text()
                self._append(f"[系统错误] 发送失败: {response.status} {body}\n")
                return
            payload = await response.json()
            if payload.get("session_id"):
                self.session_id = payload["session_id"]

    async def _send_confirm_response(self, raw_text: str):
        normalized = raw_text.strip().lower()
        if normalized in _ACCEPTED_CONFIRM_TOKENS:
            accepted = True
        elif normalized in _REJECTED_CONFIRM_TOKENS:
            accepted = False
        else:
            self._append("[系统] 请输入 y/yes/确认 或 n/no/拒绝\n")
            return

        request_id = self._pending_confirm_request_id
        if not request_id:
            self._append("[系统] 当前没有待确认请求\n")
            return

        await self._send_ws_json(
            {
                "action": "confirm_response",
                "request_id": request_id,
                "accepted": accepted,
                "metadata": {"source": "cil"},
            }
        )
        self._pending_confirm_request_id = None

    async def _config_list(self):
        await self._ensure_http_session()
        async with self._http_session.get(f"{self.base_url}/config") as response:
            payload = await response.json()
            if response.status >= 400:
                self._append(f"[系统错误] 读取配置失败: {payload}\n")
                return

        items = payload.get("items", {})
        self._append("[配置列表]\n")
        for key in sorted(items):
            item = items[key]
            value = item.get("value")
            source = item.get("source", "default")
            if item.get("is_secret"):
                display = value if item.get("has_value") else "<empty>"
            else:
                display = json.dumps(value, ensure_ascii=False) if value is not None else "<unset>"
            self._append(f"- {key} = {display} ({source})\n")

    async def _config_get(self, key: str):
        await self._ensure_http_session()
        async with self._http_session.get(f"{self.base_url}/config/{key}") as response:
            payload = await response.json()
            if response.status >= 400:
                self._append(f"[系统错误] 读取配置失败: {payload}\n")
                return

        value = payload.get("value")
        display = value if payload.get("is_secret") else json.dumps(value, ensure_ascii=False)
        self._append(
            f"[配置] {key}\n"
            f"  source: {payload.get('source', 'default')}\n"
            f"  secret: {payload.get('is_secret', False)}\n"
            f"  has_value: {payload.get('has_value', False)}\n"
            f"  value: {display}\n"
        )

    @staticmethod
    def _parse_config_value(raw_value: str):
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return raw_value

    async def _config_set(self, key: str, raw_value: str):
        await self._ensure_http_session()
        value = self._parse_config_value(raw_value)
        async with self._http_session.patch(
            f"{self.base_url}/config",
            json={"updates": {key: value}},
        ) as response:
            payload = await response.json()
            if response.status >= 400:
                self._append(f"[系统错误] 更新配置失败: {payload}\n")
                return

        self._append(
            "[配置更新]\n"
            f"  applied: {', '.join(payload.get('applied_keys', [])) or '<none>'}\n"
            f"  reloaded: {', '.join(payload.get('reloaded_components', [])) or '<none>'}\n"
            f"  restart_required: {', '.join(payload.get('restart_required_keys', [])) or '<none>'}\n"
        )
        for warning in payload.get("warnings", []):
            self._append(f"  warning: {warning}\n")

    def _render_help(self):
        self._append(
            "/help\n"
            "/config list\n"
            "/config get <key>\n"
            "/config set <key> <json-or-string>\n"
            "直接输入文本即可与 Mozart 对话\n"
            "输入 exit 退出\n"
        )

    async def _handle_command(self, text: str):
        parts = text.split(" ", 3)
        if text == "/help":
            self._render_help()
            return
        if text == "/config list":
            await self._config_list()
            return
        if len(parts) >= 3 and parts[0] == "/config" and parts[1] == "get":
            await self._config_get(parts[2])
            return
        if len(parts) >= 4 and parts[0] == "/config" and parts[1] == "set":
            await self._config_set(parts[2], parts[3])
            return
        self._append("[系统] 未知命令，输入 /help 查看帮助\n")

    async def handle_input(self, text: str):
        try:
            if text.startswith("/"):
                await self._handle_command(text)
                return
            if self._pending_confirm_request_id:
                await self._send_confirm_response(text)
                return
            await self._send_message(text)
        except Exception as e:
            logger.error("处理 CIL 输入失败: %s", e)
            self._append(f"[系统错误] {e}\n")

    async def run(self):
        self._render_banner()
        self._ws_task = asyncio.create_task(self._maintain_connection())
        try:
            await self.app.run_async()
        finally:
            self._closed = True
            if self._ws_task is not None:
                self._ws_task.cancel()
                try:
                    await self._ws_task
                except asyncio.CancelledError:
                    pass
            if self._ws is not None and not self._ws.closed:
                await self._ws.close()
            if self._http_session is not None:
                await self._http_session.close()
