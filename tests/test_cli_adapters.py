import asyncio
import unittest

from core.io_protocol import EventType, OutboundEvent, SourceKind, StreamEventType, make_source
from sensors.cli_input_adapter import CLIInputAdapter
from sensors.cli_output_adapter import CLIOutputAdapter


class _DummySessionManager:
    def get_or_create_session(self, source, session_id=""):
        return session_id or "cli:local"


class _DummyEventBus:
    def __init__(self):
        self.inbound_queue = asyncio.Queue()
        self.has_pending_confirmation = False
        self.pending_confirmation_session_id = ""
        self.pending_request_id = ""
        self.confirmation_calls = []

    def submit_confirmation_response(self, accepted: bool, request_id: str = "", session_id: str = "") -> bool:
        self.confirmation_calls.append((accepted, request_id, session_id))
        return True

    def get_pending_human_input_request(self, session_id: str = ""):
        return None

    def normalize_human_input_text(self, text: str, session_id: str = ""):
        return None

    def submit_human_input_response(
        self,
        answer_text: str = "",
        *,
        request_id: str = "",
        session_id: str = "",
        selected_option: str | None = None,
    ) -> bool:
        return False


class _DummyBuffer:
    def __init__(self):
        self.cursor_position = 0


class _DummyField:
    def __init__(self):
        self.text = ""
        self.buffer = _DummyBuffer()


class _DummyApp:
    def __init__(self):
        self.invalidate_calls = 0

    def invalidate(self):
        self.invalidate_calls += 1


def _message_event(stream_event: str, content: str = "") -> OutboundEvent:
    return OutboundEvent(
        session_id="cli:local",
        type=EventType.MESSAGE.value,
        role="assistant",
        content=content,
        source=make_source(SourceKind.SYSTEM.value, "brain"),
        metadata={"stream_event": stream_event},
    )


class CLIInputAdapterTests(unittest.TestCase):
    def setUp(self):
        self.event_bus = _DummyEventBus()
        self.adapter = CLIInputAdapter.__new__(CLIInputAdapter)
        self.adapter._event_bus = self.event_bus
        self.adapter._session_manager = _DummySessionManager()
        self.adapter.source = make_source(SourceKind.CLI.value, "local")
        self.adapter.session_id = "cli:local"
        self.adapter.output_field = _DummyField()
        self.adapter.input_field = _DummyField()

    def test_confirmation_only_consumes_cli_local_session(self):
        self.event_bus.has_pending_confirmation = True
        self.event_bus.pending_confirmation_session_id = "feishu:chat:other"
        self.event_bus.pending_request_id = "confirm-1"

        self.adapter._consume_user_text("continue")

        self.assertEqual(self.event_bus.confirmation_calls, [])
        queued_event = self.event_bus.inbound_queue.get_nowait()
        self.assertEqual(queued_event.content, "continue")
        self.assertEqual(queued_event.session_id, "cli:local")
        self.assertEqual(self.adapter.output_field.text, "You: continue\n")

    def test_confirmation_consumes_cli_local_session(self):
        self.event_bus.has_pending_confirmation = True
        self.event_bus.pending_confirmation_session_id = "cli:local"
        self.event_bus.pending_request_id = "confirm-1"

        self.adapter._consume_user_text("yes")

        self.assertEqual(
            self.event_bus.confirmation_calls,
            [(True, "confirm-1", "cli:local")],
        )
        self.assertTrue(self.event_bus.inbound_queue.empty())
        self.assertEqual(self.adapter.output_field.text, "")


class CLIOutputAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = _DummyApp()
        self.output_field = _DummyField()
        self.input_field = _DummyField()
        self.adapter = CLIOutputAdapter(self.app, self.output_field, self.input_field)

    async def test_message_stream_without_chunks_does_not_render_blank_line(self):
        await self.adapter.send(_message_event(StreamEventType.START.value))
        await self.adapter.send(_message_event(StreamEventType.END.value))

        self.assertEqual(self.output_field.text, "")
        self.assertEqual(self.app.invalidate_calls, 0)

    async def test_message_stream_chunks_render_single_assistant_line(self):
        await self.adapter.send(_message_event(StreamEventType.START.value))
        await self.adapter.send(_message_event(StreamEventType.CHUNK.value, "hello"))
        await self.adapter.send(_message_event(StreamEventType.END.value))

        self.assertEqual(self.output_field.text, "Mozart: hello\n")


if __name__ == "__main__":
    unittest.main()
