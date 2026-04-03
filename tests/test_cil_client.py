import unittest

from cil.client import CILClient


class _DummyBuffer:
    def __init__(self):
        self.cursor_position = 0


class _DummyField:
    def __init__(self):
        self.text = ""
        self.buffer = _DummyBuffer()


class _DummyApp:
    def invalidate(self):
        return None


class CILClientTests(unittest.TestCase):
    def test_parse_config_value_prefers_json(self):
        self.assertEqual(CILClient._parse_config_value("true"), True)
        self.assertEqual(CILClient._parse_config_value("123"), 123)
        self.assertEqual(CILClient._parse_config_value('{"a": 1}'), {"a": 1})
        self.assertEqual(CILClient._parse_config_value("plain-text"), "plain-text")


class CILClientStreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = CILClient.__new__(CILClient)
        self.client.output_field = _DummyField()
        self.client.input_field = _DummyField()
        self.client.app = _DummyApp()
        self.client._streaming = False
        self.client._stream_prefix_pending = False
        self.client._pending_confirm_request_id = None
        self.client._connection_logged = False
        self.client.session_id = "cil-session-1"

    async def test_message_stream_without_chunks_does_not_render_blank_line(self):
        await self.client._handle_ws_payload(
            {
                "schema": "meetyou.ws.v1",
                "kind": "event",
                "event": {"type": "message", "content": ""},
                "stream": {"phase": "start"},
            }
        )
        await self.client._handle_ws_payload(
            {
                "schema": "meetyou.ws.v1",
                "kind": "event",
                "event": {"type": "message", "content": ""},
                "stream": {"phase": "end"},
            }
        )

        self.assertEqual(self.client.output_field.text, "")

    async def test_message_stream_chunks_render_single_assistant_line(self):
        await self.client._handle_ws_payload(
            {
                "schema": "meetyou.ws.v1",
                "kind": "event",
                "event": {"type": "message", "content": ""},
                "stream": {"phase": "start"},
            }
        )
        await self.client._handle_ws_payload(
            {
                "schema": "meetyou.ws.v1",
                "kind": "event",
                "event": {"type": "message", "content": "hello"},
                "stream": {"phase": "chunk"},
            }
        )
        await self.client._handle_ws_payload(
            {
                "schema": "meetyou.ws.v1",
                "kind": "event",
                "event": {"type": "message", "content": ""},
                "stream": {"phase": "end"},
            }
        )

        self.assertEqual(self.client.output_field.text, "Mozart: hello\n")


if __name__ == "__main__":
    unittest.main()
