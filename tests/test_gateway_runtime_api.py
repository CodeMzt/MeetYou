import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway
from gateway.routes.runtime import _resolve_runtime_source_kind


class GatewayRuntimeApiTests(unittest.TestCase):
    def setUp(self):
        self.event_bus = EventBus()
        self.access_token = "runtime-token"

        self.gateway = FastAPIGateway(
            self.event_bus,
            SessionManager(),
            health_getter=lambda: {
                "service": "meetyou-runtime",
                "status": "ready",
                "live": True,
                "ready": True,
                "degraded": False,
                "components": [
                    {
                        "name": "session_execution",
                        "status": "ready",
                        "detail": "ok",
                        "last_event": "gateway.ready",
                        "updated_at": "2026-04-01T00:00:00Z",
                    }
                ],
                "errors": [],
                "updated_at": "2026-04-01T00:00:00Z",
            },
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
                    "current_mode": "general",
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
            runtime_debug_getter=lambda session_id: {
                "session_id": session_id,
                "route": {
                    "requested_mode": "general",
                    "current_mode": "general",
                    "route_reason": "Brain switched mode: Need citations and source tracking",
                    "source_profile": "tech_global",
                    "tool_bundle": ["research_tool", "research_topic"],
                    "mcp_servers": [],
                    "prompt_bundle": "general+research_grounding",
                    "active_skills": [],
                    "loaded_skills": [],
                    "confidence": "high",
                    "should_preload_context": True,
                    "prefer_live_web": True,
                    "signals": ["deep_research"],
                    "adapter_name": "semantic_router",
                    "used_keyword_fallback": False,
                    "authorization_policy": {"read_only": True},
                    "disable_tools": False,
                },
                "route_history": [{"round": 0, "mode": "general"}, {"round": 1, "mode": "general"}],
                "context_plan": {
                    "length_policy": {"target_input_tokens": 4096},
                    "layers": {"conversation_summary": True, "memory_recall": True},
                    "breakdown": {"total": 2048},
                },
                "memory_scope": {"session_id": session_id, "prefetched": True, "found": True, "profile_count": 1},
                "authorization": {
                    "route_preview": {
                        "visible_tools": ["research_tool", "research_topic"],
                        "candidate_tools": ["research_tool", "research_topic"],
                        "authorization_preview": [{"tool_name": "research_tool", "allowed": True}],
                    },
                    "recent_decisions": [{"tool_name": "research_topic", "ok": True}],
                    "confirmation": {"pending": True, "request_id": "confirm-1"},
                },
                "object_operations": [
                    {
                        "action": "delete",
                        "object_type": "memory",
                        "status": "success",
                        "summary": "已删除记忆。",
                    }
                ],
                "task_state": {
                    "background": {
                        "schedule": {"due_task_count": 1},
                        "execution": {"awaiting_completion_count": 0},
                        "delivery": {"pending_redelivery_count": 0},
                        "system": {},
                    },
                    "sources": ["scheduler.jobs"],
                },
                "runtime_state": {"session_id": session_id, "status": "thinking"},
                "usage": {"session_id": session_id, "usage_ready": True},
                "request": {
                    "provider_name": "openai",
                    "model": "deepseek-reasoner",
                    "api_target": {"host": "api.deepseek.com", "path": "/chat/completions"},
                    "transport_mode": "openai_compatible_chat",
                    "message_count": 12,
                    "tool_count": 2,
                    "request_tokens_estimated": 4096,
                    "context_limit_tokens": 128000,
                    "pressure_ratio": 0.72,
                    "near_limit": False,
                    "length_policy": {
                        "provider_family": "openai",
                        "target_input_tokens": 8192,
                        "reserved_response_tokens": 1024,
                        "reserve_ratio": 0.72,
                    },
                    "budget": {
                        "context_limit_tokens": 128000,
                        "target_input_tokens": 8192,
                        "reserved_response_tokens": 1024,
                        "breakdown_total": 4096,
                    },
                    "layers": {
                        "conversation_summary": True,
                        "memory_recall": True,
                        "session_preload": True,
                        "prefer_live_web": True,
                        "history_message_count": 5,
                    },
                },
                "compression": {
                    "triggered": True,
                    "level": "history_summary",
                    "trimmed_messages": 4,
                    "before_tokens": 9200,
                    "after_tokens": 4100,
                    "usable_tokens": 8192,
                    "summary_tokens": 480,
                },
                "last_failure": {
                    "code": "provider_bad_request",
                    "category": "validation",
                    "message": "HTTP 400",
                    "retryable": False,
                    "details": {"status_code": 400},
                    "occurred_at": "2026-04-01T00:00:04Z",
                },
                "updated_at": "2026-04-01T00:00:04Z",
            },
            access_token=self.access_token,
        )
        self.client = TestClient(self.gateway.app)
        self.addCleanup(self.client.close)

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    def test_health_returns_structured_runtime_health(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema"], "meetyou.http.v1")
        self.assertEqual(payload["kind"], "health")
        self.assertEqual(payload["health"]["service"], "meetyou-runtime")
        self.assertEqual(payload["health"]["status"], "ready")
        self.assertTrue(payload["health"]["ready"])
        self.assertEqual(payload["health"]["components"][0]["name"], "session_execution")

    def test_runtime_source_kind_uses_endpoint_provider_not_web_fallback(self):
        self.assertEqual(
            _resolve_runtime_source_kind(
                endpoint_id="feishu.feishu-oc_x.ui",
                endpoint_type="feishu",
                metadata={"source": "feishu", "transport": "feishu"},
            ),
            "feishu",
        )
        self.assertEqual(
            _resolve_runtime_source_kind(
                endpoint_id="wechat.meetwechat-abc.ui",
                endpoint_type="wechat_ui",
                metadata={"source": "wechat"},
            ),
            "wechat",
        )
        self.assertEqual(
            _resolve_runtime_source_kind(
                endpoint_id="desktop.main.ui",
                endpoint_type="desktop_ui",
                metadata={},
            ),
            "web",
        )

    def test_runtime_reply_control_queues_v4_control_event(self):
        domain = SimpleNamespace(
            services=SimpleNamespace(
                session=SimpleNamespace(
                    get_by_session_id=lambda session_id: SimpleNamespace(id="session-row", session_id=session_id)
                    if session_id == "sess-1"
                    else None
                ),
                endpoint=SimpleNamespace(
                    get_by_endpoint_id=lambda endpoint_id: SimpleNamespace(
                        id="endpoint-row",
                        endpoint_id=endpoint_id,
                        provider_type="desktop",
                    )
                    if endpoint_id == "desktop-app"
                    else None
                ),
            )
        )
        event_bus = EventBus()
        gateway = FastAPIGateway(
            event_bus,
            SessionManager(),
            core_domain=domain,
            access_token=self.access_token,
        )
        client = TestClient(gateway.app)
        self.addCleanup(client.close)

        response = client.post(
            "/runtime/sessions/sess-1/reply-control",
            json={
                "action": "regenerate",
                "endpoint_id": "desktop-app",
                "endpoint_type": "electron",
                "endpoint_request_id": "ctrl-1",
                "turn_id": "turn-1",
                "metadata": {"from": "ui-control"},
            },
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["action"], "regenerate")
        self.assertEqual(payload["request_id"], "ctrl-1")
        event = event_bus.inbound_queue.get_nowait()
        self.assertEqual(event.event_id, "ctrl-1")
        self.assertEqual(event.session_id, "sess-1")
        self.assertEqual(event.type, "control")
        self.assertEqual(event.content["action"], "regenerate")
        self.assertEqual(event.content["turn_id"], "turn-1")
        self.assertEqual(event.metadata["control_kind"], "reply_control")
        self.assertEqual(event.metadata["from"], "ui-control")

    def test_runtime_messages_are_idempotent_by_endpoint_message_id(self):
        class _MessageService:
            def __init__(self):
                self.rows = []

            def get_by_endpoint_message_id(self, *, thread_id, endpoint_message_id, origin_endpoint_id=None, role="user"):
                for row in self.rows:
                    if row.thread_id != thread_id or row.role != role:
                        continue
                    if origin_endpoint_id is not None and row.origin_endpoint_id != origin_endpoint_id:
                        continue
                    if row.meta.get("endpoint_message_id") == endpoint_message_id:
                        return row
                return None

            def create_message(self, **kwargs):
                row = SimpleNamespace(
                    id=f"row-{len(self.rows) + 1}",
                    message_id=f"msg-{len(self.rows) + 1}",
                    channel=kwargs.get("channel", "message"),
                    status=kwargs.get("status", "completed"),
                    created_at=None,
                    **kwargs,
                )
                self.rows.append(row)
                return row

        message_service = _MessageService()
        domain = SimpleNamespace(
            services=SimpleNamespace(
                workspace=SimpleNamespace(
                    get_by_workspace_id=lambda workspace_id: SimpleNamespace(
                        id="workspace-row",
                        workspace_id=workspace_id,
                        title="Personal",
                        status="active",
                        base_mode="general",
                        prompt_overlay="",
                        default_execution_target="core.local",
                        meta={},
                    )
                ),
                thread=SimpleNamespace(
                    get_by_thread_id=lambda thread_id: SimpleNamespace(
                        id="thread-row",
                        thread_id=thread_id,
                        title="Thread",
                        status="active",
                        summary="",
                    )
                ),
                session=SimpleNamespace(
                    get_by_session_id=lambda session_id: SimpleNamespace(id="session-row", session_id=session_id)
                ),
                endpoint=SimpleNamespace(
                    get_by_endpoint_id=lambda endpoint_id: SimpleNamespace(id="endpoint-row", endpoint_id=endpoint_id)
                ),
                message=message_service,
            )
        )
        event_bus = EventBus()
        gateway = FastAPIGateway(
            event_bus,
            SessionManager(),
            core_domain=domain,
            access_token=self.access_token,
        )
        client = TestClient(gateway.app)
        self.addCleanup(client.close)
        payload = {
            "thread_id": "thr-1",
            "workspace_id": "personal",
            "session_id": "sess-1",
            "endpoint_id": "wechat.provider.ui",
            "endpoint_type": "wechat",
            "content": "hello",
            "metadata": {"source": "wechat"},
            "preferred_mode": "danxi",
            "endpoint_message_id": "meetwechat:dedup:stable",
        }

        first = client.post("/runtime/messages", json=payload, headers=self._auth_headers())
        second = client.post("/runtime/messages", json=payload, headers=self._auth_headers())

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(first.json()["idempotent_replay"])
        self.assertTrue(second.json()["idempotent_replay"])
        self.assertEqual(second.json()["message_id"], first.json()["message_id"])
        self.assertEqual(len(message_service.rows), 1)
        self.assertEqual(message_service.rows[0].meta["preferred_mode"], "danxi")
        self.assertEqual(event_bus.inbound_queue.qsize(), 1)
        event = event_bus.inbound_queue.get_nowait()
        self.assertEqual(event.metadata["preferred_mode"], "danxi")
        self.assertEqual(event.source.metadata["preferred_mode"], "danxi")

    def test_runtime_user_message_records_context_pool_item(self):
        class _MessageService:
            def __init__(self):
                self.rows = []

            def get_by_endpoint_message_id(self, *, thread_id, endpoint_message_id, origin_endpoint_id=None, role="user"):
                return None

            def create_message(self, **kwargs):
                row = SimpleNamespace(
                    id=f"row-{len(self.rows) + 1}",
                    message_id=f"msg-{len(self.rows) + 1}",
                    channel=kwargs.get("channel", "message"),
                    status=kwargs.get("status", "completed"),
                    created_at=None,
                    **kwargs,
                )
                self.rows.append(row)
                return row

        class _ContextPoolService:
            def __init__(self):
                self.calls = []

            def record_message(self, **kwargs):
                self.calls.append(dict(kwargs))
                return SimpleNamespace(context_id="ctx-1")

        workspace = SimpleNamespace(
            id="workspace-row",
            workspace_id="personal",
            title="Personal",
            status="active",
            base_mode="general",
            prompt_overlay="",
            default_execution_target="core.local",
            meta={},
        )
        thread = SimpleNamespace(
            id="thread-row",
            thread_id="thr-1",
            title="Thread",
            status="active",
            summary="",
            home_workspace_id=workspace.id,
            workspace_id=workspace.id,
            principal_id="principal-row",
        )
        session = SimpleNamespace(id="session-row", session_id="sess-1")
        endpoint = SimpleNamespace(id="endpoint-row", endpoint_id="desktop-app", provider_type="desktop")
        message_service = _MessageService()
        context_pool = _ContextPoolService()
        domain = SimpleNamespace(
            principal=SimpleNamespace(id="principal-row"),
            services=SimpleNamespace(
                workspace=SimpleNamespace(
                    get_by_workspace_id=lambda workspace_id: workspace if workspace_id == "personal" else None,
                    get_by_id=lambda row_id: workspace if row_id == workspace.id else None,
                ),
                thread=SimpleNamespace(get_by_thread_id=lambda thread_id: thread if thread_id == "thr-1" else None),
                session=SimpleNamespace(get_by_session_id=lambda session_id: session if session_id == "sess-1" else None),
                endpoint=SimpleNamespace(get_by_endpoint_id=lambda endpoint_id: endpoint if endpoint_id == "desktop-app" else None),
                message=message_service,
                context_pool=context_pool,
            )
        )
        event_bus = EventBus()
        gateway = FastAPIGateway(
            event_bus,
            SessionManager(),
            core_domain=domain,
            access_token=self.access_token,
        )
        client = TestClient(gateway.app)
        self.addCleanup(client.close)

        response = client.post(
            "/runtime/messages",
            json={
                "thread_id": "thr-1",
                "workspace_id": "personal",
                "session_id": "sess-1",
                "endpoint_id": "desktop-app",
                "endpoint_type": "electron",
                "content": "remember this thread context",
                "endpoint_message_id": "endpoint-msg-1",
            },
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(context_pool.calls), 1)
        call = context_pool.calls[0]
        self.assertEqual(call["principal_id"], "principal-row")
        self.assertEqual(call["message"].content, "remember this thread context")
        self.assertEqual(call["message"].role, "user")
        self.assertEqual(call["thread"].thread_id, "thr-1")
        self.assertEqual(call["session"].session_id, "sess-1")

    def test_runtime_message_to_deleted_thread_returns_thread_not_found(self):
        domain = SimpleNamespace(
            services=SimpleNamespace(
                thread=SimpleNamespace(get_by_thread_id=lambda thread_id: None),
            )
        )
        gateway = FastAPIGateway(
            EventBus(),
            SessionManager(),
            core_domain=domain,
            access_token=self.access_token,
        )
        client = TestClient(gateway.app)
        self.addCleanup(client.close)

        response = client.post(
            "/runtime/messages",
            json={
                "thread_id": "thr-deleted",
                "workspace_id": "personal",
                "session_id": "sess-old",
                "endpoint_id": "wechat.provider.ui",
                "endpoint_type": "wechat",
                "content": "hello",
                "endpoint_message_id": "evt-after-delete",
            },
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "thread_not_found")

    def test_endpoint_session_resolve_binds_external_conversation_to_thread(self):
        workspace = SimpleNamespace(
            id="workspace-row",
            workspace_id="personal",
            title="Personal",
            status="active",
            base_mode="general",
            prompt_overlay="",
            default_execution_target="core.local",
            meta={},
        )
        endpoint = SimpleNamespace(
            id="endpoint-row",
            endpoint_id="wechat.meetwechat.ui",
            endpoint_type="wechat_ui",
            provider_type="wechat",
        )
        address = SimpleNamespace(id="address-row", address_id="addr.wechat.group.example")
        thread = SimpleNamespace(
            id="thread-row",
            thread_id="thr-chat",
            title="Example Group",
            status="active",
            summary="",
            home_workspace_id="workspace-row",
        )
        binding = SimpleNamespace(
            binding_id="etb-chat",
            endpoint_id="endpoint-row",
            thread_id="thread-row",
            workspace_id="workspace-row",
            address_id="address-row",
            thread_strategy="per_conversation",
            conversation_key="conversation:wechat:meetwechat:group:example",
            display_name="Example Group",
            status="active",
            meta={},
        )
        resolved_calls = []

        class _EndpointThreadBindingService:
            def resolve_thread(self, **kwargs):
                resolved_calls.append(dict(kwargs))
                return binding, thread

        domain = SimpleNamespace(
            principal=SimpleNamespace(id="principal-row"),
            services=SimpleNamespace(
                workspace=SimpleNamespace(get_by_workspace_id=lambda workspace_id: workspace),
                endpoint=SimpleNamespace(get_by_endpoint_id=lambda endpoint_id: endpoint),
                endpoint_address=SimpleNamespace(get_by_address_id=lambda address_id: address),
                endpoint_thread_binding=_EndpointThreadBindingService(),
                session=SimpleNamespace(
                    create_session=lambda **kwargs: SimpleNamespace(id="session-row", session_id="sess-chat", status="active")
                ),
            ),
        )
        gateway = FastAPIGateway(
            EventBus(),
            SessionManager(),
            core_domain=domain,
            access_token=self.access_token,
        )
        client = TestClient(gateway.app)
        self.addCleanup(client.close)

        response = client.post(
            "/runtime/endpoint-sessions/resolve",
            json={
                "endpoint_id": "wechat.meetwechat.ui",
                "workspace_id": "personal",
                "display_name": "Example Group",
                "conversation_key": "wechat:meetwechat:group:example",
                "address_id": "addr.wechat.group.example",
                "thread_strategy": "per_conversation",
                "title": "Example Group",
            },
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["thread"]["thread_id"], "thr-chat")
        self.assertEqual(payload["session"]["session_id"], "sess-chat")
        self.assertEqual(payload["binding"]["binding_id"], "etb-chat")
        self.assertEqual(resolved_calls[0]["conversation_key"], "wechat:meetwechat:group:example")
        self.assertEqual(resolved_calls[0]["thread_strategy"], "per_conversation")

    def test_get_runtime_state(self):
        response = self.client.get(
            "/runtime/state",
            params={"session_id": "web:session:1"},
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["kind"], "runtime")
        self.assertEqual(payload["runtime"]["resource"], "state")
        self.assertEqual(payload["runtime"]["state"]["global_state"]["status"], "idle")
        self.assertEqual(payload["runtime"]["state"]["heartbeat_state"]["status"], "heartbeat")
        self.assertEqual(payload["runtime"]["state"]["session_state"]["status"], "thinking")
        self.assertEqual(payload["runtime"]["state"]["session_state"]["current_mode"], "general")
        self.assertEqual(payload["runtime"]["state"]["session_state"]["source_profile"], "tech_global")
        self.assertEqual(payload["runtime"]["state"]["session_state"]["turn_id"], "turn-1")

    def test_get_runtime_usage(self):
        response = self.client.get(
            "/runtime/usage",
            params={"session_id": "web:session:1"},
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["kind"], "runtime")
        self.assertEqual(payload["runtime"]["resource"], "usage")
        self.assertEqual(payload["runtime"]["usage"]["session_id"], "web:session:1")
        self.assertTrue(payload["runtime"]["usage"]["usage_ready"])
        self.assertEqual(payload["runtime"]["usage"]["context_limit_source"], "config_override")
        self.assertEqual(payload["runtime"]["usage"]["context_limit_model"], "deepseek-reasoner")
        self.assertEqual(payload["runtime"]["usage"]["context_breakdown"]["total"], 2048)
        self.assertEqual(payload["runtime"]["usage"]["last_turn_usage"]["reasoning_tokens"], 44)
        self.assertEqual(payload["runtime"]["usage"]["session_totals"]["turn_count"], 2)
        self.assertEqual(payload["runtime"]["usage"]["usage_source"], "provider")

    def test_get_runtime_debug(self):
        response = self.client.get(
            "/runtime/debug",
            params={"session_id": "web:session:1"},
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["kind"], "runtime")
        self.assertEqual(payload["runtime"]["resource"], "debug")
        self.assertEqual(payload["runtime"]["debug"]["route"]["current_mode"], "general")
        self.assertEqual(payload["runtime"]["debug"]["context_plan"]["layers"]["memory_recall"], True)
        self.assertEqual(payload["runtime"]["debug"]["authorization"]["route_preview"]["visible_tools"][0], "research_tool")
        self.assertEqual(payload["runtime"]["debug"]["task_state"]["background"]["schedule"]["due_task_count"], 1)
        self.assertEqual(payload["runtime"]["debug"]["request"]["transport_mode"], "openai_compatible_chat")
        self.assertEqual(payload["runtime"]["debug"]["compression"]["level"], "history_summary")
        self.assertEqual(payload["runtime"]["debug"]["last_failure"]["code"], "provider_bad_request")
        self.assertTrue(payload["runtime"]["debug"]["authorization"]["confirmation"]["pending"])
        self.assertEqual(payload["runtime"]["debug"]["object_operations"][0]["summary"], "已删除记忆。")

    def test_runtime_debug_routes_serialize_non_json_payloads(self):
        gateway = FastAPIGateway(
            self.event_bus,
            SessionManager(),
            health_getter=lambda: {
                "service": "meetyou-runtime",
                "status": "ready",
                "live": True,
                "ready": True,
                "degraded": False,
                "components": [],
                "errors": [],
                "updated_at": "2026-04-01T00:00:00Z",
            },
            runtime_debug_getter=lambda session_id: {
                "session_id": session_id,
                "route": {"current_mode": "automation"},
                "authorization": {
                    "route_preview": {
                        "visible_tools": ["read_local_documents"],
                        "candidate_tools": ["read_local_documents"],
                        "authorization_preview": [],
                        "mcp_server_diagnostics": [SimpleNamespace(kind="opaque-diagnostic")],
                    },
                    "recent_decisions": [],
                    "confirmation": {"pending": False, "request_id": ""},
                },
                "core_mcp": {
                    "runtime_server_diagnostics": [SimpleNamespace(kind="opaque-core-runtime")],
                },
                "updated_at": "2026-04-01T00:00:00Z",
            },
            access_token=self.access_token,
        )
        client = TestClient(gateway.app)
        self.addCleanup(client.close)

        for path in ("/runtime/debug", "/developer/runtime/debug"):
            response = client.get(
                path,
                params={"session_id": "web:session:json-safe"},
                headers=self._auth_headers(),
            )

            self.assertEqual(response.status_code, 200, msg=path)
            payload = response.json()
            self.assertEqual(
                payload["runtime"]["debug"]["authorization"]["route_preview"]["mcp_server_diagnostics"][0],
                "namespace(kind='opaque-diagnostic')",
            )
            self.assertEqual(
                payload["runtime"]["debug"]["core_mcp"]["runtime_server_diagnostics"][0],
                "namespace(kind='opaque-core-runtime')",
            )

    def test_developer_runtime_debug_maps_getter_errors_to_not_found(self):
        gateway = FastAPIGateway(
            self.event_bus,
            SessionManager(),
            health_getter=lambda: {
                "service": "meetyou-runtime",
                "status": "ready",
                "live": True,
                "ready": True,
                "degraded": False,
                "components": [],
                "errors": [],
                "updated_at": "2026-04-01T00:00:00Z",
            },
            runtime_debug_getter=lambda session_id: (_ for _ in ()).throw(ValueError(f"Session not found: {session_id}")),
            access_token=self.access_token,
        )
        client = TestClient(gateway.app)
        self.addCleanup(client.close)

        response = client.get(
            "/developer/runtime/debug",
            params={"session_id": "missing-session"},
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "runtime_debug_not_found")
        self.assertEqual(payload["error"]["details"]["session_id"], "missing-session")

    def test_legacy_routes_are_not_registered(self):
        paths = {str(getattr(route, "path", "")) for route in self.gateway.app.routes}
        self.assertIn("/endpoint/ws", paths)
        self.assertNotIn("/ws", paths)
        self.assertNotIn("/client/ws", paths)
        self.assertNotIn("/client/{legacy_path:path}", paths)
        self.assertNotIn("/operator/clients", paths)
        self.assertNotIn("/runtime/workspaces/{workspace_id}/clients", paths)


if __name__ == "__main__":
    unittest.main()
