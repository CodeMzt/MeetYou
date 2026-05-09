import asyncio
from datetime import datetime, timezone
import unittest

from core.app import App, SessionExecutionRequest
from core.brain import BrainOutputEvent
from core.event_bus import EventBus
from core.io_protocol import InboundEvent, SourceKind, make_source
from core.runtime_context import get_event_context
from core.session_actor import SessionActorRuntime
from core.status import RuntimeStatus


class _FakeConfig:
    def get(self, key: str):
        values = {
            "api_key": "key",
            "api_url": "https://api.test.local/v1",
            "model": "gpt-4o-mini",
            "api_provider": "openai",
        }
        return values.get(key, "")


class _FakeSpeaker:
    def __init__(self):
        self.events = []
        self.errors = []
        self.stream_starts = []
        self.stream_chunks = []
        self.stream_ends = []
        self.statuses = []

    async def emit(self, event):
        self.events.append(event)

    async def emit_error(self, session_id, message, source, target=None, stream_id="", metadata=None):
        self.errors.append(
            {
                "session_id": session_id,
                "message": message,
                "source": source,
                "target": target,
                "stream_id": stream_id,
                "metadata": dict(metadata or {}),
            }
        )

    async def emit_status(self, session_id, content, source, target=None, metadata=None):
        self.statuses.append(
            {
                "session_id": session_id,
                "content": content,
                "source": source,
                "target": target,
                "metadata": dict(metadata or {}),
            }
        )

    async def emit_stream_start(self, session_id, source, target=None, stream_channel="answer"):
        stream_id = f"stream-{session_id}-{len(self.stream_starts) + 1}"
        self.stream_starts.append(
            {
                "session_id": session_id,
                "source": source,
                "target": target,
                "stream_channel": stream_channel,
                "stream_id": stream_id,
            }
        )
        return stream_id

    async def emit_stream_chunk(self, session_id, content, source, stream_id, target=None, stream_channel="answer"):
        self.stream_chunks.append(
            {
                "session_id": session_id,
                "content": content,
                "source": source,
                "stream_id": stream_id,
                "target": target,
                "stream_channel": stream_channel,
            }
        )

    async def emit_stream_end(self, session_id, source, stream_id, target=None, stream_channel="answer", metadata=None):
        self.stream_ends.append(
            {
                "session_id": session_id,
                "source": source,
                "stream_id": stream_id,
                "target": target,
                "stream_channel": stream_channel,
                "metadata": dict(metadata or {}),
            }
        )


