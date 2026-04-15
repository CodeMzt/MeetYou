import os
import sys
import time
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import App
from core.io_protocol import EventTarget, EventType, InboundEvent, SourceKind, TargetKind, make_source
from core.session_manager import SessionManager


class _FakeWsManager:
    def __init__(self, sessions=None):
        self._sessions = set(sessions or [])

    def has_session(self, session_id: str) -> bool:
        return session_id in self._sessions


class _FakeClientWsManager:
    def __init__(self, threads=None):
        self._threads = set(threads or [])

    def has_connections(self, thread_id: str) -> bool:
        return thread_id in self._threads


class _FakeGateway:
    def __init__(self, sessions=None, threads=None):
        self.ws_manager = _FakeWsManager(sessions=sessions)
        self.client_ws_manager = _FakeClientWsManager(threads=threads)


class HeartbeatSignalRoutingTests(unittest.TestCase):
    def test_session_manager_tracks_recent_bindings(self):
        manager = SessionManager()
        web_source = make_source(SourceKind.WEB.value, "tab-a")
        feishu_source = make_source(SourceKind.FEISHU.value, "chat-a")

        web_session = manager.get_or_create_session(web_source, "web:1")
        time.sleep(0.01)
        feishu_session = manager.get_or_create_session(feishu_source, "feishu:1")

        recent = manager.list_recent_bindings()

        self.assertEqual([binding.session_id for binding in recent[:2]], [feishu_session, web_session])

    def test_recent_user_delivery_prefers_deliverable_active_session(self):
        manager = SessionManager()
        manager.get_or_create_session(make_source(SourceKind.SYSTEM.value, "boot"), "system:boot")
        manager.bind_runtime_session(
            make_source(SourceKind.WEB.value, "tab-old"),
            "web:old",
            metadata={"thread_id": "thr-old"},
        )
        manager.bind_runtime_session(
            make_source(SourceKind.FEISHU.value, "chat-live"),
            "feishu:live",
            metadata={"thread_id": "thr-feishu"},
        )
        manager.bind_runtime_session(
            make_source(SourceKind.WEB.value, "tab-live"),
            "web:live",
            metadata={"thread_id": "thr-live"},
        )

        manager.set_default_target("feishu:live", EventTarget(kind=TargetKind.FEISHU.value, id="chat-live"))
        manager.set_default_target("web:live", EventTarget(kind=TargetKind.WEB.value, id="tab-live"))
        time.sleep(0.01)
        manager.touch_session("web:live")

        app = App.__new__(App)
        app.session_manager = manager
        app.core_services = None
        app.gateway = _FakeGateway(threads={"thr-live"})

        session_id, target = App._recent_user_delivery(app)

        self.assertEqual(session_id, "web:live")
        self.assertEqual(target.kind, TargetKind.WEB.value)
        self.assertEqual(target.id, "tab-live")

    def test_recent_user_delivery_supports_feishu_formal_client_thread(self):
        manager = SessionManager()
        manager.bind_runtime_session(
            make_source(SourceKind.FEISHU.value, "chat-live"),
            "feishu:live",
            metadata={"thread_id": "thr-feishu-live"},
        )
        manager.set_default_target("feishu:live", EventTarget(kind=TargetKind.FEISHU.value, id="chat-live"))

        app = App.__new__(App)
        app.session_manager = manager
        app.core_services = None
        app.gateway = _FakeGateway(threads={"thr-feishu-live"})

        session_id, target = App._recent_user_delivery(app)

        self.assertEqual(session_id, "feishu:live")
        self.assertEqual(target.kind, TargetKind.FEISHU.value)
        self.assertEqual(target.id, "chat-live")

    def test_signal_input_keeps_normal_conversation_style(self):
        app = App.__new__(App)
        event = InboundEvent(
            session_id="system:heart",
            type=EventType.SIGNAL.value,
            role="system",
            content="A scheduled task has failed repeatedly.",
            source=make_source(SourceKind.HEART.value, "system"),
            target=EventTarget(kind=TargetKind.INTERNAL.value),
            metadata={"heartbeat_decision": "escalate", "heartbeat_signal_kind": "system_issue"},
        )

        payload = App._build_signal_input(app, event)
        text = payload["content"]

        self.assertIn("same style as the current conversation", text)
        self.assertIn("Do not switch into a special alerting or ops tone", text)
        self.assertIn("A scheduled task has failed repeatedly.", text)
        self.assertTrue(payload["metadata"]["transient"])
        self.assertTrue(payload["metadata"]["disable_tools"])


if __name__ == "__main__":
    unittest.main()
