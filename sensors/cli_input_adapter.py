"""
CLI 输入适配器。
"""

import logging

from core.interaction_response_service import InteractionResponseService
from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import TextArea

from core.io_protocol import (
    EventTarget,
    EventType,
    InboundEvent,
    SourceKind,
    TargetKind,
    make_source,
)

logger = logging.getLogger("meetyou.cli_input")

_ACCEPTED_CONFIRM_TOKENS = {"y", "yes", "确认", "同意", "允许"}


class CLIInputAdapter:
    """
    只负责 CLI 输入采集与确认回复。
    """

    def __init__(self, event_bus, session_manager):
        self._event_bus = event_bus
        self._interaction_responses = InteractionResponseService(event_bus)
        self._session_manager = session_manager
        self.source = make_source(SourceKind.CLI.value, "local")
        self.session_id = self._session_manager.get_or_create_session(
            self.source, session_id="cli:local"
        )

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

            if user_text == "exit":
                event.app.exit()
                return

            self._consume_user_text(user_text)

        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            full_screen=True,
            mouse_support=True,
        )

    def _consume_user_text(self, user_text: str):
        interaction_responses = getattr(self, "_interaction_responses", None) or InteractionResponseService(self._event_bus)
        if interaction_responses.has_pending_confirmation(session_id=self.session_id):
            accepted = user_text.strip().lower() in _ACCEPTED_CONFIRM_TOKENS
            interaction_responses.submit_confirmation_response(
                accepted,
                request_id=interaction_responses.get_pending_confirmation_request_id(session_id=self.session_id),
                session_id=self.session_id,
                endpoint_id="cil",
            )
            return

        if interaction_responses.get_pending_human_input_request(session_id=self.session_id) is not None:
            response = interaction_responses.normalize_human_input_text(user_text, session_id=self.session_id)
            if response is not None:
                interaction_responses.submit_human_input_response(
                    response.get("answer_text", ""),
                    request_id=response.get("request_id", ""),
                    session_id=response.get("session_id", self.session_id),
                    selected_option=response.get("selected_option"),
                )
                return

        self.output_field.text += f"You: {user_text}\n"
        self.output_field.buffer.cursor_position = len(self.output_field.text)
        self._event_bus.inbound_queue.put_nowait(
            InboundEvent(
                session_id=self.session_id,
                type=EventType.MESSAGE.value,
                role="user",
                content=user_text,
                source=self.source,
                target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
            )
        )

    async def run(self):
        try:
            await self.app.run_async()
        except Exception as e:
            logger.error(f"CLI 输入适配器异常退出: {e}")
            raise
        finally:
            self._event_bus.request_shutdown()