class _FakeBrain:
    def __init__(self):
        self.runtime_snapshots = {}
        self.started_session_1 = asyncio.Event()
        self.started_session_2 = asyncio.Event()
        self.release_session_1 = asyncio.Event()
        self.contexts = {}
        self.start_order = []

    def set_session_runtime_state(
        self,
        session_id: str,
        status: str,
        detail: str = "",
        active_tools=None,
        current_mode=None,
        route_reason=None,
        action_risk=None,
        source_profile=None,
        stream_id=None,
        turn_id=None,
        finish_reason=None,
        reply_control=None,
    ):
        snapshot = {
            "session_id": session_id,
            "status": status,
            "detail": detail,
            "active_tools": list(active_tools or []),
            "current_mode": current_mode or "",
            "route_reason": route_reason or "",
            "action_risk": action_risk or "read",
            "source_profile": source_profile or "",
            "stream_id": stream_id or "",
            "turn_id": turn_id or "",
            "finish_reason": finish_reason or "",
            "reply_control": dict(reply_control or {}),
        }
        self.runtime_snapshots[session_id] = snapshot
        return snapshot

    def get_session_runtime_snapshot(self, session_id: str):
        return self.runtime_snapshots.get(session_id)

    def request_reply_control(
        self,
        session_id: str,
        *,
        action: str,
        request_id: str,
        guidance: str = "",
        checkpoint_id: str = "",
        turn_id: str = "",
        stream_id: str = "",
    ):
        del session_id, request_id, guidance, checkpoint_id, turn_id, stream_id
        return {"action": action, "status": "rejected", "reason": "unsupported in fake"}

    def finalize_reply_control(self, session_id: str, *, turn_id: str, interrupted: bool):
        del session_id, turn_id, interrupted
        return {"finish_reason": "stopped", "replay_input": None, "control_result": None}

    def mark_reply_turn_failed(self, session_id: str, *, turn_id: str):
        del session_id, turn_id
        return None

    def discard_trailing_transient_messages(self, session_id: str):
        return None

    async def close_session(self, session_id: str):
        return None

    async def input_brain(
        self,
        session_id: str,
        input_info: dict,
        api_key: str,
        api_url: str,
        model: str,
        provider_name: str = "",
        tool_activity_callback=None,
        model_options: dict | None = None,
        phase_callback=None,
        cancel_event=None,
    ):
        del input_info, api_key, api_url, model, provider_name, tool_activity_callback, model_options, cancel_event
        self.start_order.append(session_id)
        self.contexts[session_id] = get_event_context()
        if session_id == "session-1":
            self.started_session_1.set()
            await self.release_session_1.wait()
        elif session_id == "session-2":
            self.started_session_2.set()
        if phase_callback is not None:
            await phase_callback(RuntimeStatus.ANSWERING.value, "Generating answer", [])
        yield BrainOutputEvent(type="answer_text", text=f"done-{session_id}")
        yield BrainOutputEvent(
            type="usage",
            usage={
                "session_id": session_id,
                "usage_ready": True,
                "context_limit_tokens": 128000,
                "context_limit_source": "config_override",
                "context_limit_model": "gpt-4o-mini",
                "context_limit_confidence": "high",
                "current_context_tokens_estimated": 32,
                "context_breakdown": {
                    "system": 0,
                    "history": 0,
                    "tool_history": 0,
                    "memory_context": 0,
                    "policy": 0,
                    "current_input": 0,
                    "proprioception": 0,
                    "total": 32,
                },
                "last_turn_usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 3,
                    "reasoning_tokens": 0,
                    "total_tokens": 11,
                },
                "session_totals": {
                    "prompt_tokens": 8,
                    "completion_tokens": 3,
                    "reasoning_tokens": 0,
                    "total_tokens": 11,
                    "turn_count": 1,
                },
                "usage_source": "provider",
            },
        )
        yield BrainOutputEvent(type="done")


class _ReplyControlBrain(_FakeBrain):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.replay_inputs = []

    def request_reply_control(
        self,
        session_id: str,
        *,
        action: str,
        request_id: str,
        guidance: str = "",
        checkpoint_id: str = "",
        turn_id: str = "",
        stream_id: str = "",
    ):
        del request_id, checkpoint_id, turn_id, stream_id
        self.last_guidance = guidance
        return {"action": action, "status": "accepted", "session_id": session_id}

    def finalize_reply_control(self, session_id: str, *, turn_id: str, interrupted: bool):
        del session_id, turn_id, interrupted
        return {
            "finish_reason": "replayed",
            "replay_input": {
                "role": "user",
                "content": f"first\n\n补充要求：{self.last_guidance}",
                "metadata": {"reply_control_replay": "append_guidance"},
            },
            "control_result": {"action": "append_guidance", "status": "completed"},
        }

    async def input_brain(
        self,
        session_id: str,
        input_info: dict,
        api_key: str,
        api_url: str,
        model: str,
        provider_name: str = "",
        tool_activity_callback=None,
        model_options: dict | None = None,
        phase_callback=None,
        cancel_event=None,
    ):
        del api_key, api_url, model, provider_name, tool_activity_callback, model_options, cancel_event
        if input_info.get("metadata", {}).get("reply_control_replay") == "append_guidance":
            self.replay_inputs.append(input_info["content"])
            if phase_callback is not None:
                await phase_callback(RuntimeStatus.ANSWERING.value, "Generating answer", [])
            yield BrainOutputEvent(type="answer_text", text="replayed-answer")
            yield BrainOutputEvent(type="done")
            return
        self.started.set()
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class _StopReplyControlBrain(_ReplyControlBrain):
    def request_reply_control(
        self,
        session_id: str,
        *,
        action: str,
        request_id: str,
        guidance: str = "",
        checkpoint_id: str = "",
        turn_id: str = "",
        stream_id: str = "",
    ):
        del request_id, guidance, checkpoint_id, turn_id, stream_id
        return {"action": action, "status": "accepted", "session_id": session_id}

    def finalize_reply_control(self, session_id: str, *, turn_id: str, interrupted: bool):
        del session_id, turn_id, interrupted
        return {
            "finish_reason": "stopped",
            "replay_input": None,
            "control_result": {"action": "stop", "status": "completed"},
        }


