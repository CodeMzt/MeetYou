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


class _DummyConversation:
    def __init__(self):
        self.session_id = "cil-session-1"
        self.confirm_calls = []
        self.input_calls = []
        self.command_calls = []
        self.fail_confirm = False
        self.fail_input = False

    async def submit_confirm_response(self, *, request_id: str, accepted: bool, reason: str = ""):
        if self.fail_confirm:
            raise RuntimeError("confirm resource unavailable")
        self.confirm_calls.append({"request_id": request_id, "accepted": accepted, "reason": reason})
        return {"request_id": request_id, "accepted": accepted}

    async def submit_human_input_response(self, *, request_id: str, answer_text: str, selected_option: str | None = None):
        if self.fail_input:
            raise RuntimeError("human input resource unavailable")
        self.input_calls.append(
            {"request_id": request_id, "answer_text": answer_text, "selected_option": selected_option}
        )
        return {"request_id": request_id, "answer_text": answer_text, "selected_option": selected_option}

    async def send_command(self, action: str, **payload):
        self.command_calls.append({"action": action, **payload})
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
        self.client._pending_human_input_request_id = None
        self.client._connection_logged = False
        self.client._conversation = _DummyConversation()

    async def test_message_stream_without_chunks_does_not_render_blank_line(self):
        await self.client._handle_client_ws_payload(
            {
                "schema": "meetyou.client.ws.v1",
                "kind": "event",
                "event": {"type": "message.completed", "message": {"content": ""}, "stream_id": "stream-1"},
            }
        )
        await self.client._handle_client_ws_payload(
            {
                "schema": "meetyou.client.ws.v1",
                "kind": "event",
                "event": {"type": "message.completed", "message": {"content": ""}, "stream_id": "stream-1"},
            }
        )

        self.assertEqual(self.client.output_field.text, "")

    async def test_message_stream_chunks_render_single_assistant_line(self):
        await self.client._handle_client_ws_payload(
            {
                "schema": "meetyou.client.ws.v1",
                "kind": "event",
                "event": {"type": "message.delta", "channel": "answer", "delta": "hello", "stream_id": "stream-1", "turn_id": "turn-1", "phase": "chunk"},
            }
        )
        await self.client._handle_client_ws_payload(
            {
                "schema": "meetyou.client.ws.v1",
                "kind": "event",
                "event": {"type": "message.completed", "message": {"content": "hello"}, "stream_id": "stream-1", "turn_id": "turn-1"},
            }
        )

        self.assertEqual(self.client.output_field.text, "Mozart: hello\n")

    async def test_confirm_response_prefers_resource_endpoint(self):
        self.client._pending_confirm_request_id = "confirm-1"

        await self.client._send_confirm_response("yes")

        self.assertEqual(self.client._conversation.confirm_calls, [{"request_id": "confirm-1", "accepted": True, "reason": ""}])
        self.assertEqual(self.client._conversation.command_calls, [])
        self.assertIsNone(self.client._pending_confirm_request_id)

    async def test_confirm_response_falls_back_to_ws_command(self):
        self.client._pending_confirm_request_id = "confirm-2"
        self.client._conversation.fail_confirm = True

        await self.client._send_confirm_response("no")

        self.assertEqual(self.client._conversation.confirm_calls, [])
        self.assertEqual(
            self.client._conversation.command_calls,
            [{"action": "confirm_response", "request_id": "confirm-2", "accepted": False, "metadata": {"source": "cil"}}],
        )
        self.assertIsNone(self.client._pending_confirm_request_id)

    async def test_human_input_prefers_resource_endpoint(self):
        self.client._pending_human_input_request_id = "input-1"

        await self.client._send_human_input_response("A")

        self.assertEqual(
            self.client._conversation.input_calls,
            [{"request_id": "input-1", "answer_text": "A", "selected_option": "A"}],
        )
        self.assertEqual(self.client._conversation.command_calls, [])
        self.assertIsNone(self.client._pending_human_input_request_id)

    async def test_human_input_falls_back_to_ws_command(self):
        self.client._pending_human_input_request_id = "input-2"
        self.client._conversation.fail_input = True

        await self.client._send_human_input_response("B")

        self.assertEqual(self.client._conversation.input_calls, [])
        self.assertEqual(
            self.client._conversation.command_calls,
            [{
                "action": "input_response",
                "request_id": "input-2",
                "answer_text": "B",
                "selected_option": "B",
                "metadata": {"source": "cil"},
            }],
        )
        self.assertIsNone(self.client._pending_human_input_request_id)


if __name__ == "__main__":
    unittest.main()
