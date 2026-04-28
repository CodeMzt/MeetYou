from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import unittest

from core.app import App, _initial_progress_notice_content
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
    origin_endpoint_id: int | None = None


class _GatewayStub:
    def __init__(self, session_manager: SessionManager):
        self._session_manager = session_manager
        self.thread_events: list[dict] = []

    async def publish_client_thread_event(self, thread_id: str, *, event_type: str, payload: dict) -> None:
        self.thread_events.append({"thread_id": thread_id, "event_type": event_type, "payload": dict(payload)})


class _SessionServiceStub:
    def __init__(self, rows=None):
        self._rows = {row.session_id: row for row in (rows or [])}
        self.created: list[_SessionRow] = []

    def get_by_session_id(self, session_id: str):
        return self._rows.get(session_id)

    def create_session(self, *, thread_id, origin_endpoint_id=None, active_workspace_id=None, workspace_id=None, status: str = "active"):
        row = _SessionRow(
            id=100 + len(self.created),
            session_id=f"sess_created_{len(self.created) + 1}",
            thread_id=thread_id,
            workspace_id=active_workspace_id or workspace_id or 0,
            origin_endpoint_id=origin_endpoint_id,
        )
        self.created.append(row)
        self._rows[row.session_id] = row
        return row


class _ThreadServiceStub:
    def __init__(self, thread_row: _ThreadRow):
        self._thread_row = thread_row

    def get_by_id(self, row_id):
        if row_id == self._thread_row.id:
            return self._thread_row
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


class _GatewayRunEventStub(_GatewayStub):
    def __init__(self, session_manager: SessionManager):
        super().__init__(session_manager)
        self.run_events: list[dict] = []
        self.messages: list[dict] = []

    async def publish_endpoint_run_event(self, *, thread_id: str = "", run_id: str = "", event: dict) -> int:
        self.run_events.append({"thread_id": thread_id, "run_id": run_id, "event": dict(event)})
        return 1

    async def publish_endpoint_message(self, *, thread_id: str = "", message: dict) -> int:
        self.messages.append({"thread_id": thread_id, "message": dict(message)})
        return 1


class _ActorServiceStub:
    def __init__(self):
        self.actor = SimpleNamespace(id="actor-row", actor_id="system.maintenance")

    def get_by_actor_id(self, actor_id: str):
        return self.actor if actor_id == "system.maintenance" else None


class _RunServiceStub:
    def __init__(self):
        self.created: list[dict] = []
        self.statuses: list[dict] = []
        self._runs: dict[str, SimpleNamespace] = {}

    def create_run(self, **kwargs):
        row = SimpleNamespace(id=f"run-row-{len(self.created) + 1}", run_id=f"run_{len(self.created) + 1}", **kwargs)
        self.created.append(dict(kwargs))
        self._runs[row.id] = row
        return row

    def get_by_id(self, row_id):
        return self._runs.get(row_id)

    def update_status(self, **kwargs):
        self.statuses.append(dict(kwargs))
        row = self._runs.get(kwargs.get("run_row_id"))
        if row is not None:
            row.status = kwargs.get("status", row.status)
            row.output = dict(kwargs.get("output") or {})
        return row


class _RunEventServiceStub:
    def __init__(self):
        self.events: list[dict] = []

    def append_event(self, **kwargs):
        seq = len(self.events) + 1
        row = SimpleNamespace(
            event_id=f"evt_{seq}",
            seq=seq,
            created_at=None,
            **kwargs,
        )
        self.events.append(dict(kwargs))
        return row


class _EndpointServiceStub:
    def get_by_endpoint_id(self, endpoint_id: str):
        if endpoint_id == "desktop-app":
            return SimpleNamespace(id=5, endpoint_id=endpoint_id)
        return None


class _ShortReplyBridgeStub:
    def __init__(self):
        self.calls: list[dict] = []

    async def publish_progress_notice(self, session_id: str, **kwargs):
        self.calls.append({"session_id": session_id, **dict(kwargs)})
        return {"delivered": True, "session_id": session_id, **dict(kwargs)}


class ClientThreadBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_bridged_runtime_session_creates_persistent_session_for_final_reply(self):
        session_manager = SessionManager()
        session_manager.bind_runtime_session(
            source=SimpleNamespace(kind="system", id="agent:desktop-main-agent", metadata={}),
            session_id="system:agent:desktop-main-agent",
            default_target=EventTarget(kind=TargetKind.INTERNAL.value, id="desktop-main-agent"),
            metadata={
                "thread_id": "thr_recent",
                "workspace_id": "desktop-main",
                "endpoint_id": "desktop-app",
                "bridged_session_id": "client-session-1",
            },
        )
        gateway = _GatewayStub(session_manager)
        message_service = _MessageServiceStub()
        session_service = _SessionServiceStub()
        core_services = SimpleNamespace(
            session=session_service,
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
        self.assertEqual(gateway.thread_events[1]["payload"]["message"]["origin_endpoint_id"], "desktop-app")
        self.assertEqual(gateway.thread_events[1]["payload"]["message"]["message_id"], "msg_1")
        self.assertEqual(len(message_service.created), 1)
        self.assertEqual(message_service.created[0]["session_id"], session_service.created[0].id)

    async def test_transient_agent_session_persists_to_bridged_client_session_when_available(self):
        session_manager = SessionManager()
        session_manager.bind_runtime_session(
            source=SimpleNamespace(kind="system", id="agent:desktop-main-agent", metadata={}),
            session_id="system:agent:desktop-main-agent",
            default_target=EventTarget(kind=TargetKind.INTERNAL.value, id="desktop-main-agent"),
            metadata={
                "thread_id": "thr_recent",
                "workspace_id": "desktop-main",
                "endpoint_id": "desktop-app",
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
            origin_endpoint_id=5,
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

    async def test_streaming_delta_and_completed_reply_use_run_event_log(self):
        session_manager = SessionManager()
        gateway = _GatewayRunEventStub(session_manager)
        message_service = _MessageServiceStub()
        run_service = _RunServiceStub()
        run_event_service = _RunEventServiceStub()
        session_row = _SessionRow(
            id=9,
            session_id="client-session-1",
            thread_id=7,
            workspace_id=3,
            origin_endpoint_id=5,
        )
        core_services = SimpleNamespace(
            session=_SessionServiceStub([session_row]),
            thread=_ThreadServiceStub(_ThreadRow(id=7, thread_id="thr_recent", workspace_id=3)),
            workspace=_WorkspaceServiceStub(),
            endpoint=_EndpointServiceStub(),
            actor=_ActorServiceStub(),
            run=run_service,
            run_event=run_event_service,
            message=message_service,
        )
        bridge = ClientThreadBridge(
            gateway_getter=lambda: gateway,
            core_services_getter=lambda: core_services,
        )

        await bridge.publish_message_delta(
            "client-session-1",
            stream_id="stream-3",
            turn_id="turn-3",
            delta="hello",
        )
        await bridge.persist_and_publish_assistant_message(
            "client-session-1",
            content="hello persisted",
            stream_id="stream-3",
            turn_id="turn-3",
        )

        self.assertEqual(len(run_service.created), 1)
        self.assertEqual([item["type"] for item in run_event_service.events], ["message.delta", "message.completed"])
        self.assertEqual(gateway.run_events[0]["event"]["type"], "message.delta")
        self.assertEqual(gateway.run_events[0]["event"]["payload"]["delta"], "hello")
        self.assertEqual(gateway.run_events[1]["event"]["type"], "message.completed")
        self.assertEqual(gateway.run_events[1]["event"]["payload"]["message"]["content"], "hello persisted")
        self.assertEqual(gateway.messages[0]["message"]["content"], "hello persisted")
        self.assertEqual(gateway.messages[0]["message"]["role"], "assistant")
        self.assertEqual(run_service.statuses[0]["status"], "succeeded")
        self.assertEqual(len(message_service.created), 1)

    async def test_progress_notice_emits_run_event_without_assistant_message(self):
        session_manager = SessionManager()
        session_manager.bind_runtime_session(
            source=SimpleNamespace(kind="system", id="agent:desktop-main-agent", metadata={}),
            session_id="system:agent:desktop-main-agent",
            default_target=EventTarget(kind=TargetKind.INTERNAL.value, id="desktop-main-agent"),
            metadata={
                "thread_id": "thr_recent",
                "workspace_id": "desktop-main",
                "endpoint_id": "desktop-app",
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
            origin_endpoint_id=5,
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

        result = await bridge.publish_progress_notice(
            "system:agent:desktop-main-agent",
            content="I will check that.",
            stream_id="stream-1",
            turn_id="turn-1",
        )

        self.assertTrue(result["delivered"])
        self.assertEqual(message_service.created, [])
        self.assertEqual(gateway.thread_events[0]["event_type"], "assistant.progress_notice")
        self.assertEqual(gateway.thread_events[0]["payload"]["type"], "assistant.progress_notice")
        self.assertEqual(gateway.thread_events[0]["payload"]["payload"]["text"], "I will check that.")
        self.assertEqual(gateway.thread_events[0]["payload"]["stream_id"], "stream-1")
        self.assertFalse(gateway.thread_events[0]["payload"]["durable"])

    async def test_app_progress_notice_only_allowed_during_active_turn(self):
        app = App.__new__(App)
        bridge = _ShortReplyBridgeStub()
        app._get_client_thread_bridge = lambda: bridge
        app.brain = _BrainStub({"status": RuntimeStatus.IDLE.value, "turn_id": "turn-1", "stream_id": "stream-1"})

        rejected = await App.emit_progress_notice(app, "not now", session_id="sess-1", turn_id="turn-1")

        self.assertFalse(rejected["delivered"])
        self.assertEqual(rejected["reason"], "progress_notice_not_allowed")
        self.assertEqual(bridge.calls, [])

        app.brain = _BrainStub({"status": RuntimeStatus.TOOL_CALLING.value, "turn_id": "turn-1", "stream_id": "stream-1"})
        accepted = await App.emit_progress_notice(app, "checking", session_id="sess-1", turn_id="turn-1")

        self.assertTrue(accepted["delivered"])
        self.assertEqual(bridge.calls[0]["content"], "checking")
        self.assertEqual(bridge.calls[0]["turn_id"], "turn-1")
        self.assertEqual(bridge.calls[0]["stream_id"], "stream-1")

    def test_required_non_streaming_progress_notice_can_be_runtime_started(self):
        self.assertEqual(
            _initial_progress_notice_content(
                {
                    "supports_streaming_reply": False,
                    "progress_notice_policy": "required_before_nontrivial_final",
                    "progress_notice_content": "Working on it",
                }
            ),
            "Working on it",
        )
        self.assertEqual(
            _initial_progress_notice_content(
                {
                    "supports_streaming_reply": False,
                    "progress_notice_policy": "prefer_before_nontrivial_final",
                    "progress_notice_content": "Working on it",
                }
            ),
            "",
        )
        self.assertEqual(
            _initial_progress_notice_content(
                {
                    "supports_streaming_reply": True,
                    "progress_notice_policy": "required_before_nontrivial_final",
                    "progress_notice_content": "Working on it",
                }
            ),
            "",
        )


if __name__ == "__main__":
    unittest.main()