class _ImmediateReplayControlBrain(_FakeBrain):
    def __init__(self):
        super().__init__()
        self.replay_inputs = []
        self.input_calls = 0

    def request_reply_control(
        self,
        session_id: str,
        *,
        action: str,
        request_id: str,
        guidance: str = "",
        checkpoint_id: str = "",
        turn_id: str = "",
        stream_id: str = "",
    ):
        del session_id, request_id, guidance, checkpoint_id, turn_id, stream_id
        if action == "regenerate":
            return {
                "action": action,
                "status": "completed",
                "replay_input": {
                    "role": "user",
                    "content": "first",
                    "metadata": {"reply_control_replay": "regenerate"},
                },
            }
        if action == "rollback":
            return {
                "action": action,
                "status": "completed",
                "checkpoint": {"checkpoint_id": "cp-1"},
            }
        return {"action": action, "status": "rejected", "reason": "unsupported"}

    async def input_brain(
        self,
        session_id: str,
        input_info: dict,
        api_key: str,
        api_url: str,
        model: str,
        provider_name: str = "",
        tool_activity_callback=None,
        model_options: dict | None = None,
        phase_callback=None,
        cancel_event=None,
    ):
        del session_id, api_key, api_url, model, provider_name, tool_activity_callback, model_options, cancel_event
        self.input_calls += 1
        self.replay_inputs.append(input_info["content"])
        if phase_callback is not None:
            await phase_callback(RuntimeStatus.ANSWERING.value, "Generating answer", [])
        yield BrainOutputEvent(type="answer_text", text="regenerated-answer")
        yield BrainOutputEvent(type="done")


class _GatewayStub:
    def __init__(self):
        self.thread_events = []

    async def publish_thread_delivery_event(self, thread_id: str, *, event_type: str, payload: dict):
        self.thread_events.append({"thread_id": thread_id, "event_type": event_type, "payload": dict(payload)})


class _MessageServiceStub:
    def __init__(self):
        self.created = []

    def create_message(self, **kwargs):
        self.created.append(dict(kwargs))
        return type(
            "MessageRecord",
            (),
            {
                "message_id": "msg_assistant_1",
                "role": kwargs.get("role", "assistant"),
                "content": kwargs.get("content", ""),
                "status": kwargs.get("status", "completed"),
                "channel": kwargs.get("channel", "message"),
                "created_at": datetime.now(timezone.utc),
            },
        )()


class _CoreServicesStub:
    def __init__(self):
        self.message = _MessageServiceStub()
        self.session = type(
            "SessionServiceStub",
            (),
            {"get_by_session_id": staticmethod(lambda session_id: type("S", (), {"id": "row-session-1", "thread_id": "row-thread-1", "session_id": session_id})())},
        )()
        self.thread = type(
            "ThreadServiceStub",
            (),
            {"get_by_id": staticmethod(lambda row_id: type("T", (), {"id": row_id, "thread_id": "thr_test", "workspace_id": "row-workspace-1"})())},
        )()
        self.workspace = type(
            "WorkspaceServiceStub",
            (),
            {"get_by_id": staticmethod(lambda row_id: type("W", (), {"id": row_id, "workspace_id": "personal"})())},
        )()


class AppSessionExecutionTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _build_app(brain):
        app = App.__new__(App)
        app.event_bus = EventBus()
        app.config = _FakeConfig()
        app.brain = brain
        app.speaker = _FakeSpeaker()
        app.session_manager = type(
            "_SessionManagerStub",
            (),
            {"get_default_target": staticmethod(lambda session_id: type("T", (), {"kind": "current_session", "id": "", "metadata": {}})())},
        )()
        app._brain_source = make_source(SourceKind.SYSTEM.value, "brain")
        app._runtime_source = make_source(SourceKind.SYSTEM.value, "runtime")
        app._usage_source = make_source(SourceKind.SYSTEM.value, "usage")
        app._control_source = make_source(SourceKind.SYSTEM.value, "reply_control")
        app._get_main_provider = lambda: "openai"
        app._build_model_options = lambda metadata=None: {}
        app._emit_pending_task_updates = _async_noop
        app._is_heartbeat_signal = lambda event: False
        app._recent_user_delivery = lambda: None
        app._build_signal_input = lambda event: {
            "role": event.role,
            "content": event.content,
            "metadata": dict(getattr(event, "metadata", {}) or {}),
        }
        app._session_execution_runtime = SessionActorRuntime(app._process_session_execution)
        return app

    def test_enriches_input_info_with_project_context_from_thread(self):
        app = App.__new__(App)
        project = type(
            "Project",
            (),
            {
                "project_id": "prj_1",
                "title": "论文项目",
                "description": "跟踪研究材料",
                "instructions": "优先使用项目源。",
                "status": "active",
            },
        )()
        source = type(
            "ProjectSource",
            (),
            {
                "source_id": "src_1",
                "source_type": "note",
                "title": "研究笔记",
                "content_type": "text",
                "content": "项目源正文",
                "updated_at": datetime(2026, 5, 9, tzinfo=timezone.utc),
            },
        )()
        app.core_domain = type(
            "Domain",
            (),
            {
                "services": type(
                    "Services",
                    (),
                    {
                        "thread": type(
                            "ThreadService",
                            (),
                            {
                                "get_by_thread_id": staticmethod(
                                    lambda thread_id: type("Thread", (), {"project_id": "row-project-1"})()
                                )
                            },
                        )(),
                        "project": type(
                            "ProjectService",
                            (),
                            {
                                "get_by_id": staticmethod(lambda row_id: project),
                                "list_sources": staticmethod(lambda project_id, limit=5: [source]),
                            },
                        )(),
                    },
                )()
            },
        )()
        input_info = {
            "role": "user",
            "content": "请按项目要求回答",
            "metadata": {"thread_id": "thr_1"},
        }

        app._enrich_input_info_with_project_context(input_info)

        metadata = input_info["metadata"]
        self.assertEqual(metadata["project_id"], "prj_1")
        self.assertEqual(metadata["project_instructions"], "优先使用项目源。")
        self.assertEqual(metadata["project_sources"][0]["source_id"], "src_1")
        self.assertEqual(metadata["project_sources"][0]["content"], "项目源正文")

    async def test_brain_processor_runs_sessions_in_parallel_and_binds_context(self):
        app = App.__new__(App)
        app.event_bus = EventBus()
        app.config = _FakeConfig()
        app.brain = _FakeBrain()
        app.speaker = _FakeSpeaker()
        app._brain_source = make_source(SourceKind.SYSTEM.value, "brain")
        app._runtime_source = make_source(SourceKind.SYSTEM.value, "runtime")
        app._usage_source = make_source(SourceKind.SYSTEM.value, "usage")
        app._get_main_provider = lambda: "openai"
        app._build_model_options = lambda metadata=None: {}
        app._emit_pending_task_updates = _async_noop
        app._is_heartbeat_signal = lambda event: False
        app._recent_user_delivery = lambda: None
        app._build_signal_input = lambda event: {
            "role": event.role,
            "content": event.content,
            "metadata": dict(getattr(event, "metadata", {}) or {}),
        }
        app._session_execution_runtime = SessionActorRuntime(app._process_session_execution)

        processor_task = asyncio.create_task(App.brain_processor(app))
        try:
            await app.event_bus.inbound_queue.put(
                InboundEvent(
                    session_id="session-1",
                    type="message",
                    role="user",
                    content="first",
                    source=make_source(SourceKind.WEB.value, "tab-1"),
                )
            )
            await app.event_bus.inbound_queue.put(
                InboundEvent(
                    session_id="session-2",
                    type="message",
                    role="user",
                    content="second",
                    source=make_source(SourceKind.WEB.value, "tab-2"),
                )
            )

            await asyncio.wait_for(
                asyncio.gather(
                    app.brain.started_session_1.wait(),
                    app.brain.started_session_2.wait(),
                ),
                timeout=1.0,
            )
            app.brain.release_session_1.set()
            await asyncio.wait_for(app._session_execution_runtime.join(), timeout=1.0)
            app.event_bus.request_shutdown()
            await asyncio.wait_for(processor_task, timeout=1.0)
        finally:
            if not processor_task.done():
                app.event_bus.request_shutdown()
                await asyncio.wait_for(processor_task, timeout=1.0)

        self.assertEqual(app.brain.start_order, ["session-1", "session-2"])
        self.assertEqual(app.brain.contexts["session-1"]["session_id"], "session-1")
        self.assertEqual(app.brain.contexts["session-2"]["session_id"], "session-2")
        self.assertEqual(app.brain.contexts["session-1"]["target"].kind, "current_session")
        self.assertEqual(app.brain.contexts["session-2"]["target"].kind, "current_session")
        self.assertEqual(app.brain.runtime_snapshots["session-1"]["status"], RuntimeStatus.IDLE.value)
        self.assertEqual(app.brain.runtime_snapshots["session-2"]["status"], RuntimeStatus.IDLE.value)

        usage_events = [event for event in app.speaker.events if event.type == "usage"]
        self.assertCountEqual(
            [event.session_id for event in usage_events],
            ["session-1", "session-2"],
        )

    async def test_reply_control_stop_cancels_current_turn_without_replay(self):
        app = self._build_app(_StopReplyControlBrain())

        processor_task = asyncio.create_task(App.brain_processor(app))
        try:
            await app.event_bus.inbound_queue.put(
                InboundEvent(
                    session_id="session-1",
                    type="message",
                    role="user",
                    content="first",
                    source=make_source(SourceKind.WEB.value, "tab-1"),
                )
            )
            await asyncio.wait_for(app.brain.started.wait(), timeout=1.0)
            await app.event_bus.inbound_queue.put(
                InboundEvent(
                    session_id="session-1",
                    type="control",
                    role="system",
                    content={"action": "stop"},
                    source=make_source(SourceKind.WEB.value, "tab-1"),
                    metadata={"control_kind": "reply_control"},
                )
            )
            await asyncio.wait_for(app._session_execution_runtime.join("session-1"), timeout=2.0)
            app.event_bus.request_shutdown()
            await asyncio.wait_for(processor_task, timeout=1.0)
        finally:
            if not processor_task.done():
                app.event_bus.request_shutdown()
                await asyncio.wait_for(processor_task, timeout=1.0)

        self.assertTrue(app.brain.cancelled.is_set())
        self.assertEqual(app.brain.replay_inputs, [])
        self.assertEqual(app.brain.runtime_snapshots["session-1"]["status"], RuntimeStatus.IDLE.value)
        self.assertEqual(app.brain.runtime_snapshots["session-1"]["finish_reason"], "stopped")
        finish_reasons = [item["metadata"].get("finish_reason", "") for item in app.speaker.stream_ends]
        self.assertIn("stopped", finish_reasons)
        control_events = [event for event in app.speaker.events if event.type == "control"]
        self.assertTrue(any(event.content.get("action") == "stop" and event.content.get("status") == "completed" for event in control_events))

    async def test_reply_control_append_guidance_cancels_and_replays_current_turn(self):
        app = self._build_app(_ReplyControlBrain())

        processor_task = asyncio.create_task(App.brain_processor(app))
        try:
            await app.event_bus.inbound_queue.put(
                InboundEvent(
                    session_id="session-1",
                    type="message",
                    role="user",
                    content="first",
                    source=make_source(SourceKind.WEB.value, "tab-1"),
                )
            )
            await asyncio.wait_for(app.brain.started.wait(), timeout=1.0)
            await app.event_bus.inbound_queue.put(
                InboundEvent(
                    session_id="session-1",
                    type="control",
                    role="system",
                    content={"action": "append_guidance", "guidance": "更简短"},
                    source=make_source(SourceKind.WEB.value, "tab-1"),
                    metadata={"control_kind": "reply_control"},
                )
            )
            await asyncio.wait_for(app._session_execution_runtime.join("session-1"), timeout=2.0)
            app.event_bus.request_shutdown()
            await asyncio.wait_for(processor_task, timeout=1.0)
        finally:
            if not processor_task.done():
                app.event_bus.request_shutdown()
                await asyncio.wait_for(processor_task, timeout=1.0)

        self.assertTrue(app.brain.cancelled.is_set())
        self.assertEqual(app.brain.replay_inputs, ["first\n\n补充要求：更简短"])
        finish_reasons = [item["metadata"].get("finish_reason", "") for item in app.speaker.stream_ends]
        self.assertIn("replayed", finish_reasons)
        control_events = [event for event in app.speaker.events if event.type == "control"]
        self.assertTrue(any(event.content.get("status") == "completed" for event in control_events))

    async def test_reply_control_regenerate_replays_latest_input_when_idle(self):
        app = self._build_app(_ImmediateReplayControlBrain())

        processor_task = asyncio.create_task(App.brain_processor(app))
        try:
            await app.event_bus.inbound_queue.put(
                InboundEvent(
                    session_id="session-1",
                    type="control",
                    role="system",
                    content={"action": "regenerate"},
                    source=make_source(SourceKind.WEB.value, "tab-1"),
                    metadata={"control_kind": "reply_control"},
                )
            )
            await asyncio.wait_for(_wait_until(lambda: app.brain.input_calls == 1), timeout=2.0)
            await asyncio.wait_for(app._session_execution_runtime.join("session-1"), timeout=2.0)
            app.event_bus.request_shutdown()
            await asyncio.wait_for(processor_task, timeout=1.0)
        finally:
            if not processor_task.done():
                app.event_bus.request_shutdown()
                await asyncio.wait_for(processor_task, timeout=1.0)

        self.assertEqual(app.brain.replay_inputs, ["first"])
        self.assertEqual(app.brain.input_calls, 1)
        self.assertTrue(any(item["content"] == "regenerated-answer" for item in app.speaker.stream_chunks))
        control_events = [event for event in app.speaker.events if event.type == "control"]
        self.assertTrue(any(event.content.get("action") == "regenerate" and event.content.get("status") == "completed" for event in control_events))

    async def test_reply_control_rollback_completes_without_spawning_new_turn(self):
        app = self._build_app(_ImmediateReplayControlBrain())

        processor_task = asyncio.create_task(App.brain_processor(app))
        try:
            await app.event_bus.inbound_queue.put(
                InboundEvent(
                    session_id="session-1",
                    type="control",
                    role="system",
                    content={"action": "rollback", "checkpoint_id": "cp-1"},
                    source=make_source(SourceKind.WEB.value, "tab-1"),
                    metadata={"control_kind": "reply_control"},
                )
            )
            await asyncio.wait_for(
                _wait_until(
                    lambda: any(
                        event.content.get("action") == "rollback"
                        for event in app.speaker.events
                        if event.type == "control"
                    )
                ),
                timeout=1.0,
            )
            app.event_bus.request_shutdown()
            await asyncio.wait_for(processor_task, timeout=1.0)
        finally:
            if not processor_task.done():
                app.event_bus.request_shutdown()
                await asyncio.wait_for(processor_task, timeout=1.0)

        self.assertEqual(app.brain.input_calls, 0)
        self.assertEqual(app.speaker.stream_starts, [])
        control_events = [event for event in app.speaker.events if event.type == "control"]
        self.assertTrue(any(event.content.get("action") == "rollback" and event.content.get("status") == "completed" for event in control_events))

    async def test_process_session_execution_publishes_client_thread_events(self):
        app = self._build_app(_ImmediateReplayControlBrain())
        app.gateway = _GatewayStub()
        app.core_services = _CoreServicesStub()

        request = SessionExecutionRequest(
            session_id="session-1",
            event=InboundEvent(
                session_id="session-1",
                type="message",
                role="user",
                content="first",
                source=make_source(SourceKind.WEB.value, "tab-1"),
            ),
            input_info={"role": "user", "content": "first", "metadata": {}},
            target=type("Target", (), {"kind": "current_session", "id": "", "metadata": {}})(),
            is_boot=False,
        )

        await app._process_session_execution(request)

        event_types = [item["event_type"] for item in app.gateway.thread_events]
        self.assertIn("runtime.state", event_types)
        self.assertIn("message.delta", event_types)
        self.assertIn("message.completed", event_types)
        self.assertEqual(app.gateway.thread_events[-1]["thread_id"], "thr_test")
        self.assertEqual(app.core_services.message.created[-1]["content"], "regenerated-answer")


async def _async_noop(*args, **kwargs):
    return None


async def _wait_until(predicate, interval: float = 0.01):
    while not predicate():
        await asyncio.sleep(interval)


if __name__ == "__main__":
    unittest.main()
