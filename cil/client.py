"""
基于 gateway HTTP/WebSocket 的 CIL 客户端。
"""

import asyncio
import json
import logging
import os
from uuid import uuid4

try:
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.widgets import TextArea
except ImportError:  # pragma: no cover - optional at import time
    Application = None
    KeyBindings = None
    Keys = None
    HSplit = None
    Window = None
    Layout = None
    TextArea = None

from core.logger import setup_logger
from endpoint_providers.runtime_connection import EndpointRuntimeConnection

logger = logging.getLogger("meetyou.cil")

_ACCEPTED_CONFIRM_TOKENS = {"y", "yes", "确认", "同意", "允许"}
_REJECTED_CONFIRM_TOKENS = {"n", "no", "拒绝", "取消", "不同意"}


class CILClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        setup_logger(enable_console=False, component="cil")
        if any(
            dependency is None
            for dependency in (Application, KeyBindings, Keys, HSplit, Window, Layout, TextArea)
        ):
            raise RuntimeError("prompt_toolkit is required to run CILClient.")

        self.base_url = base_url.rstrip("/")
        self.source_id = f"cil-{uuid4().hex[:8]}"
        self._closed = False
        self._pending_confirm_request_id: str | None = None
        self._pending_human_input_request_id: str | None = None
        self._streaming = False
        self._stream_prefix_pending = False
        self._connection_logged = False
        self._conversation = EndpointRuntimeConnection(
            base_url=self.base_url,
            provider_id=self.source_id,
            provider_type="cil",
            display_name="CIL",
            workspace_id="personal",
            access_token=os.environ.get("MEETYOU_GATEWAY_ACCESS_TOKEN", ""),
            thread_title="CIL Chat",
            event_handler=self._handle_endpoint_ws_payload,
        )

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

    async def _handle_endpoint_ws_payload(self, data: dict):
        if data.get("schema") != "meetyou.endpoint.ws.v4":
            return

        frame_type = str(data.get("type") or "")
        if frame_type in {"endpoint.hello.ack", "subscription.ack"}:
            if not self._connection_logged:
                self._append(f"[系统] 已连接 gateway，会话 {self._conversation.session_id}\n")
                self._connection_logged = True
            return

        if frame_type == "endpoint.error":
            error = data.get("payload", {}) or {}
            self._append(f"[系统错误] {error.get('code', 'gateway_error')}: {error.get('message', '')}\n")
            return

        if frame_type == "delivery.notice":
            notice = data.get("payload", {}) or {}
            content = str(notice.get("content") or notice.get("text") or "").strip()
            if not content and isinstance(notice.get("message"), dict):
                content = str(notice["message"].get("content") or "").strip()
            if content:
                self._append(f"Mozart: {content}\n")
            return

        if frame_type != "delivery.run_event":
            return

        evt = data.get("payload", {}) or {}
        event_type = str(evt.get("type") or "")
        body = evt.get("payload") if isinstance(evt.get("payload"), dict) else evt

        if event_type == "confirm.requested":
            self._pending_confirm_request_id = body.get("request_id")
            self._append("\n" + "=" * 50 + "\n" + str(body.get("content", "")) + "\n回复 y/yes/确认 或 n/no/拒绝\n" + "=" * 50 + "\n")
            return

        if event_type == "human_input.requested":
            self._pending_human_input_request_id = body.get("request_id")
            options = [str(item).strip() for item in (body.get("options") or []) if str(item).strip()]
            option_lines = "\n".join(f"{idx}. {item}" for idx, item in enumerate(options, start=1))
            self._append("\n" + "=" * 50 + "\n" + str(body.get("question", "") or body.get("content", "")) + (f"\n{option_lines}" if option_lines else "") + "\n输入编号或直接回复内容\n" + "=" * 50 + "\n")
            return

        if event_type == "confirm.resolved":
            self._pending_confirm_request_id = None
            return

        if event_type == "human_input.resolved":
            self._pending_human_input_request_id = None
            return

        if event_type in {"activity.status", "assistant.progress_notice"}:
            content = str(body.get("content", "") or body.get("text", "")).strip()
            if content:
                self._append(f"[系统] {content}\n")
            return

        if event_type in {"runtime.state", "runtime.usage", "operation.updated", "reasoning.delta"}:
            return

        if event_type in {"message.delta", "assistant.message.delta"}:
            if body.get("channel") not in {"", "answer"}:
                return
            content = str(body.get("delta", "") or body.get("content", "")).replace("\r", "")
            if content:
                if self._stream_prefix_pending:
                    self._append("Mozart: ")
                    self._stream_prefix_pending = False
                elif not self._streaming:
                    self._append("Mozart: ")
                self._append(content)
                self._streaming = True
            return

        if event_type in {"message.completed", "assistant.message.completed"}:
            message = body.get("message", {}) if isinstance(body.get("message"), dict) else body
            content = str(message.get("content", "")).replace("\r", "")
            if self._streaming:
                if self._stream_prefix_pending:
                    if content:
                        self._append("Mozart: ")
                    self._stream_prefix_pending = False
                if content and self.output_field.text.rstrip().endswith(content.rstrip()) is False:
                    self._append(content)
                if not self._stream_prefix_pending:
                    self._append("\n")
            else:
                if content:
                    self._append(f"Mozart: {content}\n")
            self._streaming = False
            self._stream_prefix_pending = False
            return
    async def _send_message(self, text: str):
        self._append(f"You: {text}\n")
        await self._conversation.send_message(text)

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

        try:
            await self._conversation.submit_confirm_response(
                request_id=request_id,
                accepted=accepted,
            )
        except Exception:
            await self._conversation.send_command(
                "confirm_response",
                request_id=request_id,
                accepted=accepted,
                metadata={"source": "cil"},
            )
        self._pending_confirm_request_id = None

    async def _send_human_input_response(self, raw_text: str):
        request_id = self._pending_human_input_request_id
        if not request_id:
            self._append("[系统] 当前没有待补充输入请求\n")
            return
        text = raw_text.strip()
        try:
            await self._conversation.submit_human_input_response(
                request_id=request_id,
                answer_text=text,
                selected_option=text,
            )
        except Exception:
            await self._conversation.send_command(
                "input_response",
                request_id=request_id,
                answer_text=text,
                selected_option=text,
                metadata={"source": "cil"},
            )
        self._pending_human_input_request_id = None

    async def _config_list(self):
        payload = await self._conversation.request_json("GET", "/operator/config")

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
        payload = await self._conversation.request_json("GET", f"/operator/config/{key}")

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
        value = self._parse_config_value(raw_value)
        payload = await self._conversation.request_json(
            "PATCH",
            "/operator/config",
            json_body={"updates": {key: value}},
        )

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
            if self._pending_human_input_request_id:
                await self._send_human_input_response(text)
                return
            await self._send_message(text)
        except Exception as e:
            logger.error("处理 CIL 输入失败: %s", e)
            self._append(f"[系统错误] {e}\n")

    async def run(self):
        self._render_banner()
        try:
            await self._conversation.start()
            await self.app.run_async()
        finally:
            self._closed = True
            await self._conversation.close()

