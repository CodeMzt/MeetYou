from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from psycopg import connect

from core.db.bootstrap import bootstrap_core_domain
from core.credential_transport import encrypt_json_payload
from core.app_lifecycle import sync_memory_state_to_db
from core.event_bus import EventBus
from core.io_protocol import EventTarget, HumanInputRequestEvent, TargetKind, make_source
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway
from gateway.routes import client as client_routes


TEST_DATABASE_NAME = "meetyou_gateway_surface_test"
ADMIN_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
TEST_DATABASE_URL = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{TEST_DATABASE_NAME}"


class GatewaySurfaceRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._drop_database(TEST_DATABASE_NAME)
        cls._create_database(TEST_DATABASE_NAME)

    @classmethod
    def tearDownClass(cls):
        cls._drop_database(TEST_DATABASE_NAME)

    @staticmethod
    def _admin_connect():
        return connect(ADMIN_DATABASE_URL, autocommit=True)

    @classmethod
    def _drop_database(cls, db_name: str) -> None:
        with cls._admin_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                    (db_name,),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')

    @classmethod
    def _create_database(cls, db_name: str) -> None:
        with cls._admin_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE DATABASE "{db_name}"')

    def setUp(self):
        self.access_token = "surface-token"
        self.core_domain = bootstrap_core_domain(database_url=TEST_DATABASE_URL, run_migrations=True)
        self.event_bus = EventBus()
        self.gateway = FastAPIGateway(
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
                "updated_at": "2026-04-08T00:00:00Z",
            },
            runtime_debug_getter=lambda session_id: {"session_id": session_id, "route": {"current_mode": "general"}},
            core_domain=self.core_domain,
            access_token=self.access_token,
        )
        self.client = TestClient(self.gateway.app)

    def tearDown(self):
        self.client.close()
        self.core_domain.engine.dispose()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    def test_client_workspaces_and_thread_session_flow(self):
        response = self.client.get("/client/workspaces", headers=self._auth_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue({"personal", "desktop-main", "study", "home-lab"}.issubset({item["workspace_id"] for item in payload}))
        desktop_workspace = {item["workspace_id"]: item for item in payload}["desktop-main"]
        self.assertEqual(desktop_workspace["base_mode"], "automation")
        self.assertEqual(desktop_workspace["default_execution_target"], "specific_agent")
        self.assertTrue(desktop_workspace["prompt_overlay"])
        self.assertEqual(desktop_workspace["capability_policy"], "allow_all")
        self.assertEqual(desktop_workspace["allowed_capability_ids"], [])
        self.assertEqual(desktop_workspace["preferred_agent_types"], ["desktop"])
        self.assertEqual(desktop_workspace["preferred_source_profiles"], ["workspace_local"])
        self.assertEqual(desktop_workspace["agent_routing_policy"], "balanced")
        self.assertEqual(desktop_workspace["memory_ranking_policy"], "workspace_first")
        self.assertEqual(desktop_workspace["capability_routing_overrides"], {})

        procedures_resp = self.client.get("/client/procedures", headers=self._auth_headers())
        self.assertEqual(procedures_resp.status_code, 200)
        procedures = {item["procedure_id"]: item for item in procedures_resp.json()}
        self.assertIn("code_review", procedures)
        self.assertEqual(procedures["code_review"]["default_execution_target"], "core_only")
        self.assertIn("general", procedures["code_review"]["applicable_modes"])
        self.assertEqual(procedures["code_review"]["preferred_capability_ref"], "search_memory")
        self.assertEqual(procedures["desktop_fix_loop"]["preferred_agent_types"], ["desktop"])
        self.assertEqual(procedures["desktop_fix_loop"]["agent_routing_policy"], "balanced")

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Route test", "pinned_procedure_id": "code_review"},
            headers=self._auth_headers(),
        )
        self.assertEqual(thread_resp.status_code, 200)
        thread_payload = thread_resp.json()
        self.assertEqual(thread_payload["workspace_id"], "personal")
        self.assertEqual(thread_payload["pinned_procedure_id"], "code_review")

        procedure_detail_resp = self.client.get("/client/procedures/code_review", headers=self._auth_headers())
        self.assertEqual(procedure_detail_resp.status_code, 200)
        procedure_detail = procedure_detail_resp.json()
        self.assertEqual(procedure_detail["procedure_id"], "code_review")
        self.assertTrue(procedure_detail["prompt_overlay"])
        self.assertIn("infer_keywords", procedure_detail)

        inferred_thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Inferred procedure thread"},
            headers=self._auth_headers(),
        )
        self.assertEqual(inferred_thread_resp.status_code, 200)
        inferred_thread = self.core_domain.services.thread.get_by_thread_id(inferred_thread_resp.json()["thread_id"])
        self.core_domain.services.thread.set_latest_inferred_procedure(
            thread_id=inferred_thread.id,
            procedure_id="code_review",
            score=7,
            reason="keywords:review,patch",
            inferred_at="2026-04-12T00:00:00Z",
        )
        context_resp = self.client.get(
            f"/client/threads/{inferred_thread.thread_id}/procedure-context",
            headers=self._auth_headers(),
        )
        self.assertEqual(context_resp.status_code, 200)
        context_payload = context_resp.json()
        self.assertEqual(context_payload["source"], "inferred")
        self.assertEqual(context_payload["effective_procedure"]["procedure_id"], "code_review")
        self.assertEqual(context_payload["latest_inferred_score"], 7)

        pin_resp = self.client.put(
            f"/client/threads/{inferred_thread.thread_id}/pinned-procedure",
            json={"procedure_id": "desktop_fix_loop"},
            headers=self._auth_headers(),
        )
        self.assertEqual(pin_resp.status_code, 200)
        pin_payload = pin_resp.json()
        self.assertEqual(pin_payload["source"], "pinned")
        self.assertEqual(pin_payload["pinned_procedure"]["procedure_id"], "desktop_fix_loop")
        self.assertEqual(pin_payload["effective_procedure"]["procedure_id"], "desktop_fix_loop")

        unpin_resp = self.client.delete(
            f"/client/threads/{inferred_thread.thread_id}/pinned-procedure",
            headers=self._auth_headers(),
        )
        self.assertEqual(unpin_resp.status_code, 200)
        unpin_payload = unpin_resp.json()
        self.assertEqual(unpin_payload["source"], "inferred")
        self.assertIsNone(unpin_payload["pinned_procedure"])
        self.assertEqual(unpin_payload["effective_procedure"]["procedure_id"], "code_review")

        session_resp = self.client.post(
            "/client/sessions",
            json={
                "thread_id": thread_payload["thread_id"],
                "workspace_id": "personal",
                "client_id": "electron-main",
                "client_type": "electron",
                "display_name": "Electron Main",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(session_resp.status_code, 200)
        self.assertEqual(session_resp.json()["thread_id"], thread_payload["thread_id"])

    def test_create_session_binds_runtime_session_without_replaying_connected_agent(self):
        workspace = self.core_domain.services.workspace.get_by_workspace_id("personal")
        self.assertIsNotNone(workspace)
        registered = self.core_domain.services.agent.register_agent(
            principal_id=self.core_domain.principal.id,
            agent_id="desktop-main-agent",
            agent_type="desktop",
            display_name="Desktop Main Agent",
            transport_profile="local",
            workspace_rows=[workspace],
        )
        agent = self.core_domain.services.agent.record_heartbeat(
            agent_id=registered.agent_id,
            status="ready",
            metrics={"source": "test"},
        )
        calls: list[dict] = []

        async def _connected(_agent_id: str) -> bool:
            return True

        async def _capture_handler(**kwargs):
            calls.append(dict(kwargs))

        self.gateway.agent_ws_manager.is_connected = _connected  # type: ignore[method-assign]
        self.gateway._agent_connection_event_handler = _capture_handler  # noqa: SLF001

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Session bootstrap replay"},
            headers=self._auth_headers(),
        )
        self.assertEqual(thread_resp.status_code, 200)
        thread_id = thread_resp.json()["thread_id"]

        session_resp = self.client.post(
            "/client/sessions",
            json={
                "thread_id": thread_id,
                "workspace_id": "personal",
                "client_id": "electron-main",
                "client_type": "electron",
                "display_name": "Electron Main",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(session_resp.status_code, 200)
        session_id = session_resp.json()["session_id"]

        binding = self.gateway._session_manager.get_binding(session_id)  # noqa: SLF001
        self.assertIsNotNone(binding)
        self.assertEqual(getattr(binding, "session_id", ""), session_id)
        self.assertEqual((binding.metadata or {}).get("thread_id"), thread_id)
        self.assertEqual((binding.metadata or {}).get("workspace_id"), "personal")
        self.assertEqual((binding.metadata or {}).get("client_id"), "electron-main")
        self.assertEqual(len(calls), 0)

    def test_workspace_agents_include_ready_agent(self):
        workspace = self.core_domain.services.workspace.get_by_workspace_id("desktop-main")
        self.assertIsNotNone(workspace)
        registered = self.core_domain.services.agent.register_agent(
            principal_id=self.core_domain.principal.id,
            agent_id="desktop-main-agent",
            agent_type="desktop",
            display_name="Desktop Main Agent",
            transport_profile="desktop_wss",
            workspace_rows=[workspace],
        )
        self.core_domain.services.agent.record_heartbeat(
            agent_id=registered.agent_id,
            status="ready",
            metrics={"source": "test"},
        )

        response = self.client.get("/client/workspaces/desktop-main/agents", headers=self._auth_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        agent_rows = {item["agent_id"]: item for item in payload}
        self.assertIn("desktop-main-agent", agent_rows)
        self.assertEqual(agent_rows["desktop-main-agent"]["status"], "ready")

    def test_client_attachment_flow(self):
        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Attachment thread"},
            headers=self._auth_headers(),
        )
        self.assertEqual(thread_resp.status_code, 200)
        thread_id = thread_resp.json()["thread_id"]

        ticket_resp = self.client.post(
            "/client/attachments/upload-ticket",
            json={
                "owner_type": "thread",
                "owner_id": thread_id,
                "kind": "file",
                "mime_type": "text/plain",
                "file_name": "notes.txt",
                "client_id": "electron-main",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(ticket_resp.status_code, 200)
        ticket_payload = ticket_resp.json()
        self.assertTrue(ticket_payload["attachment_id"])
        self.assertTrue(ticket_payload["ticket_id"])

        upload_resp = self.client.put(
            f"/client/attachments/upload/{ticket_payload['ticket_id']}",
            content=b"hello attachment",
            headers=self._auth_headers(),
        )
        self.assertEqual(upload_resp.status_code, 200)
        upload_payload = upload_resp.json()
        self.assertEqual(upload_payload["attachment_id"], ticket_payload["attachment_id"])
        self.assertEqual(upload_payload["status"], "uploaded")
        self.assertTrue(upload_payload["created_at"])
        self.assertTrue(upload_payload["updated_at"])
        self.assertTrue(upload_payload["uploaded_at"])

        complete_resp = self.client.post(
            f"/client/attachments/{ticket_payload['attachment_id']}/complete",
            json={"ticket_id": ticket_payload["ticket_id"], "sha256": upload_payload["sha256"], "size_bytes": upload_payload["size_bytes"]},
            headers=self._auth_headers(),
        )
        self.assertEqual(complete_resp.status_code, 200)
        complete_payload = complete_resp.json()
        self.assertEqual(complete_payload["status"], "ready")
        self.assertTrue(complete_payload["created_at"])
        self.assertTrue(complete_payload["updated_at"])
        self.assertEqual(complete_payload["uploaded_at"], upload_payload["uploaded_at"])
        self.assertTrue(complete_payload["completed_at"])

        download_ticket_resp = self.client.get(
            f"/client/attachments/{ticket_payload['attachment_id']}/download-ticket?client_id=electron-main",
            headers=self._auth_headers(),
        )
        self.assertEqual(download_ticket_resp.status_code, 200)
        download_ticket = download_ticket_resp.json()
        self.assertTrue(download_ticket["download_url"])
        self.assertEqual(download_ticket["download_strategy"], "proxy")
        self.assertTrue(download_ticket["fallback_download_url"])
        self.assertEqual(download_ticket["download_url"], download_ticket["fallback_download_url"])

        content_resp = self.client.get(
            f"/client/attachments/content/{ticket_payload['attachment_id']}?ticket_id={download_ticket['ticket_id']}",
            headers=self._auth_headers(),
        )
        self.assertEqual(content_resp.status_code, 200)
        self.assertEqual(content_resp.content, b"hello attachment")

        detail_resp = self.client.get(
            f"/client/attachments/{ticket_payload['attachment_id']}",
            headers=self._auth_headers(),
        )
        self.assertEqual(detail_resp.status_code, 200)
        detail_payload = detail_resp.json()
        self.assertEqual(detail_payload["attachment_id"], ticket_payload["attachment_id"])
        self.assertEqual(detail_payload["status"], "ready")
        self.assertTrue(detail_payload["created_at"])
        self.assertTrue(detail_payload["completed_at"])
        list_resp = self.client.get(
            f"/client/attachments?owner_type=thread&owner_id={thread_id}",
            headers=self._auth_headers(),
        )
        self.assertEqual(list_resp.status_code, 200)
        list_payload = list_resp.json()
        self.assertEqual(len(list_payload), 1)
        self.assertEqual(list_payload[0]["attachment_id"], ticket_payload["attachment_id"])

        delete_resp = self.client.delete(
            f"/client/attachments/{ticket_payload['attachment_id']}",
            headers=self._auth_headers(),
        )
        self.assertEqual(delete_resp.status_code, 200)
        delete_payload = delete_resp.json()
        self.assertEqual(delete_payload["status"], "deleted")
        self.assertTrue(delete_payload["deleted_at"])

        list_after_delete_resp = self.client.get(
            f"/client/attachments?owner_type=thread&owner_id={thread_id}",
            headers=self._auth_headers(),
        )
        self.assertEqual(list_after_delete_resp.status_code, 200)
        self.assertEqual(list_after_delete_resp.json(), [])

        list_deleted_resp = self.client.get(
            f"/client/attachments?owner_type=thread&owner_id={thread_id}&include_deleted=true",
            headers=self._auth_headers(),
        )
        self.assertEqual(list_deleted_resp.status_code, 200)
        list_deleted_payload = list_deleted_resp.json()
        self.assertEqual(len(list_deleted_payload), 1)
        self.assertEqual(list_deleted_payload[0]["status"], "deleted")

    def test_client_danxi_routes_use_gateway_facade(self):
        calls: dict[str, dict] = {}
        with patch.object(
            client_routes,
            "_DANXI_TOOLS",
            new=type(
                "_FakeDanxiTools",
                (),
                {
                    "danxi_login": lambda self, **kwargs: (
                        calls.setdefault("login", dict(kwargs)),
                        {
                            "session_key": "default",
                            "email": "user@example.com",
                            "transport": "webvpn",
                            "webvpn_enabled": True,
                            "has_webvpn_cookie": True,
                            "token": {"has_access_token": True, "has_refresh_token": False, "raw_keys": ["access"]},
                            "user_profile": {"user_id": 1},
                        },
                    )[1],
                    "danxi_get_session_status": lambda self, session_key="": {
                        "session_key": session_key or "default",
                        "email": "user@example.com",
                        "transport": "webvpn",
                        "webvpn_enabled": True,
                        "has_webvpn_cookie": True,
                        "webvpn_required": True,
                        "direct_connect_available": False,
                        "logged_in": True,
                        "user_profile": {"user_id": 1},
                    },
                    "danxi_get_user_profile": lambda self, **_: {
                        "session_key": "default",
                        "logged_in": True,
                        "transport": "webvpn",
                        "webvpn_enabled": True,
                        "has_webvpn_cookie": True,
                        "webvpn_required": True,
                        "direct_connect_available": False,
                        "profile": {"user_id": 1, "nickname": "阿明"},
                    },
                    "danxi_set_webvpn_cookie": lambda self, cookie_header, **kwargs: (
                        calls.setdefault("cookie", {"cookie_header": cookie_header, **dict(kwargs)}),
                        {
                            "session_key": "default",
                            "email": "user@example.com",
                            "transport": "webvpn",
                            "webvpn_enabled": True,
                            "has_webvpn_cookie": True,
                            "webvpn_required": True,
                            "direct_connect_available": False,
                            "logged_in": True,
                            "user_profile": {"user_id": 1},
                        },
                    )[1],
                    "danxi_list_divisions": lambda self, **_: {"count": 1, "items": [{"division_id": 2, "name": "综合"}]},
                    "danxi_list_posts": lambda self, **_: {"scope": "homepage", "count": 1, "items": [{"hole_id": 10, "content": "hello"}]},
                    "danxi_get_post": lambda self, hole_id, **_: {"hole": {"hole_id": hole_id, "content": "hello"}},
                    "danxi_list_floors": lambda self, hole_id, **_: {"count": 1, "items": [{"hole_id": hole_id, "floor_id": 1, "content": "reply"}]},
                    "danxi_reply_post": lambda self, hole_id, content, **_: {"ok": True, "status_code": 201, "hole_id": hole_id, "floor_id": 77},
                    "danxi_edit_reply": lambda self, floor_id, content, **_: {"ok": True, "status_code": 200, "floor_id": floor_id},
                    "danxi_delete_reply": lambda self, floor_id, **_: {"ok": True, "status_code": 200, "floor_id": floor_id},
                    "danxi_summarize_post": lambda self, hole_id, **_: {
                        "hole_id": hole_id,
                        "title": f"帖子 #{hole_id}",
                        "summary": "这里是结构化摘要。",
                        "key_points": ["主贴说明了问题背景。"],
                        "reply_highlights": ["匿名: 提供了解决办法。"],
                        "floor_count": 1,
                        "participant_count": 1,
                        "generated_at": "2026-04-14T00:00:00Z",
                    },
                    "danxi_search_posts": lambda self, query, **_: {"query": query, "floor_hits": 1, "hole_ids": [10], "hits_by_hole": {10: [{"hole_id": 10}]}, "items": [{"hole_id": 10}]},
                    "danxi_list_messages": lambda self, **_: {"count": 1, "items": [{"message_id": 9, "content": "ping"}]},
                    "_can_connect_directly": lambda self: False,
                },
            )(),
        ):
            with patch.dict(os.environ, {"MEETYOU_CREDENTIAL_SECRET": "gateway-test-secret"}, clear=False):
                login_resp = self.client.post(
                    "/client/danxi/session/login",
                    json={
                        "session_key": "default",
                        "encrypted_credentials": encrypt_json_payload(
                            {
                                "email": "user@example.com",
                                "password": "secret",
                                "session_key": "default",
                                "use_webvpn": True,
                            },
                            purpose="danxi.client.login.v1",
                        ),
                    },
                    headers=self._auth_headers(),
                )
                self.assertEqual(login_resp.status_code, 200)
                self.assertEqual(login_resp.json()["transport"], "webvpn")

                session_resp = self.client.get("/client/danxi/session", headers=self._auth_headers())
                self.assertEqual(session_resp.status_code, 200)
                self.assertTrue(session_resp.json()["has_webvpn_cookie"])

                cookie_resp = self.client.patch(
                    "/client/danxi/session/webvpn-cookie",
                    json={
                        "session_key": "default",
                        "encrypted_credentials": encrypt_json_payload(
                            {
                                "session_key": "default",
                                "cookie_header": "vpn=ok",
                                "enable_webvpn": True,
                            },
                            purpose="danxi.client.webvpn_cookie.v1",
                        ),
                    },
                    headers=self._auth_headers(),
                )
                self.assertEqual(cookie_resp.status_code, 200)

            profile_resp = self.client.get("/client/danxi/profile?refresh=true", headers=self._auth_headers())
            self.assertEqual(profile_resp.status_code, 200)
            self.assertEqual(profile_resp.json()["profile"]["nickname"], "阿明")

            self.assertEqual(self.client.get("/client/danxi/divisions", headers=self._auth_headers()).json()["count"], 1)
            self.assertEqual(self.client.get("/client/danxi/posts", headers=self._auth_headers()).json()["items"][0]["hole_id"], 10)
            self.assertEqual(self.client.get("/client/danxi/posts/10", headers=self._auth_headers()).json()["hole"]["hole_id"], 10)
            self.assertEqual(self.client.get("/client/danxi/posts/10/floors", headers=self._auth_headers()).json()["count"], 1)
            self.assertTrue(
                self.client.post(
                    "/client/danxi/posts/10/replies",
                    json={"content": "hello reply"},
                    headers=self._auth_headers(),
                ).json()["ok"]
            )
            self.assertEqual(
                self.client.patch(
                    "/client/danxi/floors/77",
                    json={"content": "edited reply"},
                    headers=self._auth_headers(),
                ).json()["floor_id"],
                77,
            )
            self.assertEqual(
                self.client.delete("/client/danxi/floors/77?confirm=true", headers=self._auth_headers()).json()["floor_id"],
                77,
            )
            self.assertEqual(
                self.client.get("/client/danxi/posts/10/summary", headers=self._auth_headers()).json()["hole_id"],
                10,
            )
            self.assertEqual(self.client.get("/client/danxi/search?query=test", headers=self._auth_headers()).json()["query"], "test")
            self.assertEqual(self.client.get("/client/danxi/messages", headers=self._auth_headers()).json()["count"], 1)
        self.assertEqual(calls["login"]["email"], "user@example.com")
        self.assertEqual(calls["login"]["password"], "secret")
        self.assertTrue(calls["login"]["use_webvpn"])
        self.assertEqual(calls["cookie"]["cookie_header"], "vpn=ok")

    def test_client_danxi_login_rejects_when_credential_secret_is_missing(self):
        with patch.dict(
            os.environ,
            {
                "MEETYOU_CREDENTIAL_SECRET": "",
                "MEETYOU_GATEWAY_ACCESS_TOKEN": "",
                "MEETYOU_AGENT_ACCESS_TOKEN": "",
            },
            clear=False,
        ):
            response = self.client.post(
                "/client/danxi/session/login",
                json={
                    "session_key": "default",
                    "encrypted_credentials": {
                        "version": "v1",
                        "alg": "aes-256-gcm",
                        "purpose": "danxi.client.login.v1",
                        "iv": "AA==",
                        "ciphertext": "AA==",
                        "tag": "AA==",
                    },
                },
                headers=self._auth_headers(),
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "danxi_credential_key_unavailable")

    def test_client_danxi_login_rejects_plaintext_credentials(self):
        response = self.client.post(
            "/client/danxi/session/login",
            json={
                "session_key": "default",
                "email": "user@example.com",
                "password": "secret",
                "use_webvpn": True,
                "webvpn_cookie": "vpn=ok",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "danxi_encrypted_credentials_required")

    def test_client_danxi_webvpn_cookie_rejects_plaintext_credentials(self):
        response = self.client.patch(
            "/client/danxi/session/webvpn-cookie",
            json={
                "session_key": "default",
                "cookie_header": "vpn=ok",
                "enable_webvpn": True,
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "danxi_encrypted_credentials_required")

    def test_client_attachment_download_ticket_prefers_presigned_url_when_available(self):
        class _FakePresignedStore:
            def __init__(self):
                self.objects = {}

            def put_bytes(self, object_key: str, content: bytes):
                self.objects[object_key] = bytes(content)
                return type("Stored", (), {"object_key": object_key, "size_bytes": len(content)})()

            def read_bytes(self, object_key: str) -> bytes:
                return self.objects[object_key]

            def delete_object(self, object_key: str) -> None:
                self.objects.pop(object_key, None)

            def generate_presigned_download_url(
                self,
                object_key: str,
                *,
                expires_in_seconds: int,
                file_name: str = "",
                mime_type: str = "",
            ) -> str:
                return (
                    f"https://object-store.example.com/{object_key}"
                    f"?expires={expires_in_seconds}&file_name={file_name}&mime_type={mime_type}"
                )

        self.core_domain.services.attachment._object_store = _FakePresignedStore()
        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Presigned attachment thread"},
            headers=self._auth_headers(),
        )
        self.assertEqual(thread_resp.status_code, 200)
        thread_id = thread_resp.json()["thread_id"]

        ticket_resp = self.client.post(
            "/client/attachments/upload-ticket",
            json={
                "owner_type": "thread",
                "owner_id": thread_id,
                "kind": "file",
                "mime_type": "text/plain",
                "file_name": "presigned.txt",
                "client_id": "electron-main",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(ticket_resp.status_code, 200)
        ticket_payload = ticket_resp.json()

        upload_resp = self.client.put(
            f"/client/attachments/upload/{ticket_payload['ticket_id']}",
            content=b"hello presigned attachment",
            headers=self._auth_headers(),
        )
        self.assertEqual(upload_resp.status_code, 200)

        complete_resp = self.client.post(
            f"/client/attachments/{ticket_payload['attachment_id']}/complete",
            json={"ticket_id": ticket_payload["ticket_id"]},
            headers=self._auth_headers(),
        )
        self.assertEqual(complete_resp.status_code, 200)

        download_ticket_resp = self.client.get(
            f"/client/attachments/{ticket_payload['attachment_id']}/download-ticket?client_id=electron-main",
            headers=self._auth_headers(),
        )
        self.assertEqual(download_ticket_resp.status_code, 200)
        download_ticket = download_ticket_resp.json()
        self.assertEqual(download_ticket["download_strategy"], "presigned")
        self.assertIn("https://object-store.example.com/", download_ticket["download_url"])
        self.assertTrue(download_ticket["fallback_download_url"])

    def test_client_attachment_content_supports_unicode_file_name(self):
        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Unicode attachment thread"},
            headers=self._auth_headers(),
        )
        self.assertEqual(thread_resp.status_code, 200)
        thread_id = thread_resp.json()["thread_id"]

        ticket_resp = self.client.post(
            "/client/attachments/upload-ticket",
            json={
                "owner_type": "thread",
                "owner_id": thread_id,
                "kind": "image",
                "mime_type": "image/png",
                "file_name": "大白LOGO.png",
                "client_id": "electron-main",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(ticket_resp.status_code, 200)
        ticket_payload = ticket_resp.json()

        upload_resp = self.client.put(
            f"/client/attachments/upload/{ticket_payload['ticket_id']}",
            content=b"unicode-name-image",
            headers=self._auth_headers(),
        )
        self.assertEqual(upload_resp.status_code, 200)

        complete_resp = self.client.post(
            f"/client/attachments/{ticket_payload['attachment_id']}/complete",
            json={"ticket_id": ticket_payload["ticket_id"]},
            headers=self._auth_headers(),
        )
        self.assertEqual(complete_resp.status_code, 200)

        download_ticket_resp = self.client.get(
            f"/client/attachments/{ticket_payload['attachment_id']}/download-ticket?client_id=electron-main",
            headers=self._auth_headers(),
        )
        self.assertEqual(download_ticket_resp.status_code, 200)
        download_ticket = download_ticket_resp.json()

        content_resp = self.client.get(
            f"/client/attachments/content/{ticket_payload['attachment_id']}?ticket_id={download_ticket['ticket_id']}",
            headers=self._auth_headers(),
        )
        self.assertEqual(content_resp.status_code, 200)
        self.assertEqual(content_resp.content, b"unicode-name-image")
        disposition = content_resp.headers.get("content-disposition", "")
        self.assertIn("filename=", disposition)
        self.assertIn("filename*=UTF-8''", disposition)

    def test_client_attachment_list_and_delete_flow(self):
        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Attachment manage thread"},
            headers=self._auth_headers(),
        )
        self.assertEqual(thread_resp.status_code, 200)
        thread_id = thread_resp.json()["thread_id"]

        ticket_resp = self.client.post(
            "/client/attachments/upload-ticket",
            json={
                "owner_type": "thread",
                "owner_id": thread_id,
                "kind": "file",
                "mime_type": "text/plain",
                "file_name": "manage.txt",
                "client_id": "electron-main",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(ticket_resp.status_code, 200)
        ticket_payload = ticket_resp.json()

        upload_resp = self.client.put(
            f"/client/attachments/upload/{ticket_payload['ticket_id']}",
            content=b"attachment-for-listing",
            headers=self._auth_headers(),
        )
        self.assertEqual(upload_resp.status_code, 200)

        complete_resp = self.client.post(
            f"/client/attachments/{ticket_payload['attachment_id']}/complete",
            json={"ticket_id": ticket_payload["ticket_id"]},
            headers=self._auth_headers(),
        )
        self.assertEqual(complete_resp.status_code, 200)

        list_resp = self.client.get(
            f"/client/threads/{thread_id}/attachments",
            headers=self._auth_headers(),
        )
        self.assertEqual(list_resp.status_code, 200)
        attachments = list_resp.json()
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["file_name"], "manage.txt")
        self.assertEqual(attachments[0]["status"], "ready")
        self.assertTrue(attachments[0]["created_at"])
        self.assertTrue(attachments[0]["updated_at"])

        delete_resp = self.client.delete(
            f"/client/attachments/{ticket_payload['attachment_id']}",
            headers=self._auth_headers(),
        )
        self.assertEqual(delete_resp.status_code, 200)
        self.assertEqual(delete_resp.json()["status"], "deleted")

        list_after_delete_resp = self.client.get(
            f"/client/threads/{thread_id}/attachments",
            headers=self._auth_headers(),
        )
        self.assertEqual(list_after_delete_resp.status_code, 200)
        self.assertEqual(list_after_delete_resp.json(), [])

    def test_client_attachment_delete_accepts_browser_cors_preflight(self):
        response = self.client.options(
            "/client/attachments/att_delete_cors_probe",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://127.0.0.1:5173")
        allowed_methods = str(response.headers.get("access-control-allow-methods", ""))
        self.assertIn("DELETE", allowed_methods)

    def test_operator_workspace_management_and_client_reads_dynamic_workspace(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "focus-lab",
                "title": "Focus Lab",
                "base_mode": "study",
                "prompt_overlay": "Focus on learning outcomes.",
                "default_execution_target": "core_only",
                "capability_policy": "allowlist",
                "allowed_capability_ids": ["agent.focus-lab-agent.focus.allowed"],
                "preferred_source_profiles": ["study_materials"],
                "memory_ranking_policy": "workspace_first",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)
        self.assertEqual(create_resp.json()["workspace_id"], "focus-lab")
        self.assertEqual(create_resp.json()["default_execution_target"], "core_only")
        self.assertEqual(create_resp.json()["prompt_overlay"], "Focus on learning outcomes.")
        self.assertEqual(create_resp.json()["capability_policy"], "allowlist")
        self.assertEqual(create_resp.json()["allowed_capability_ids"], ["agent.focus-lab-agent.focus.allowed"])
        self.assertEqual(create_resp.json()["preferred_source_profiles"], ["study_materials"])
        self.assertEqual(create_resp.json()["memory_ranking_policy"], "workspace_first")

        list_resp = self.client.get("/operator/workspaces", headers=self._auth_headers())
        self.assertEqual(list_resp.status_code, 200)
        self.assertIn("focus-lab", {item["workspace_id"] for item in list_resp.json()})

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "focus-lab", "title": "Dynamic workspace thread"},
            headers=self._auth_headers(),
        )
        self.assertEqual(thread_resp.status_code, 200)
        thread_id = thread_resp.json()["thread_id"]

        fetched_thread = self.client.get(f"/client/threads/{thread_id}", headers=self._auth_headers())
        self.assertEqual(fetched_thread.status_code, 200)
        self.assertEqual(fetched_thread.json()["workspace_id"], "focus-lab")

        workspaces_resp = self.client.get("/client/workspaces", headers=self._auth_headers())
        self.assertEqual(workspaces_resp.status_code, 200)
        focus_workspace_view = {item["workspace_id"]: item for item in workspaces_resp.json()}["focus-lab"]
        self.assertEqual(focus_workspace_view["base_mode"], "study")
        self.assertEqual(focus_workspace_view["default_execution_target"], "core_only")
        self.assertEqual(focus_workspace_view["capability_policy"], "allowlist")
        self.assertEqual(focus_workspace_view["allowed_capability_ids"], ["agent.focus-lab-agent.focus.allowed"])
        self.assertEqual(focus_workspace_view["preferred_source_profiles"], ["study_materials"])
        self.assertEqual(focus_workspace_view["memory_ranking_policy"], "workspace_first")

        focus_workspace = self.core_domain.services.workspace.get_by_workspace_id("focus-lab")
        agent = self.core_domain.services.agent.register_agent(
            agent_id="focus-lab-agent",
            principal_id=self.core_domain.principal.id,
            agent_type="desktop",
            display_name="Focus Lab Agent",
            transport_profile="desktop_wss",
            workspace_rows=[focus_workspace],
            owner_client_id=self.core_domain.services.client.ensure_client(
                client_id="electron-main",
                principal_id=self.core_domain.principal.id,
                client_type="electron",
                display_name="Electron Main",
            ).id,
        )
        self.core_domain.services.capability.replace_agent_capabilities(
            agent=agent,
            capabilities=[
                {
                    "capability_id": "agent.focus-lab-agent.focus.allowed",
                    "kind": "tool",
                    "title": "Focus Allowed Capability",
                    "risk_level": "read",
                    "requires_confirmation": False,
                    "workspace_ids": ["focus-lab"],
                }
            ],
            workspace_rows=[focus_workspace],
            revision=1,
        )

        targets_resp = self.client.get("/client/workspaces/focus-lab/agents", headers=self._auth_headers())
        self.assertEqual(targets_resp.status_code, 200)
        self.assertEqual(targets_resp.json()[0]["agent_id"], "focus-lab-agent")
        self.assertEqual(targets_resp.json()[0]["owner_client_id"], "electron-main")

        operation_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "focus-lab",
                "client_id": "electron-main",
                "title": "Focus operation",
                "operation_type": "capability_call",
                "execution_target": "specific_agent",
                "target_agent_id": "focus-lab-agent",
                "capability_id": "agent.focus-lab-agent.focus.allowed",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(operation_resp.status_code, 200)

        fetched_operation = self.client.get(
            f"/client/operations/{operation_resp.json()['operation_id']}",
            headers=self._auth_headers(),
        )
        self.assertEqual(fetched_operation.status_code, 200)
        self.assertEqual(fetched_operation.json()["workspace_id"], "focus-lab")

        missing_target_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "focus-lab",
                "client_id": "electron-main",
                "title": "Missing target",
                "operation_type": "capability_call",
                "execution_target": "specific_agent",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(missing_target_resp.status_code, 400)
        self.assertEqual(missing_target_resp.json()["error"]["code"], "target_agent_required")

    def test_operator_workspace_patch_updates_source_profile_policy(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "policy-lab",
                "title": "Policy Lab",
                "preferred_source_profiles": ["workspace_local"],
                "memory_ranking_policy": "workspace_first",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)

        patch_resp = self.client.patch(
            "/operator/workspaces/policy-lab",
            json={
                "base_mode": "danxi",
                "preferred_source_profiles": ["policy_global", "workspace_local"],
                "memory_ranking_policy": "workspace_first",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(patch_resp.status_code, 200)
        self.assertEqual(
            patch_resp.json()["preferred_source_profiles"],
            ["policy_global", "workspace_local"],
        )
        self.assertEqual(patch_resp.json()["base_mode"], "danxi")
        self.assertEqual(patch_resp.json()["memory_ranking_policy"], "workspace_first")

        workspaces_resp = self.client.get("/client/workspaces", headers=self._auth_headers())
        self.assertEqual(workspaces_resp.status_code, 200)
        policy_workspace = {item["workspace_id"]: item for item in workspaces_resp.json()}["policy-lab"]
        self.assertEqual(policy_workspace["base_mode"], "danxi")
        self.assertEqual(policy_workspace["preferred_source_profiles"], ["policy_global", "workspace_local"])
        self.assertEqual(policy_workspace["memory_ranking_policy"], "workspace_first")

    def test_operator_source_profiles_lists_known_catalog_profiles(self):
        resp = self.client.get("/operator/source-profiles", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        profiles = {item["profile_name"]: item for item in resp.json()}
        self.assertIn("campus_forum", profiles)
        self.assertIn("workspace_local", profiles)
        self.assertIn("study_materials", profiles)
        self.assertTrue(profiles["tech_updates"]["official_only"])

    def test_operator_workspace_patch_rejects_unknown_source_profile(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "invalid-policy-lab",
                "title": "Invalid Policy Lab",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)

        patch_resp = self.client.patch(
            "/operator/workspaces/invalid-policy-lab",
            json={"preferred_source_profiles": ["unknown_profile"]},
            headers=self._auth_headers(),
        )
        self.assertEqual(patch_resp.status_code, 400)
        self.assertEqual(patch_resp.json()["error"]["code"], "invalid_source_profile")

    def test_operator_workspace_patch_rejects_unknown_memory_ranking_policy(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "invalid-memory-lab",
                "title": "Invalid Memory Lab",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)

        patch_resp = self.client.patch(
            "/operator/workspaces/invalid-memory-lab",
            json={"memory_ranking_policy": "global_only"},
            headers=self._auth_headers(),
        )
        self.assertEqual(patch_resp.status_code, 400)
        self.assertEqual(patch_resp.json()["error"]["code"], "invalid_memory_ranking_policy")

    def test_workspace_allowlist_blocks_disallowed_capability_operation(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "restricted-lab",
                "title": "Restricted Lab",
                "base_mode": "automation",
                "capability_policy": "allowlist",
                "allowed_capability_ids": ["agent.restricted-lab-agent.file.read"],
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "restricted-lab", "title": "Restricted thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]

        restricted_workspace = self.core_domain.services.workspace.get_by_workspace_id("restricted-lab")
        agent = self.core_domain.services.agent.register_agent(
            agent_id="restricted-lab-agent",
            principal_id=self.core_domain.principal.id,
            agent_type="desktop",
            display_name="Restricted Agent",
            transport_profile="desktop_wss",
            workspace_rows=[restricted_workspace],
            owner_client_id=self.core_domain.services.client.ensure_client(
                client_id="electron-main",
                principal_id=self.core_domain.principal.id,
                client_type="electron",
                display_name="Electron Main",
            ).id,
        )
        self.core_domain.services.capability.replace_agent_capabilities(
            agent=agent,
            capabilities=[
                {
                    "capability_id": "agent.restricted-lab-agent.file.read",
                    "kind": "tool",
                    "title": "Read File",
                    "risk_level": "read",
                    "requires_confirmation": False,
                    "workspace_ids": ["restricted-lab"],
                },
                {
                    "capability_id": "agent.restricted-lab-agent.file.write",
                    "kind": "tool",
                    "title": "Write File",
                    "risk_level": "write",
                    "requires_confirmation": True,
                    "workspace_ids": ["restricted-lab"],
                },
            ],
            workspace_rows=[restricted_workspace],
            revision=1,
        )

        blocked_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "restricted-lab",
                "client_id": "electron-main",
                "title": "Blocked write",
                "operation_type": "capability_call",
                "execution_target": "specific_agent",
                "target_agent_id": "restricted-lab-agent",
                "capability_id": "agent.restricted-lab-agent.file.write",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(blocked_resp.status_code, 403)
        self.assertEqual(blocked_resp.json()["error"]["code"], "capability_not_allowed_in_workspace")

        allowed_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "restricted-lab",
                "client_id": "electron-main",
                "title": "Allowed read",
                "operation_type": "capability_call",
                "execution_target": "specific_agent",
                "target_agent_id": "restricted-lab-agent",
                "capability_id": "agent.restricted-lab-agent.file.read",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(allowed_resp.status_code, 200)

    def test_workspace_allowlist_requires_capability_id_for_capability_call(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "strict-lab",
                "title": "Strict Lab",
                "capability_policy": "allowlist",
                "allowed_capability_ids": ["core.memory.search"],
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "strict-lab", "title": "Strict thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]

        resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "strict-lab",
                "client_id": "electron-main",
                "title": "Missing capability",
                "operation_type": "capability_call",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "capability_required_by_workspace_policy")

    def test_workspace_allowlist_accepts_abstract_capability_key(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "abstract-lab",
                "title": "Abstract Lab",
                "capability_policy": "allowlist",
                "allowed_capability_ids": ["document.read"],
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "abstract-lab", "title": "Abstract thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]

        abstract_workspace = self.core_domain.services.workspace.get_by_workspace_id("abstract-lab")
        agent = self.core_domain.services.agent.register_agent(
            agent_id="abstract-agent",
            principal_id=self.core_domain.principal.id,
            agent_type="desktop",
            display_name="Abstract Agent",
            transport_profile="desktop_wss",
            workspace_rows=[abstract_workspace],
            owner_client_id=self.core_domain.services.client.ensure_client(
                client_id="electron-main",
                principal_id=self.core_domain.principal.id,
                client_type="electron",
                display_name="Electron Main",
            ).id,
        )
        self.core_domain.services.capability.replace_agent_capabilities(
            agent=agent,
            capabilities=[
                {
                    "capability_id": "agent.abstract-agent.file.read",
                    "abstract_capability_key": "document.read",
                    "kind": "tool",
                    "title": "Read Document",
                    "risk_level": "read",
                    "requires_confirmation": False,
                    "workspace_ids": ["abstract-lab"],
                }
            ],
            workspace_rows=[abstract_workspace],
            revision=1,
        )

        resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "abstract-lab",
                "client_id": "electron-main",
                "title": "Read by abstract key",
                "operation_type": "capability_call",
                "execution_target": "specific_agent",
                "target_agent_id": "abstract-agent",
                "capability_id": "document.read",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["capability_id"], "agent.abstract-agent.file.read")

    def test_message_defaults_to_workspace_base_mode(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "study-lab",
                "title": "Study Lab",
                "base_mode": "study",
                "prompt_overlay": "Prefer structured note-taking.",
                "default_execution_target": "core_only",
                "preferred_source_profiles": ["study_materials"],
                "memory_ranking_policy": "workspace_first",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "study-lab", "title": "Study thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]

        message_resp = self.client.post(
            "/client/messages",
            json={
                "thread_id": thread_id,
                "workspace_id": "study-lab",
                "client_id": "electron-main",
                "content": "help me study this material",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(message_resp.status_code, 200)

        queued_event = self.event_bus.inbound_queue.get_nowait()
        self.assertEqual(queued_event.metadata["preferred_mode"], "study")
        self.assertEqual(queued_event.metadata["workspace_prompt_overlay"], "Prefer structured note-taking.")
        self.assertEqual(queued_event.metadata["workspace_default_execution_target"], "core_only")
        self.assertEqual(queued_event.metadata["workspace_preferred_source_profiles"], ["study_materials"])
        self.assertEqual(queued_event.metadata["workspace_memory_ranking_policy"], "workspace_first")

    def test_operation_defaults_to_workspace_execution_target(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "research-lab",
                "title": "Research Lab",
                "base_mode": "research",
                "default_execution_target": "core_only",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "research-lab", "title": "Research thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]

        operation_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "research-lab",
                "client_id": "electron-main",
                "title": "Server-side summarize",
                "operation_type": "research_summary",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(operation_resp.status_code, 200)
        self.assertEqual(operation_resp.json()["execution_target"], "core_only")

    def test_workspace_any_agent_uses_workspace_preferred_agent_order(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "route-lab",
                "title": "Route Lab",
                "base_mode": "automation",
                "default_execution_target": "workspace_any_agent",
                "preferred_agent_ids": ["route-agent-b", "route-agent-a"],
                "preferred_agent_types": ["desktop"],
                "agent_routing_policy": "balanced",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)
        self.assertEqual(create_resp.json()["preferred_agent_ids"], ["route-agent-b", "route-agent-a"])
        self.assertEqual(create_resp.json()["preferred_agent_types"], ["desktop"])
        self.assertEqual(create_resp.json()["agent_routing_policy"], "balanced")

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "route-lab", "title": "Route thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]

        route_workspace = self.core_domain.services.workspace.get_by_workspace_id("route-lab")
        owner_client = self.core_domain.services.client.ensure_client(
            client_id="electron-main",
            principal_id=self.core_domain.principal.id,
            client_type="electron",
            display_name="Electron Main",
        )
        self.core_domain.services.agent.register_agent(
            principal_id=self.core_domain.principal.id,
            agent_id="route-agent-a",
            agent_type="desktop",
            display_name="Route Agent A",
            transport_profile="desktop_wss",
            workspace_rows=[route_workspace],
            owner_client_id=owner_client.id,
        )
        self.core_domain.services.agent.register_agent(
            principal_id=self.core_domain.principal.id,
            agent_id="route-agent-b",
            agent_type="desktop",
            display_name="Route Agent B",
            transport_profile="desktop_wss",
            workspace_rows=[route_workspace],
            owner_client_id=owner_client.id,
        )

        operation_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "route-lab",
                "client_id": "electron-main",
                "title": "Route selection",
                "operation_type": "route_only",
                "execution_target": "workspace_any_agent",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(operation_resp.status_code, 200)
        self.assertEqual(operation_resp.json()["target_agent_id"], "route-agent-b")
        self.assertIn("workspace", operation_resp.json()["routing_reason"].lower())

    def test_workspace_any_agent_resolves_abstract_capability_key(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "abstract-route-lab",
                "title": "Abstract Route Lab",
                "default_execution_target": "workspace_any_agent",
                "preferred_agent_ids": ["abstract-route-b", "abstract-route-a"],
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "abstract-route-lab", "title": "Abstract route thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]
        route_workspace = self.core_domain.services.workspace.get_by_workspace_id("abstract-route-lab")
        owner_client = self.core_domain.services.client.ensure_client(
            client_id="electron-main",
            principal_id=self.core_domain.principal.id,
            client_type="electron",
            display_name="Electron Main",
        )
        agent_a = self.core_domain.services.agent.register_agent(
            agent_id="abstract-route-a",
            principal_id=self.core_domain.principal.id,
            agent_type="desktop",
            display_name="Abstract Route A",
            transport_profile="desktop_wss",
            workspace_rows=[route_workspace],
            owner_client_id=owner_client.id,
        )
        agent_b = self.core_domain.services.agent.register_agent(
            agent_id="abstract-route-b",
            principal_id=self.core_domain.principal.id,
            agent_type="desktop",
            display_name="Abstract Route B",
            transport_profile="desktop_wss",
            workspace_rows=[route_workspace],
            owner_client_id=owner_client.id,
        )
        self.core_domain.services.capability.replace_agent_capabilities(
            agent=agent_a,
            capabilities=[
                {
                    "capability_id": "agent.abstract-route-a.file.read",
                    "abstract_capability_key": "document.read",
                    "kind": "tool",
                    "title": "Read Document A",
                    "risk_level": "read",
                    "requires_confirmation": False,
                    "workspace_ids": ["abstract-route-lab"],
                }
            ],
            workspace_rows=[route_workspace],
            revision=1,
        )
        self.core_domain.services.capability.replace_agent_capabilities(
            agent=agent_b,
            capabilities=[
                {
                    "capability_id": "agent.abstract-route-b.file.read",
                    "abstract_capability_key": "document.read",
                    "kind": "tool",
                    "title": "Read Document B",
                    "risk_level": "read",
                    "requires_confirmation": False,
                    "workspace_ids": ["abstract-route-lab"],
                }
            ],
            workspace_rows=[route_workspace],
            revision=1,
        )

        operation_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "abstract-route-lab",
                "client_id": "electron-main",
                "title": "Abstract route selection",
                "operation_type": "capability_call",
                "execution_target": "workspace_any_agent",
                "capability_id": "document.read",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(operation_resp.status_code, 200)
        self.assertEqual(operation_resp.json()["target_agent_id"], "abstract-route-b")
        self.assertEqual(operation_resp.json()["capability_id"], "agent.abstract-route-b.file.read")

    def test_capability_routing_override_overrides_workspace_default_preferences(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "override-lab",
                "title": "Override Lab",
                "default_execution_target": "workspace_any_agent",
                "preferred_agent_ids": ["override-agent-b", "override-agent-a"],
                "capability_routing_overrides": {
                    "document.read": {
                        "preferred_agent_ids": ["override-agent-a"],
                        "preferred_agent_types": ["desktop"],
                        "agent_routing_policy": "strict_preferred",
                    }
                },
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)
        self.assertIn("document.read", create_resp.json()["capability_routing_overrides"])

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "override-lab", "title": "Override thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]
        override_workspace = self.core_domain.services.workspace.get_by_workspace_id("override-lab")
        owner_client = self.core_domain.services.client.ensure_client(
            client_id="electron-main",
            principal_id=self.core_domain.principal.id,
            client_type="electron",
            display_name="Electron Main",
        )
        agent_a = self.core_domain.services.agent.register_agent(
            agent_id="override-agent-a",
            principal_id=self.core_domain.principal.id,
            agent_type="desktop",
            display_name="Override Agent A",
            transport_profile="desktop_wss",
            workspace_rows=[override_workspace],
            owner_client_id=owner_client.id,
        )
        agent_b = self.core_domain.services.agent.register_agent(
            agent_id="override-agent-b",
            principal_id=self.core_domain.principal.id,
            agent_type="desktop",
            display_name="Override Agent B",
            transport_profile="desktop_wss",
            workspace_rows=[override_workspace],
            owner_client_id=owner_client.id,
        )
        self.core_domain.services.capability.replace_agent_capabilities(
            agent=agent_a,
            capabilities=[
                {
                    "capability_id": "agent.override-agent-a.file.read",
                    "abstract_capability_key": "document.read",
                    "kind": "tool",
                    "title": "Read Document A",
                    "risk_level": "read",
                    "requires_confirmation": False,
                    "workspace_ids": ["override-lab"],
                }
            ],
            workspace_rows=[override_workspace],
            revision=1,
        )
        self.core_domain.services.capability.replace_agent_capabilities(
            agent=agent_b,
            capabilities=[
                {
                    "capability_id": "agent.override-agent-b.file.read",
                    "abstract_capability_key": "document.read",
                    "kind": "tool",
                    "title": "Read Document B",
                    "risk_level": "read",
                    "requires_confirmation": False,
                    "workspace_ids": ["override-lab"],
                }
            ],
            workspace_rows=[override_workspace],
            revision=1,
        )

        operation_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "override-lab",
                "client_id": "electron-main",
                "title": "Override route selection",
                "operation_type": "capability_call",
                "execution_target": "workspace_any_agent",
                "capability_id": "document.read",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(operation_resp.status_code, 200)
        self.assertEqual(operation_resp.json()["target_agent_id"], "override-agent-a")
        self.assertIn("document.read", operation_resp.json()["routing_reason"])

    def test_workspace_preferred_agent_types_influence_routing(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "type-lab",
                "title": "Type Lab",
                "default_execution_target": "workspace_any_agent",
                "preferred_agent_types": ["raspi", "desktop"],
                "agent_routing_policy": "balanced",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "type-lab", "title": "Type thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]
        type_workspace = self.core_domain.services.workspace.get_by_workspace_id("type-lab")
        owner_client = self.core_domain.services.client.ensure_client(
            client_id="electron-main",
            principal_id=self.core_domain.principal.id,
            client_type="electron",
            display_name="Electron Main",
        )
        self.core_domain.services.agent.register_agent(
            principal_id=self.core_domain.principal.id,
            agent_id="type-desktop-agent",
            agent_type="desktop",
            display_name="Type Desktop Agent",
            transport_profile="desktop_wss",
            workspace_rows=[type_workspace],
            owner_client_id=owner_client.id,
        )
        self.core_domain.services.agent.register_agent(
            principal_id=self.core_domain.principal.id,
            agent_id="type-raspi-agent",
            agent_type="raspi",
            display_name="Type Raspi Agent",
            transport_profile="edge_wss",
            workspace_rows=[type_workspace],
            owner_client_id=owner_client.id,
        )

        operation_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "type-lab",
                "client_id": "electron-main",
                "title": "Type preference route",
                "operation_type": "route_only",
                "execution_target": "workspace_any_agent",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(operation_resp.status_code, 200)
        self.assertEqual(operation_resp.json()["target_agent_id"], "type-raspi-agent")

    def test_workspace_prefer_owner_client_policy_overrides_preferred_agent_order(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "owner-lab",
                "title": "Owner Lab",
                "default_execution_target": "workspace_any_agent",
                "preferred_agent_ids": ["owner-other-agent", "owner-main-agent"],
                "agent_routing_policy": "prefer_owner_client",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "owner-lab", "title": "Owner thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]
        owner_workspace = self.core_domain.services.workspace.get_by_workspace_id("owner-lab")
        main_client = self.core_domain.services.client.ensure_client(
            client_id="electron-main",
            principal_id=self.core_domain.principal.id,
            client_type="electron",
            display_name="Electron Main",
        )
        other_client = self.core_domain.services.client.ensure_client(
            client_id="feishu-client",
            principal_id=self.core_domain.principal.id,
            client_type="feishu",
            display_name="Feishu Client",
        )
        self.core_domain.services.agent.register_agent(
            principal_id=self.core_domain.principal.id,
            agent_id="owner-main-agent",
            agent_type="desktop",
            display_name="Owner Main Agent",
            transport_profile="desktop_wss",
            workspace_rows=[owner_workspace],
            owner_client_id=main_client.id,
        )
        self.core_domain.services.agent.register_agent(
            principal_id=self.core_domain.principal.id,
            agent_id="owner-other-agent",
            agent_type="desktop",
            display_name="Owner Other Agent",
            transport_profile="desktop_wss",
            workspace_rows=[owner_workspace],
            owner_client_id=other_client.id,
        )

        operation_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "owner-lab",
                "client_id": "electron-main",
                "title": "Owner preference route",
                "operation_type": "route_only",
                "execution_target": "workspace_any_agent",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(operation_resp.status_code, 200)
        self.assertEqual(operation_resp.json()["target_agent_id"], "owner-main-agent")
        self.assertIn("prefer_owner_client", operation_resp.json()["routing_reason"])

    def test_workspace_strict_preferred_policy_rejects_non_preferred_fallback(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "strict-route-lab",
                "title": "Strict Route Lab",
                "default_execution_target": "workspace_any_agent",
                "preferred_agent_ids": ["strict-preferred-agent"],
                "agent_routing_policy": "strict_preferred",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "strict-route-lab", "title": "Strict route thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]
        strict_workspace = self.core_domain.services.workspace.get_by_workspace_id("strict-route-lab")
        owner_client = self.core_domain.services.client.ensure_client(
            client_id="electron-main",
            principal_id=self.core_domain.principal.id,
            client_type="electron",
            display_name="Electron Main",
        )
        self.core_domain.services.agent.register_agent(
            principal_id=self.core_domain.principal.id,
            agent_id="strict-other-agent",
            agent_type="desktop",
            display_name="Strict Other Agent",
            transport_profile="desktop_wss",
            workspace_rows=[strict_workspace],
            owner_client_id=owner_client.id,
        )

        operation_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "strict-route-lab",
                "client_id": "electron-main",
                "title": "Strict route",
                "operation_type": "route_only",
                "execution_target": "workspace_any_agent",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(operation_resp.status_code, 409)
        self.assertEqual(operation_resp.json()["error"]["code"], "workspace_agent_unavailable")

    def test_workspace_default_specific_agent_auto_selects_online_agent(self):
        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "desktop-main", "title": "Desktop default route"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]
        desktop_workspace = self.core_domain.services.workspace.get_by_workspace_id("desktop-main")
        owner_client = self.core_domain.services.client.ensure_client(
            client_id="electron-main",
            principal_id=self.core_domain.principal.id,
            client_type="electron",
            display_name="Electron Main",
        )
        self.core_domain.services.agent.register_agent(
            principal_id=self.core_domain.principal.id,
            agent_id="desktop-auto-agent",
            agent_type="desktop",
            display_name="Desktop Auto Agent",
            transport_profile="desktop_wss",
            workspace_rows=[desktop_workspace],
            owner_client_id=owner_client.id,
        )

        operation_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "desktop-main",
                "client_id": "electron-main",
                "title": "Desktop default route",
                "operation_type": "route_only",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(operation_resp.status_code, 200)
        self.assertEqual(operation_resp.json()["execution_target"], "specific_agent")
        self.assertEqual(operation_resp.json()["target_agent_id"], "desktop-auto-agent")

    def test_procedure_call_uses_procedure_capability_ref_and_routing_preferences(self):
        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "desktop-main", "title": "Procedure route thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]
        desktop_workspace = self.core_domain.services.workspace.get_by_workspace_id("desktop-main")
        owner_client = self.core_domain.services.client.ensure_client(
            client_id="electron-main",
            principal_id=self.core_domain.principal.id,
            client_type="electron",
            display_name="Electron Main",
        )
        desktop_agent = self.core_domain.services.agent.register_agent(
            principal_id=self.core_domain.principal.id,
            agent_id="desktop-procedure-agent",
            agent_type="desktop",
            display_name="Desktop Procedure Agent",
            transport_profile="desktop_wss",
            workspace_rows=[desktop_workspace],
            owner_client_id=owner_client.id,
        )
        self.core_domain.services.capability.replace_agent_capabilities(
            agent=desktop_agent,
            capabilities=[
                {
                    "capability_id": "agent.desktop-procedure-agent.manage.tasks",
                    "abstract_capability_key": "manage_tasks",
                    "kind": "tool",
                    "title": "Manage Tasks",
                    "risk_level": "write",
                    "requires_confirmation": True,
                    "workspace_ids": ["desktop-main"],
                }
            ],
            workspace_rows=[desktop_workspace],
            revision=1,
        )

        operation_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "desktop-main",
                "client_id": "electron-main",
                "title": "Procedure route",
                "operation_type": "procedure_call",
                "execution_target": "specific_agent",
                "arguments": {"procedure_id": "desktop_fix_loop"},
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(operation_resp.status_code, 200)
        payload = operation_resp.json()
        self.assertEqual(payload["target_agent_id"], "desktop-procedure-agent")
        self.assertEqual(payload["capability_id"], "agent.desktop-procedure-agent.manage.tasks")
        self.assertIn("procedure", payload["routing_reason"].lower())

    def test_prefer_agent_fallback_core_downgrades_when_no_agent_available(self):
        create_resp = self.client.post(
            "/operator/workspaces",
            json={
                "workspace_id": "fallback-lab",
                "title": "Fallback Lab",
                "default_execution_target": "prefer_agent_fallback_core",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(create_resp.status_code, 200)

        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "fallback-lab", "title": "Fallback thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]

        operation_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread_id,
                "workspace_id": "fallback-lab",
                "client_id": "electron-main",
                "title": "Fallback route",
                "operation_type": "route_only",
                "execution_target": "prefer_agent_fallback_core",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(operation_resp.status_code, 200)
        self.assertEqual(operation_resp.json()["execution_target"], "core_only")
        self.assertEqual(operation_resp.json()["target_agent_id"], "")
        self.assertIn("fallback", operation_resp.json()["routing_reason"].lower())

    def test_client_messages_and_websocket_flow(self):
        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Message flow", "pinned_procedure_id": "code_review"},
            headers=self._auth_headers(),
        )
        self.assertEqual(thread_resp.status_code, 200)
        thread_id = thread_resp.json()["thread_id"]

        with self.client.websocket_connect(
            f"/client/ws?thread_id={thread_id}",
            headers=self._auth_headers(),
        ) as websocket:
            connected = websocket.receive_json()
            self.assertEqual(connected["kind"], "connection")

            message_resp = self.client.post(
                "/client/messages",
                json={
                    "thread_id": thread_id,
                    "workspace_id": "personal",
                    "client_id": "electron-main",
                    "content": "hello new client api",
                },
                headers=self._auth_headers(),
            )
            self.assertEqual(message_resp.status_code, 200)
            created_event = websocket.receive_json()
            self.assertEqual(created_event["event"]["type"], "message.created")

            list_resp = self.client.get(f"/client/threads/{thread_id}/messages", headers=self._auth_headers())
            self.assertEqual(list_resp.status_code, 200)
            messages = list_resp.json()
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["content"], "hello new client api")

        queued_event = self.event_bus.inbound_queue.get_nowait()
        self.assertEqual(queued_event.metadata["workspace_id"], "personal")
        self.assertEqual(queued_event.metadata["pinned_procedure_id"], "code_review")
        self.assertEqual(queued_event.metadata["pinned_procedure"]["procedure_id"], "code_review")
        self.assertEqual(queued_event.metadata["workspace_preferred_source_profiles"], ["workspace_local"])
        self.assertEqual(queued_event.metadata["workspace_memory_ranking_policy"], "workspace_first")

    def test_client_message_rejects_session_from_other_thread(self):
        thread_a_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Thread A"},
            headers=self._auth_headers(),
        )
        thread_b_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Thread B"},
            headers=self._auth_headers(),
        )
        self.assertEqual(thread_a_resp.status_code, 200)
        self.assertEqual(thread_b_resp.status_code, 200)

        session_resp = self.client.post(
            "/client/sessions",
            json={
                "thread_id": thread_b_resp.json()["thread_id"],
                "workspace_id": "personal",
                "client_id": "electron-main",
                "client_type": "electron",
                "display_name": "Electron Main",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(session_resp.status_code, 200)

        message_resp = self.client.post(
            "/client/messages",
            json={
                "thread_id": thread_a_resp.json()["thread_id"],
                "workspace_id": "personal",
                "session_id": session_resp.json()["session_id"],
                "client_id": "electron-main",
                "content": "hello from wrong session",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(message_resp.status_code, 400)
        self.assertEqual(message_resp.json()["error"]["code"], "session_thread_mismatch")
        self.assertTrue(self.event_bus.inbound_queue.empty())

    def test_client_websocket_accepts_ping_and_confirm_commands(self):
        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Interactive flow"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]
        session_resp = self.client.post(
            "/client/sessions",
            json={
                "thread_id": thread_id,
                "workspace_id": "personal",
                "client_id": "electron-main",
                "client_type": "electron",
                "display_name": "Electron Main",
            },
            headers=self._auth_headers(),
        )
        session_id = session_resp.json()["session_id"]
        loop = asyncio.new_event_loop()
        try:
            future = loop.create_future()
            self.event_bus._register_pending_request(  # noqa: SLF001
                request_id="req-confirm-1",
                session_id=session_id,
                kind="confirm",
                future=future,
                event=None,
            )
            with self.client.websocket_connect(
                f"/client/ws?thread_id={thread_id}",
                headers=self._auth_headers(),
            ) as websocket:
                websocket.receive_json()
                websocket.send_json({"action": "ping"})
                pong = websocket.receive_json()
                self.assertEqual(pong["kind"], "pong")

                websocket.send_json(
                    {
                        "action": "confirm_response",
                        "session_id": session_id,
                        "request_id": "req-confirm-1",
                        "accepted": True,
                        "client_id": "electron-main",
                    }
                )
                ack = websocket.receive_json()
                self.assertEqual(ack["kind"], "ack")
                self.assertTrue(future.done())
                self.assertTrue(future.result())
        finally:
            loop.close()

    def test_http_confirm_response_endpoint_submits_event_bus(self):
        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Confirm endpoint"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]
        session_resp = self.client.post(
            "/client/sessions",
            json={
                "thread_id": thread_id,
                "workspace_id": "personal",
                "client_id": "electron-main",
                "client_type": "electron",
                "display_name": "Electron Main",
            },
            headers=self._auth_headers(),
        )
        session_id = session_resp.json()["session_id"]

        loop = asyncio.new_event_loop()
        try:
            future = loop.create_future()
            self.event_bus._register_pending_request(  # noqa: SLF001
                request_id="req-confirm-http",
                session_id=session_id,
                kind="confirm",
                future=future,
                event=None,
            )
            response = self.client.post(
                f"/client/sessions/{session_id}/confirm-response",
                json={
                    "accepted": True,
                    "request_id": "req-confirm-http",
                    "client_id": "electron-main",
                },
                headers=self._auth_headers(),
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["request_id"], "req-confirm-http")
            self.assertEqual(payload["session_id"], session_id)
            self.assertTrue(payload["accepted"])
            self.assertTrue(future.done())
            self.assertTrue(future.result())
        finally:
            loop.close()

    def test_http_human_input_response_endpoint_submits_event_bus(self):
        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Human input endpoint"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]
        session_resp = self.client.post(
            "/client/sessions",
            json={
                "thread_id": thread_id,
                "workspace_id": "personal",
                "client_id": "electron-main",
                "client_type": "electron",
                "display_name": "Electron Main",
            },
            headers=self._auth_headers(),
        )
        session_id = session_resp.json()["session_id"]

        loop = asyncio.new_event_loop()
        try:
            future = loop.create_future()
            pending_event = HumanInputRequestEvent(
                session_id=session_id,
                type="human_input_request",
                role="system",
                content="Why?",
                question="Why?",
                options=["A", "B"],
                placeholder="",
                source=make_source("system", "human_input"),
                target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
            )
            self.event_bus._register_pending_request(  # noqa: SLF001
                request_id=pending_event.request_id,
                session_id=session_id,
                kind="human_input",
                future=future,
                event=pending_event,
            )
            response = self.client.post(
                f"/client/sessions/{session_id}/human-input-response",
                json={
                    "request_id": pending_event.request_id,
                    "answer_text": "Because it matches the requirement",
                    "selected_option": "A",
                    "client_id": "electron-main",
                },
                headers=self._auth_headers(),
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["request_id"], pending_event.request_id)
            self.assertEqual(payload["session_id"], session_id)
            self.assertEqual(payload["answer_text"], "Because it matches the requirement")
            self.assertEqual(payload["selected_option"], "A")
            self.assertTrue(future.done())
            self.assertEqual(
                future.result(),
                {
                    "answered": True,
                    "timed_out": False,
                    "selected_option": "A",
                    "answer_text": "Because it matches the requirement",
                    "request_id": pending_event.request_id,
                    "session_id": session_id,
                },
            )
        finally:
            loop.close()

    def test_chat_confirmation_approval_decision_resolves_pending_confirm(self):
        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Approval confirm thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]
        session_resp = self.client.post(
            "/client/sessions",
            json={
                "thread_id": thread_id,
                "workspace_id": "personal",
                "client_id": "electron-main",
                "client_type": "electron",
                "display_name": "Electron Main",
            },
            headers=self._auth_headers(),
        )
        session_id = session_resp.json()["session_id"]
        session_row = self.core_domain.services.session.get_by_session_id(session_id)
        thread_row = self.core_domain.services.thread.get_by_thread_id(thread_id)
        workspace_row = self.core_domain.services.workspace.get_by_workspace_id("personal")
        operation = self.core_domain.services.operation.create_operation(
            thread_id=thread_row.id,
            workspace_id=workspace_row.id,
            operation_type="chat_confirmation",
            execution_target="core_only",
            title="Chat Confirmation",
            requested_by_client_id=session_row.client_id,
            requested_by_session_id=session_row.id,
            status="waiting_approval",
            metadata={
                "confirm_request_id": "req-approval-confirm",
                "confirm_session_id": session_id,
                "approval_required": True,
            },
        )
        approval = self.core_domain.services.approval.create_approval(
            operation_id=operation.id,
            approval_type="chat_confirmation",
            risk_level="system",
        )
        self.core_domain.services.operation.update_status(
            operation_id=operation.id,
            status="waiting_approval",
            metadata={
                "approval_id": approval.approval_id,
                "approval_status": approval.status,
            },
        )

        async def on_confirm_response(payload):
            updated_approval = self.core_domain.services.approval.decide_approval(
                approval_id=approval.approval_id,
                decision="approve" if payload.get("accepted") else "reject",
                reason=str(payload.get("reason") or ""),
                decided_by_client_id=None,
            )
            self.core_domain.services.operation.update_status(
                operation_id=operation.id,
                status="succeeded" if payload.get("accepted") else "rejected",
                result_summary="确认已通过" if payload.get("accepted") else "确认已拒绝",
                metadata={
                    "approval_id": approval.approval_id,
                    "approval_status": getattr(updated_approval, "status", ""),
                    "confirm_decision": "approve" if payload.get("accepted") else "reject",
                },
            )

        self.event_bus.subscribe(self.event_bus.CONFIRM_RESPONSE, on_confirm_response)

        loop = asyncio.new_event_loop()
        try:
            future = loop.create_future()
            self.event_bus._register_pending_request(  # noqa: SLF001
                request_id="req-approval-confirm",
                session_id=session_id,
                kind="confirm",
                future=future,
                event=None,
            )
            response = self.client.post(
                f"/client/approvals/{approval.approval_id}/decision",
                json={
                    "decision": "approve",
                    "reason": "approved from approval route",
                    "client_id": "electron-main",
                },
                headers=self._auth_headers(),
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "approved")
            self.assertEqual(payload["operation_status"], "succeeded")
            self.assertTrue(future.done())
            self.assertTrue(future.result())
            refreshed = self.core_domain.services.approval.get_by_approval_id(approval.approval_id)
            self.assertEqual(refreshed.status, "approved")
        finally:
            loop.close()

    def test_procedure_governance_approval_decision_resolves_pending_confirm(self):
        thread_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Procedure governance thread"},
            headers=self._auth_headers(),
        )
        thread_id = thread_resp.json()["thread_id"]
        session_resp = self.client.post(
            "/client/sessions",
            json={
                "thread_id": thread_id,
                "workspace_id": "personal",
                "client_id": "electron-main",
                "client_type": "electron",
                "display_name": "Electron Main",
            },
            headers=self._auth_headers(),
        )
        session_id = session_resp.json()["session_id"]
        session_row = self.core_domain.services.session.get_by_session_id(session_id)
        thread_row = self.core_domain.services.thread.get_by_thread_id(thread_id)
        workspace_row = self.core_domain.services.workspace.get_by_workspace_id("personal")
        operation = self.core_domain.services.operation.create_operation(
            thread_id=thread_row.id,
            workspace_id=workspace_row.id,
            operation_type="procedure_governance",
            execution_target="core_only",
            title="Procedure Governance",
            requested_by_client_id=session_row.client_id,
            requested_by_session_id=session_row.id,
            status="waiting_approval",
            metadata={
                "confirm_request_id": "req-procedure-governance",
                "confirm_session_id": session_id,
                "approval_required": True,
            },
        )
        approval = self.core_domain.services.approval.create_approval(
            operation_id=operation.id,
            approval_type="procedure_governance",
            risk_level="write",
        )
        self.core_domain.services.operation.update_status(
            operation_id=operation.id,
            status="waiting_approval",
            metadata={
                "approval_id": approval.approval_id,
                "approval_status": approval.status,
            },
        )

        async def on_confirm_response(payload):
            updated_approval = self.core_domain.services.approval.decide_approval(
                approval_id=approval.approval_id,
                decision="approve" if payload.get("accepted") else "reject",
                reason=str(payload.get("reason") or ""),
                decided_by_client_id=None,
            )
            self.core_domain.services.operation.update_status(
                operation_id=operation.id,
                status="succeeded" if payload.get("accepted") else "rejected",
                result_summary="治理已通过" if payload.get("accepted") else "治理已拒绝",
                metadata={
                    "approval_id": approval.approval_id,
                    "approval_status": getattr(updated_approval, "status", ""),
                },
            )

        self.event_bus.subscribe(self.event_bus.CONFIRM_RESPONSE, on_confirm_response)

        loop = asyncio.new_event_loop()
        try:
            future = loop.create_future()
            self.event_bus._register_pending_request(  # noqa: SLF001
                request_id="req-procedure-governance",
                session_id=session_id,
                kind="confirm",
                future=future,
                event=None,
            )
            response = self.client.post(
                f"/client/approvals/{approval.approval_id}/decision",
                json={
                    "decision": "approve",
                    "reason": "approved from procedure governance approval route",
                    "client_id": "electron-main",
                },
                headers=self._auth_headers(),
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "approved")
            self.assertEqual(payload["operation_status"], "succeeded")
            self.assertTrue(future.done())
            self.assertTrue(future.result())
        finally:
            loop.close()

    def test_client_websocket_rejects_session_outside_thread(self):
        thread_a_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Thread A"},
            headers=self._auth_headers(),
        )
        thread_b_resp = self.client.post(
            "/client/threads",
            json={"workspace_id": "personal", "title": "Thread B"},
            headers=self._auth_headers(),
        )
        session_resp = self.client.post(
            "/client/sessions",
            json={
                "thread_id": thread_b_resp.json()["thread_id"],
                "workspace_id": "personal",
                "client_id": "electron-main",
                "client_type": "electron",
                "display_name": "Electron Main",
            },
            headers=self._auth_headers(),
        )
        session_id = session_resp.json()["session_id"]

        with self.client.websocket_connect(
            f"/client/ws?thread_id={thread_a_resp.json()['thread_id']}",
            headers=self._auth_headers(),
        ) as websocket:
            websocket.receive_json()
            websocket.send_json(
                {
                    "action": "confirm_response",
                    "session_id": session_id,
                    "request_id": "req-confirm-1",
                    "accepted": True,
                    "client_id": "electron-main",
                }
            )
            error = websocket.receive_json()
            self.assertEqual(error["kind"], "error")
            self.assertEqual(error["error"]["code"], "session_thread_mismatch")

    def test_client_operation_and_approval_decision(self):
        desktop_workspace = self.core_domain.services.workspace.get_by_workspace_id("desktop-main")
        thread = self.core_domain.services.thread.create_thread(
            principal_id=self.core_domain.principal.id,
            workspace_id=desktop_workspace.id,
            title="Operation thread",
        )
        agent = self.core_domain.services.agent.ensure_agent(
            agent_id="desktop-main-agent",
            principal_id=self.core_domain.principal.id,
            agent_type="desktop",
            display_name="Desktop Agent",
            transport_profile="desktop_wss",
            owner_client_id=self.core_domain.services.client.ensure_client(
                client_id="electron-main",
                principal_id=self.core_domain.principal.id,
                client_type="electron",
                display_name="Electron Main",
            ).id,
        )
        self.core_domain.services.agent.bind_workspace(workspace_id=desktop_workspace.id, agent_id=agent.id)
        self.core_domain.services.capability.replace_agent_capabilities(
            agent=agent,
            capabilities=[
                {
                    "capability_id": "agent.desktop-main-agent.desktop.capture",
                    "kind": "tool",
                    "title": "Desktop Capture",
                    "risk_level": "write",
                    "requires_confirmation": True,
                    "workspace_ids": ["desktop-main"],
                }
            ],
            workspace_rows=[desktop_workspace],
            revision=1,
        )

        dispatch_calls = []

        async def fake_dispatch_agent_call(*, agent_id: str, payload: dict) -> bool:
            dispatch_calls.append((agent_id, payload))
            return True

        self.gateway.dispatch_agent_call = fake_dispatch_agent_call

        operation_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread.thread_id,
                "workspace_id": "desktop-main",
                "client_id": "electron-main",
                "title": "Capture screenshot",
                "operation_type": "capture_screenshot",
                "execution_target": "specific_agent",
                "target_agent_id": "desktop-main-agent",
                "capability_id": "agent.desktop-main-agent.desktop.capture",
                "arguments": {"display": "primary"},
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(operation_resp.status_code, 200)
        operation_payload = operation_resp.json()
        self.assertEqual(operation_payload["target_agent_id"], "desktop-main-agent")
        self.assertEqual(operation_payload["thread_id"], thread.thread_id)
        self.assertEqual(operation_payload["status"], "waiting_approval")
        self.assertTrue(operation_payload["approval_required"])
        self.assertEqual(operation_payload["approval_status"], "pending")
        self.assertTrue(operation_payload["approval_id"])
        self.assertEqual(dispatch_calls, [])

        operation = self.core_domain.services.operation.get_by_operation_id(operation_payload["operation_id"])
        requesting_client = self.core_domain.services.client.get_by_client_id("electron-main")
        self.assertEqual(operation.requested_by_client_id, requesting_client.id)
        decision_resp = self.client.post(
            f"/client/approvals/{operation_payload['approval_id']}/decision",
            json={"decision": "approve", "reason": "allowed", "client_id": "electron-main"},
            headers=self._auth_headers(),
        )
        self.assertEqual(decision_resp.status_code, 200)
        decision_payload = decision_resp.json()
        self.assertEqual(decision_payload["decision"], "approve")
        self.assertEqual(decision_payload["status"], "approved")
        self.assertEqual(decision_payload["operation_id"], operation.operation_id)
        self.assertEqual(decision_payload["operation_status"], "dispatching")
        self.assertEqual(len(dispatch_calls), 1)

        refreshed = self.core_domain.services.operation.get_by_operation_id(operation_payload["operation_id"])
        self.assertEqual(refreshed.status, "dispatching")
        self.assertEqual(refreshed.meta.get("approval_status"), "approved")
        self.assertTrue(refreshed.meta.get("last_call_id"))

    def test_client_operation_rejection_updates_operation_without_dispatch(self):
        desktop_workspace = self.core_domain.services.workspace.get_by_workspace_id("desktop-main")
        thread = self.core_domain.services.thread.create_thread(
            principal_id=self.core_domain.principal.id,
            workspace_id=desktop_workspace.id,
            title="Reject operation thread",
        )
        agent = self.core_domain.services.agent.ensure_agent(
            agent_id="desktop-main-agent-reject",
            principal_id=self.core_domain.principal.id,
            agent_type="desktop",
            display_name="Desktop Agent Reject",
            transport_profile="desktop_wss",
            owner_client_id=self.core_domain.services.client.ensure_client(
                client_id="electron-main",
                principal_id=self.core_domain.principal.id,
                client_type="electron",
                display_name="Electron Main",
            ).id,
        )
        self.core_domain.services.agent.bind_workspace(workspace_id=desktop_workspace.id, agent_id=agent.id)
        self.core_domain.services.capability.replace_agent_capabilities(
            agent=agent,
            capabilities=[
                {
                    "capability_id": "agent.desktop-main-agent-reject.file.write",
                    "kind": "tool",
                    "title": "Write File",
                    "risk_level": "write",
                    "requires_confirmation": True,
                    "workspace_ids": ["desktop-main"],
                }
            ],
            workspace_rows=[desktop_workspace],
            revision=1,
        )

        dispatch_calls = []

        async def fake_dispatch_agent_call(*, agent_id: str, payload: dict) -> bool:
            dispatch_calls.append((agent_id, payload))
            return True

        self.gateway.dispatch_agent_call = fake_dispatch_agent_call

        operation_resp = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread.thread_id,
                "workspace_id": "desktop-main",
                "client_id": "electron-main",
                "title": "Write config",
                "operation_type": "capability_call",
                "execution_target": "specific_agent",
                "target_agent_id": "desktop-main-agent-reject",
                "capability_id": "agent.desktop-main-agent-reject.file.write",
                "arguments": {"path": "README.md"},
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(operation_resp.status_code, 200)
        approval_id = operation_resp.json()["approval_id"]

        decision_resp = self.client.post(
            f"/client/approvals/{approval_id}/decision",
            json={"decision": "reject", "reason": "not now", "client_id": "electron-main"},
            headers=self._auth_headers(),
        )
        self.assertEqual(decision_resp.status_code, 200)
        self.assertEqual(decision_resp.json()["status"], "rejected")
        self.assertEqual(decision_resp.json()["operation_status"], "rejected")
        self.assertEqual(dispatch_calls, [])

        operation = self.core_domain.services.operation.get_by_operation_id(operation_resp.json()["operation_id"])
        self.assertEqual(operation.status, "rejected")
        self.assertEqual(operation.meta.get("approval_status"), "rejected")

    def test_client_operation_rejects_cross_workspace_agent(self):
        personal_workspace = self.core_domain.services.workspace.get_by_workspace_id("personal")
        desktop_workspace = self.core_domain.services.workspace.get_by_workspace_id("desktop-main")
        thread = self.core_domain.services.thread.create_thread(
            principal_id=self.core_domain.principal.id,
            workspace_id=personal_workspace.id,
            title="Boundary thread",
        )
        agent = self.core_domain.services.agent.ensure_agent(
            agent_id="desktop-boundary-agent",
            principal_id=self.core_domain.principal.id,
            agent_type="desktop",
            display_name="Desktop Agent",
            transport_profile="desktop_wss",
            owner_client_id=self.core_domain.services.client.ensure_client(
                client_id="electron-main",
                principal_id=self.core_domain.principal.id,
                client_type="electron",
                display_name="Electron Main",
            ).id,
        )
        self.core_domain.services.agent.bind_workspace(workspace_id=desktop_workspace.id, agent_id=agent.id)

        response = self.client.post(
            "/client/operations",
            json={
                "thread_id": thread.thread_id,
                "workspace_id": "personal",
                "title": "Wrong workspace agent",
                "operation_type": "capability_call",
                "execution_target": "specific_agent",
                "target_agent_id": "desktop-boundary-agent",
            },
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "agent_workspace_mismatch")

    def test_operator_and_developer_surfaces(self):
        health_resp = self.client.get("/operator/health", headers=self._auth_headers())
        self.assertEqual(health_resp.status_code, 200)
        self.assertEqual(health_resp.json()["kind"], "health")

        debug_resp = self.client.get("/developer/runtime/debug", params={"session_id": "sess_1"}, headers=self._auth_headers())
        self.assertEqual(debug_resp.status_code, 200)
        self.assertEqual(debug_resp.json()["runtime"]["resource"], "debug")

    def test_operator_config_and_memory_routes_read_db_state(self):
        personal_workspace = self.core_domain.services.workspace.get_by_workspace_id("personal")
        self.core_domain.services.config_state.replace_entries(
            [
                {
                    "config_key": "api_provider",
                    "value_json": "openai",
                    "is_secret": False,
                    "has_value": True,
                    "source": "config",
                    "env_key": None,
                    "meta": {},
                }
            ]
        )
        self.core_domain.services.memory_state.replace_records(
            principal_id=self.core_domain.principal.id,
            records=[
                {
                    "memory_id": "mem_1",
                    "record_type": "profile",
                    "content": "name: 阿明",
                    "canonical_text": "name: 阿明",
                    "scope_user_id": "browser-tab-a",
                    "scope_session_id": "s1",
                    "origin_workspace_id": personal_workspace.id,
                    "raw_record": {
                        "strength": 0.72,
                        "importance": 0.9,
                        "confidence": 0.95,
                        "created_at": "2026-04-10T09:30:00Z",
                        "last_accessed_at": "2026-04-10T09:31:00Z",
                        "last_updated_at": "2026-04-10T09:32:00Z",
                        "tags": [],
                        "entity_keys": [],
                        "source_record_ids": [],
                        "fact_key": "name",
                        "fact_value": "阿明",
                    },
                    "meta": {},
                    "workspace_ids": [personal_workspace.id],
                }
            ],
        )

        config_resp = self.client.get("/operator/config", headers=self._auth_headers())
        memory_resp = self.client.get(
            "/operator/memory",
            params={"source_id": "browser-tab-a", "session_id": "s1"},
            headers=self._auth_headers(),
        )

        self.assertEqual(config_resp.status_code, 200)
        self.assertEqual(memory_resp.status_code, 200)
        self.assertEqual(config_resp.json()["items"]["api_provider"]["value"], "openai")
        self.assertEqual(memory_resp.json()["records"][0]["fact_value"], "阿明")
        self.assertEqual(memory_resp.json()["records"][0]["workspace_tags"], ["personal"])
        self.assertEqual(memory_resp.json()["records"][0]["source_label"], "工作区:personal")
        self.assertEqual(memory_resp.json()["records"][0]["created_at"], "2026-04-10T09:30:00Z")
        self.assertEqual(memory_resp.json()["records"][0]["last_accessed_at"], "2026-04-10T09:31:00Z")
        self.assertEqual(memory_resp.json()["records"][0]["last_updated_at"], "2026-04-10T09:32:00Z")

    def test_operator_memory_routes_reflect_runtime_state_blob_sync(self):
        self.core_domain.services.state_blob.save_state(
            principal_id=self.core_domain.principal.id,
            state_key="memory_graph",
            payload={
                "metadata": {"schema_version": "2", "revision": 1},
                "records": [
                    {
                        "id": "mem_runtime_1",
                        "type": "profile",
                        "scope": {"user_id": "browser-tab-a", "session_id": ""},
                        "content": "name: 小白",
                        "canonical_text": "name: 小白",
                        "status": "active",
                        "workspace_tags": ["personal"],
                        "origin_workspace_id": "personal",
                        "fact_key": "name",
                        "fact_value": "小白",
                    }
                ],
                "edges": [],
                "working_summaries": {"global": "", "by_session": {}},
            },
            meta={"source": "test"},
        )
        app = type(
            "_App",
            (),
            {
                "core_services": self.core_domain.services,
                "core_domain": self.core_domain,
            },
        )()

        asyncio.run(sync_memory_state_to_db(app))

        memory_resp = self.client.get("/operator/memory", headers=self._auth_headers())
        self.assertEqual(memory_resp.status_code, 200)
        self.assertEqual(memory_resp.json()["records"][0]["id"], "mem_runtime_1")
        self.assertEqual(memory_resp.json()["records"][0]["fact_value"], "小白")
        self.assertEqual(memory_resp.json()["records"][0]["workspace_tags"], ["personal"])


if __name__ == "__main__":
    unittest.main()
