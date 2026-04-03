import unittest

from core.io_protocol import EventTarget, EventType, OutboundEvent, SourceKind, TargetKind, make_source
from core.session_manager import SessionManager
from core.speaker import Speaker
from gateway.ws_manager import WebSocketManager
from gateway.ws_manager import WebSocketOutputAdapter


class FakeWebSocket:
    def __init__(self):
        self.payloads = []

    async def send_json(self, payload):
        self.payloads.append(payload)


class RuntimeWebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_stream_boundaries_use_message_events(self):
        ws_manager = WebSocketManager()
        websocket = FakeWebSocket()
        session_manager = SessionManager()
        source = make_source(SourceKind.WEB.value, "browser-tab-a")
        session_manager.get_or_create_session(source, "session-1")
        speaker = Speaker(session_manager)
        speaker.register_adapter(TargetKind.WEB.value, WebSocketOutputAdapter(ws_manager))

        await ws_manager.connect("session-1", websocket)

        stream_id = await speaker.emit_stream_start(
            "session-1",
            make_source(SourceKind.SYSTEM.value, "brain"),
            stream_channel="answer",
        )
        await speaker.emit_stream_end(
            "session-1",
            make_source(SourceKind.SYSTEM.value, "brain"),
            stream_id,
            stream_channel="answer",
        )

        self.assertEqual(websocket.payloads[0]["event"]["type"], "message")
        self.assertEqual(websocket.payloads[0]["stream"]["phase"], "start")
        self.assertEqual(websocket.payloads[0]["stream"]["channel"], "answer")
        self.assertEqual(websocket.payloads[1]["event"]["type"], "message")
        self.assertEqual(websocket.payloads[1]["stream"]["phase"], "end")

    async def test_reasoning_event_includes_stream_channel_and_turn_id(self):
        ws_manager = WebSocketManager()
        websocket = FakeWebSocket()
        await ws_manager.connect("session-1", websocket)

        await ws_manager.send_event(
            "session-1",
            OutboundEvent(
                session_id="session-1",
                type=EventType.REASONING.value,
                role="assistant",
                content="thinking chunk",
                source=make_source(SourceKind.SYSTEM.value, "brain"),
                target=EventTarget(kind=TargetKind.WEB.value, id="browser-tab-a"),
                stream_id="stream-1",
                metadata={
                    "stream_event": "chunk",
                    "stream_channel": "reasoning",
                    "turn_id": "turn-1",
                },
            ),
        )

        payload = websocket.payloads[0]
        self.assertEqual(payload["schema"], "meetyou.ws.v1")
        self.assertEqual(payload["kind"], "event")
        self.assertEqual(payload["event"]["type"], "reasoning")
        self.assertEqual(payload["event"]["metadata"]["turn_id"], "turn-1")
        self.assertEqual(payload["stream"]["id"], "stream-1")
        self.assertEqual(payload["stream"]["phase"], "chunk")
        self.assertEqual(payload["stream"]["channel"], "reasoning")

    async def test_runtime_status_and_usage_events_are_serialized(self):
        ws_manager = WebSocketManager()
        websocket = FakeWebSocket()
        await ws_manager.connect("session-1", websocket)

        await ws_manager.send_event(
            "session-1",
            OutboundEvent(
                session_id="session-1",
                type=EventType.RUNTIME_STATUS.value,
                role="system",
                content={"session_id": "session-1", "status": "thinking", "turn_id": "turn-1"},
                source=make_source(SourceKind.SYSTEM.value, "runtime"),
                target=EventTarget(kind=TargetKind.WEB.value, id="browser-tab-a"),
                metadata={"turn_id": "turn-1"},
            ),
        )
        await ws_manager.send_event(
            "session-1",
            OutboundEvent(
                session_id="session-1",
                type=EventType.USAGE.value,
                role="system",
                content={
                    "session_id": "session-1",
                    "last_turn_usage": {"total_tokens": 21},
                    "session_totals": {"total_tokens": 42, "turn_count": 2},
                },
                source=make_source(SourceKind.SYSTEM.value, "usage"),
                target=EventTarget(kind=TargetKind.WEB.value, id="browser-tab-a"),
                metadata={"turn_id": "turn-1"},
            ),
        )

        self.assertEqual(websocket.payloads[0]["event"]["type"], "runtime_status")
        self.assertEqual(websocket.payloads[0]["event"]["content"]["status"], "thinking")
        self.assertEqual(websocket.payloads[1]["event"]["type"], "usage")
        self.assertEqual(websocket.payloads[1]["event"]["content"]["last_turn_usage"]["total_tokens"], 21)
        self.assertEqual(websocket.payloads[1]["event"]["metadata"]["turn_id"], "turn-1")


if __name__ == "__main__":
    unittest.main()
