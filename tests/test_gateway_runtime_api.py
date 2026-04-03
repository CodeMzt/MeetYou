import unittest

from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway


class GatewayRuntimeApiTests(unittest.TestCase):
    def setUp(self):
        self.event_bus = EventBus()

        self.gateway = FastAPIGateway(
            self.event_bus,
            SessionManager(),
            runtime_state_getter=lambda session_id="": {
                "global_state": {
                    "session_id": "system:global",
                    "status": "idle",
                    "detail": "",
                    "active_tools": [],
                    "current_mode": "",
                    "route_reason": "",
                    "action_risk": "read",
                    "source_profile": "",
                    "stream_id": "",
                    "turn_id": "",
                    "updated_at": "2026-04-01T00:00:00Z",
                },
                "heartbeat_state": {
                    "session_id": "system:heart",
                    "status": "heartbeat",
                    "detail": "tick",
                    "active_tools": ["heartbeat"],
                    "current_mode": "",
                    "route_reason": "",
                    "action_risk": "read",
                    "source_profile": "",
                    "stream_id": "",
                    "turn_id": "",
                    "updated_at": "2026-04-01T00:00:01Z",
                },
                "session_state": {
                    "session_id": session_id,
                    "status": "thinking",
                    "detail": "Calling model",
                    "active_tools": ["search_memory"],
                    "current_mode": "research",
                    "route_reason": "Matched research signals: latest, direct_url",
                    "action_risk": "read",
                    "source_profile": "tech_global",
                    "stream_id": "stream-1",
                    "turn_id": "turn-1",
                    "updated_at": "2026-04-01T00:00:02Z",
                } if session_id else None,
            },
            runtime_usage_getter=lambda session_id: {
                "session_id": session_id,
                "usage_ready": True,
                "context_limit_tokens": 128000,
                "context_limit_source": "config_override",
                "context_limit_model": "deepseek-reasoner",
                "context_limit_confidence": "high",
                "current_context_tokens_estimated": 2048,
                "context_breakdown": {
                    "system": 200,
                    "history": 800,
                    "tool_history": 128,
                    "memory_context": 256,
                    "policy": 256,
                    "current_input": 128,
                    "proprioception": 280,
                    "total": 2048,
                },
                "last_turn_usage": {
                    "prompt_tokens": 900,
                    "completion_tokens": 120,
                    "reasoning_tokens": 44,
                    "total_tokens": 1064,
                },
                "session_totals": {
                    "prompt_tokens": 1900,
                    "completion_tokens": 240,
                    "reasoning_tokens": 88,
                    "total_tokens": 2228,
                    "turn_count": 2,
                },
                "usage_source": "provider",
                "updated_at": "2026-04-01T00:00:03Z",
            },
        )
        self.client = TestClient(self.gateway.app)
        self.addCleanup(self.client.close)

    def test_post_inputs_accepts_thinking_options(self):
        response = self.client.post(
            "/inputs",
            json={
                "content": "hello",
                "session_id": "web:session:1",
                "source_id": "browser-tab-a",
                "preferred_mode": "research",
                "metadata": {"page": "chat"},
                "options": {
                    "thinking": {
                        "enabled": True,
                        "effort": "high",
                        "budget_tokens": 512,
                    }
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["accepted"])
        self.assertEqual(payload["session_id"], "web:session:1")

        queued_event = self.event_bus.inbound_queue.get_nowait()
        self.assertEqual(queued_event.content, "hello")
        self.assertEqual(queued_event.metadata["page"], "chat")
        self.assertEqual(queued_event.metadata["preferred_mode"], "research")
        self.assertEqual(
            queued_event.metadata["input_options"]["thinking"],
            {"enabled": True, "effort": "high", "budget_tokens": 512},
        )

    def test_post_inputs_deduplicates_same_client_message_id(self):
        payload = {
            "content": "hello once",
            "session_id": "web:session:dedup",
            "source_id": "browser-tab-a",
            "client_message_id": "msg-001",
            "role": "user",
        }

        first = self.client.post("/inputs", json=payload)
        second = self.client.post("/inputs", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

        first_payload = first.json()
        second_payload = second.json()
        self.assertEqual(first_payload["event_id"], second_payload["event_id"])

        queued_event = self.event_bus.inbound_queue.get_nowait()
        self.assertEqual(queued_event.content, "hello once")
        self.assertEqual(queued_event.metadata["client_message_id"], "msg-001")
        self.assertTrue(self.event_bus.inbound_queue.empty())

    def test_get_runtime_state(self):
        response = self.client.get("/runtime/state", params={"session_id": "web:session:1"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["global_state"]["status"], "idle")
        self.assertEqual(payload["heartbeat_state"]["status"], "heartbeat")
        self.assertEqual(payload["session_state"]["status"], "thinking")
        self.assertEqual(payload["session_state"]["current_mode"], "research")
        self.assertEqual(payload["session_state"]["source_profile"], "tech_global")
        self.assertEqual(payload["session_state"]["turn_id"], "turn-1")

    def test_get_runtime_usage(self):
        response = self.client.get("/runtime/usage", params={"session_id": "web:session:1"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["session_id"], "web:session:1")
        self.assertTrue(payload["usage_ready"])
        self.assertEqual(payload["context_limit_source"], "config_override")
        self.assertEqual(payload["context_limit_model"], "deepseek-reasoner")
        self.assertEqual(payload["context_breakdown"]["total"], 2048)
        self.assertEqual(payload["last_turn_usage"]["reasoning_tokens"], 44)
        self.assertEqual(payload["session_totals"]["turn_count"], 2)
        self.assertEqual(payload["usage_source"], "provider")


if __name__ == "__main__":
    unittest.main()
