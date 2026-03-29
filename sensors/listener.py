"""
CLI 交互监听器。

基于 prompt_toolkit 实现异步全屏终端界面，
处理用户输入并将事件发布到事件总线。
"""

import logging

from prompt_toolkit import Application
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

logger = logging.getLogger("meetyou.listener")


class Listener:
    """
    CLI 终端交互监听器。

    提供全屏文本界面（输出区 + 输入区），
    将用户输入事件发布到 EventBus。
    """

    def __init__(self, event_bus):
        """
        Args:
            event_bus: EventBus 实例
        """
        self._event_bus = event_bus

        self.output_field = TextArea(text="", read_only=True, scrollbar=True)
        self.input_field = TextArea(height=5, prompt="User: ")

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
        def pageup(event):
            self.output_field.buffer.cursor_up(count=10)

        @self.kb.add(Keys.PageDown)
        def pagedown(event):
            self.output_field.buffer.cursor_down(count=10)

        @self.kb.add("enter")
        def handle_enter(event):
            user_text = self.input_field.text.strip()
            self.input_field.text = ""

            if not user_text:
                return

            # 如果有待确认的危险命令，优先处理为确认回复
            if self._event_bus.has_pending_confirmation:
                accepted = user_text.lower() in ("y", "yes")
                status = "已确认" if accepted else "已拒绝"
                self.output_field.text += f"[确认回复] {status}\n"
                self.output_field.buffer.cursor_position = len(self.output_field.text)
                self._event_bus.resolve_confirmation(accepted)
                return

            # 正常输入处理
            if user_text == "exit":
                event.app.exit()
                return

            self.output_field.text += f"You: {user_text}\n"
            self.output_field.buffer.cursor_position = len(self.output_field.text)
            self._event_bus.sensory_queue.put_nowait({
                "source": "user",
                "content": user_text,
            })

        # 订阅确认请求事件 — 在输出区展示确认提示
        def _show_confirmation(data):
            prompt = data.get("prompt", "请确认操作")
            self.output_field.text += f"\n{'='*50}\n{prompt}\n{'='*50}\n"
            self.output_field.buffer.cursor_position = len(self.output_field.text)
            self.input_field.text = ""
            try:
                self.app.invalidate()
            except Exception:
                pass

        self._event_bus.subscribe(self._event_bus.CONFIRM_REQUEST, _show_confirmation)

        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            full_screen=True,
            mouse_support=True,
        )

    def system_output(self, text: str):
        """同步输出系统消息到终端"""
        self.output_field.text += text + "\n"
        self.output_field.buffer.cursor_position = len(self.output_field.text)
        try:
            self.app.invalidate()
        except Exception:
            pass

    async def run(self):
        """异步运行 CLI 界面"""
        try:
            await self.app.run_async()
        except Exception as e:
            logger.error(f"Listener 异常退出: {e}")
            raise
        finally:
            self.output_field.text += "\nMozart: 哎，回见！\n"
            self.output_field.buffer.cursor_position = len(self.output_field.text)
            self._event_bus.request_shutdown()
