from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import unittest

from core.app import App
from core.client_thread_bridge import ClientThreadBridge
from core.io_protocol import EventTarget, TargetKind
from core.session_manager import SessionManager
from core.status import RuntimeStatus


@dataclass
class _ThreadRow:
    id: int
    thread_id: str
    workspace_id: int


@dataclass
class _WorkspaceRow:
    workspace_id: str


@dataclass
class _SessionRow:
    id: int
    session_id: str
    thread_id: int
    workspace_id: int
    client_id: int


class _GatewayStub:
    def __init__(self, session_manager: SessionManager):
        self._session_manager = session_manager
        self.thread_events: list[dict] = []

    async def publish_client_thread_event(self, thread_id: str, *, event_type: str, payload: dict) -> None:
        self.thread_events.append({"thread_id": thread_id, "event_type": event_type, "payload": dict(payload)})


class _SessionServiceStub:
    def __init__(self, rows=None):
        self._rows = {row.session_id: row for row in (rows or [])}

    def get_by_session_id(self, session_id: str):
        return self._rows.get(session_id)


class _ThreadServiceStub:
    def __init__(self, thread_row: _ThreadRow):
        self._thread_row = thread_row

    def get_by_id(self, row_id):
        return None

    def get_by_thread_id(self, thread_id: str):
        if thread_id == self._thread_row.thread_id:
            return self._thread_row
        return None


class _WorkspaceServiceStub:
    def get_by_id(self, row_id):
        return _WorkspaceRow(workspace_id="desktop-main")


class _MessageServiceStub:
    def __init__(self):
        self.created: list[dict] = []
        self._counter = 0

    def create_message(self, **kwargs):
        self.created.append(dict(kwargs))
        self._counter += 1
        return SimpleNamespace(
            message_id=f"msg_{self._counter}",
            role=kwargs.get("role", "assistant"),
            content=kwargs.get("content", ""),
            status=kwargs.get("status", "completed"),
            channel=kwargs.get("channel", "message"),
            created_at=None,
        )


class _BrainStub:
    def __init__(self, snapshot: dict):
        self.snapshot = snapshot

    def get_session_runtime_snapshot(self, session_id: str):
        return dict(self.snapshot)


class _ShortReplyBridgeStub:
    def __init__(self):
        self.calls: list[dict] = []

    async def publish_short_assistant_message(self, session_id: str, **kwargs):
        self.calls.append({"session_id": session_id, **dict(kwargs)})
        return {"delivered": True, "session_id": session_id, **dict(kwargs)}


class ClientThreadBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_agent_session_publishes_delta_and_completed_to_bridged_thread(self):
        session_manager = SessionManager()
        session_manager.bind_runtime_session(
            source=SimpleNamespace(kind="system", id="agent:desktop-main-agent", metadata={}),
            session_id="system:agent:desktop-main-agent",
            default_target=EventTarget(kind=TargetKind.INTERNAL.value, id="desktop-main-agent"),
            metadata={
                "thread_id": "thr_recent",
                "workspace_id": "desktop-main",
                "client_id": "desktop-app",
                "bridged_session_id": "client-session-1",
            },
        )
        gateway = _GatewayStub(session_manager)
        message_service = _MessageServiceStub()
        core_services = SimpleNamespace(
            session=_SessionServiceStub(),
            thread=_ThreadServiceStub(_ThreadRow(id=7, thread_id="thr_recent", workspace_id=3)),
            workspace=_WorkspaceServiceStub(),
            message=message_service,
        )
        bridge = ClientThreadBridge(
            gateway_getter=lambda: gateway,
            core_services_getter=lambda: core_services,
        )

        await bridge.publish_message_delta(
            "system:agent:desktop-main-agent",
            stream_id="stream-1",
            turn_id="turn-1",
            delta="hello",
        )
        await bridge.persist_and_publish_assistant_message(
            "system:agent:desktop-main-agent",
            content="hello world",
            stream_id="stream-1",
            turn_id="turn-1",
        )

        self.assertEqual(len(gateway.thread_events), 2)
        self.assertEqual(gateway.thread_events[0]["event_type"], "message.delta")
        self.assertEqual(gateway.thread_events[0]["thread_id"], "thr_recent")
        self.assertEqual(gateway.thread_events[0]["payload"]["delta"], "hello")
        self.assertEqual(gateway.thread_events[1]["event_type"], "message.completed")
        self.assertEqual(gateway.thread_events[1]["payload"]["thread_id"], "thr_recent")
        self.assertEqual(gateway.thread_events[1]["payload"]["message"]["content"], "hello world")
        self.assertEqual(gateway.thread_events[1]["payload"]["message"]["client_id"], "desktop-app")
        self.assertTrue(gateway.thread_events[1]["payload"]["message"]["message_id"].startswith("msg_transient_"))
        self.assertEqual(message_service.created, [])

    async def test_transient_agent_session_persists_to_bridged_client_session_when_available(self):
        session_manager = SessionManager()
        session_manager.bind_runtime_session(
            source=SimpleNamespace(kind="system", id="agent:desktop-main-agent", metadata={}),
            session_id="system:agent:desktop-main-agent",
            default_target=EventTarget(kind=TargetKind.INTERNAL.value, id="desktop-main-agent"),
            metadata={
                "thread_id": "thr_recent",
                "workspace_id": "desktop-main",
                "client_id": "desktop-app",
                "bridged_session_id": "client-session-1",
            },
        )
        gateway = _GatewayStub(session_manager)
        message_service = _MessageServiceStub()
        bridged_session = _SessionRow(
            id=9,
            session_id="client-session-1",
            thread_id=7,
            workspace_id=3,
            client_id=5,
        )
        core_services = SimpleNamespace(
            session=_SessionServiceStub([bridged_session]),
            thread=_ThreadServiceStub(_ThreadRow(id=7, thread_id="thr_recent", workspace_id=3)),
            workspace=_WorkspaceServiceStub(),
            message=message_service,
        )
        bridge = ClientThreadBridge(
            gateway_getter=lambda: gateway,
            core_services_getter=lambda: core_services,
        )

        await bridge.publish_message_delta(
            "system:agent:desktop-main-agent",
            stream_id="stream-2",
            turn_id="turn-2",
            delta="hello",
        )
        await bridge.persist_and_publish_assistant_message(
            "system:agent:desktop-main-agent",
            content="hello persisted",
            stream_id="stream-2",
            turn_id="turn-2",
        )

        self.assertEqual(len(message_service.created), 1)
        self.assertEqual(message_service.created[0]["session_id"], bridged_session.id)
        self.assertEqual(gateway.thread_events[0]["payload"]["session_id"], "client-session-1")
        self.assertEqual(gateway.thread_events[1]["payload"]["session_id"], "client-session-1")
        self.assertEqual(gateway.thread_events[1]["payload"]["message"]["session_id"], "client-session-1")
        self.assertEqual(gateway.thread_events[1]["payload"]["message"]["content"], "hello persisted")

    async def test_short_reply_persists_as_standalone_message_created(self):
        session_manager = SessionManager()
        session_manager.bind_runtime_session(
            source=SimpleNamespace(kind="system", id="agent:desktop-main-agent", metadata={}),
            session_id="system:agent:desktop-main-agent",
            default_target=EventTarget(kind=TargetKind.INTERNAL.value, id="desktop-main-agent"),
            metadata={
                "thread_id": "thr_recent",
                "workspace_id": "desktop-main",
                "client_id": "desktop-app",
                "bridged_session_id": "client-session-1",
            },
        )
        gateway = _GatewayStub(session_manager)
        message_service = _MessageServiceStub()
        bridged_session = _SessionRow(
            id=9,
            session_id="client-session-1",
            thread_id=7,
            workspace_id=3,
            client_id=5,
        )
        core_services = SimpleNamespace(
            session=_SessionServiceStub([bridged_session]),
            thread=_ThreadServiceStub(_ThreadRow(id=7, thread_id="thr_recent", workspace_id=3)),
            workspace=_WorkspaceServiceStub(),
            message=message_service,
        )
        bridge = ClientThreadBridge(
            gateway_getter=lambda: gateway,
            core_services_getter=lambda: core_services,
        )

        result = await bridge.publish_short_assistant_message(
            "system:agent:desktop-main-agent",
            content="I will check that.",
            stream_id="stream-1",
            turn_id="turn-1",
        )

        self.assertTrue(result["delivered"])
        self.assertEqual(len(message_service.created), 1)
        self.assertEqual(message_service.created[0]["channel"], "short_reply")
        self.assertEqual(message_service.created[0]["meta"]["short_reply"], True)
        self.assertEqual(gateway.thread_events[0]["event_type"], "message.created")
        self.assertEqual(gateway.thread_events[0]["payload"]["message"]["channel"], "short_reply")
        self.assertNotIn("stream_id", gateway.thread_events[0]["payload"])

    async def test_app_short_reply_only_allowed_during_active_turn(self):
        app = App.__new__(App)
        bridge = _ShortReplyBridgeStub()
        app._get_client_thread_bridge = lambda: bridge
        app.brain = _BrainStub({"status": RuntimeStatus.IDLE.value, "turn_id": "turn-1", "stream_id": "stream-1"})

        rejected = await App.emit_temporary_reply(app, "not now", session_id="sess-1", turn_id="turn-1")

        self.assertFalse(rejected["delivered"])
        self.assertEqual(rejected["reason"], "short_reply_not_allowed")
        self.assertEqual(bridge.calls, [])

        app.brain = _BrainStub({"status": RuntimeStatus.TOOL_CALLING.value, "turn_id": "turn-1", "stream_id": "stream-1"})
        accepted = await App.emit_temporary_reply(app, "checking", session_id="sess-1", turn_id="turn-1")

        self.assertTrue(accepted["delivered"])
        self.assertEqual(bridge.calls[0]["content"], "checking")
        self.assertEqual(bridge.calls[0]["turn_id"], "turn-1")
        self.assertEqual(bridge.calls[0]["stream_id"], "stream-1")


if __name__ == "__main__":
    unittest.main()
