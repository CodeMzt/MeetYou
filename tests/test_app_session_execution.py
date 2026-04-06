import asyncio
import unittest

from core.app import App
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

    async def emit_stream_end(self, session_id, source, stream_id, target=None, stream_channel="answer"):
        self.stream_ends.append(
            {
                "session_id": session_id,
                "source": source,
                "stream_id": stream_id,
                "target": target,
                "stream_channel": stream_channel,
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
        }
        self.runtime_snapshots[session_id] = snapshot
        return snapshot

    def get_session_runtime_snapshot(self, session_id: str):
        return self.runtime_snapshots.get(session_id)

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
    ):
        del input_info, api_key, api_url, model, provider_name, tool_activity_callback, model_options
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


class AppSessionExecutionTests(unittest.IsolatedAsyncioTestCase):
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


async def _async_noop(*args, **kwargs):
    return None


if __name__ == "__main__":
    unittest.main()
