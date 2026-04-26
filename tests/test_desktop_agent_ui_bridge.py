from __future__ import annotations

import unittest
raise unittest.SkipTest("Legacy Desktop Agent UI bridge tests were replaced by Desktop Client coverage.")

import asyncio
import json
import socket
import tempfile
import time
import unittest
from pathlib import Path

import aiohttp
from aiohttp import ClientSession, web

from desktop_agent.config import DesktopAgentConfig
from desktop_agent.desktop_api import LOCAL_BRIDGE_STATUS_PATH, DesktopApiServer


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class DesktopApiServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session_start_count = 0
        self.health_delay_seconds = 0.0
        self.core_port = _unused_port()
        self.bridge_port = _unused_port()
        self.core_base_url = f"http://127.0.0.1:{self.core_port}"
        self.bridge_base_url = f"http://127.0.0.1:{self.bridge_port}"
        self.core_runner = web.AppRunner(self._build_core_app())
        await self.core_runner.setup()
        self.core_site = web.TCPSite(self.core_runner, host="127.0.0.1", port=self.core_port)
        await self.core_site.start()

        async def _mark_session_started() -> None:
            self.session_start_count += 1

        self.bridge = DesktopApiServer(
            DesktopAgentConfig(
                core_base_url=self.core_base_url,
                agent_access_token="agent-token",
                gateway_access_token="core-token",
                local_bridge_port=self.bridge_port,
                local_bridge_access_token="local-token",
            ),
            on_client_session_created=_mark_session_started,
        )
        await self.bridge.start()

    async def asyncTearDown(self):
        await self.bridge.stop()
        await self.core_runner.cleanup()

    def _build_core_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/client/workspaces", self._handle_workspaces)
        app.router.add_post("/client/sessions", self._handle_sessions)
        app.router.add_post("/client/attachments/upload-ticket", self._handle_upload_ticket)
        app.router.add_put("/client/attachments/upload/{ticket_id}", self._handle_upload_content)
        app.router.add_get("/client/attachments/{attachment_id}/download-ticket", self._handle_download_ticket)
        app.router.add_get("/client/attachments/content/{attachment_id}", self._handle_download_content)
        app.router.add_get("/client/ws", self._handle_client_ws)
        return app

    @staticmethod
    def _assert_core_auth(request: web.Request) -> None:
        self_auth = str(request.headers.get("Authorization") or "")
        assert self_auth == "Bearer core-token"

    async def _handle_health(self, request: web.Request) -> web.Response:
        self._assert_core_auth(request)
        if self.health_delay_seconds:
            await asyncio.sleep(self.health_delay_seconds)
        return web.json_response({"status": "ready", "health": {"build_info": {"git_commit": "core-commit", "branch": "main", "build_time": "2026-04-24T00:00:00Z", "component": "core", "package_version": "1.0.0"}}})

    async def _handle_workspaces(self, request: web.Request) -> web.Response:
        self._assert_core_auth(request)
        return web.json_response([
            {"workspace_id": "personal", "title": "Personal", "base_mode": "general"},
        ])

    async def _handle_upload_ticket(self, request: web.Request) -> web.Response:
        self._assert_core_auth(request)
        payload = await request.json()
        return web.json_response(
            {
                "attachment_id": "att_1",
                "ticket_id": "up_1",
                "upload_url": f"{self.core_base_url}/client/attachments/upload/up_1",
                "expires_at": "2026-04-18T00:00:00Z",
                "object_key": f"attachments/{payload['owner_id']}/att_1",
                "status": "pending",
            }
        )

    async def _handle_sessions(self, request: web.Request) -> web.Response:
        self._assert_core_auth(request)
        payload = await request.json()
        return web.json_response(
            {
                "session_id": "sess_1",
                "thread_id": payload["thread_id"],
                "workspace_id": payload["workspace_id"],
                "client_id": payload["client_id"],
                "status": "active",
            }
        )

    async def _handle_download_ticket(self, request: web.Request) -> web.Response:
        self._assert_core_auth(request)
        attachment_id = request.match_info["attachment_id"]
        download_url = f"{self.core_base_url}/client/attachments/content/{attachment_id}?ticket_id=down_1"
        return web.json_response(
            {
                "attachment_id": attachment_id,
                "ticket_id": "down_1",
                "download_url": download_url,
                "fallback_download_url": download_url,
                "download_strategy": "proxy",
                "expires_at": "2026-04-18T00:00:00Z",
                "mime_type": "text/plain",
                "file_name": "report.txt",
                "size_bytes": 128,
            }
        )

    async def _handle_upload_content(self, request: web.Request) -> web.Response:
        self._assert_core_auth(request)
        content = await request.read()
        self.assertEqual(content, b"desktop-upload")
        return web.json_response(
            {
                "attachment_id": "att_1",
                "ticket_id": request.match_info["ticket_id"],
                "status": "uploaded",
                "size_bytes": len(content),
                "sha256": "demo-sha",
            }
        )

    async def _handle_download_content(self, request: web.Request) -> web.Response:
        self._assert_core_auth(request)
        self.assertEqual(request.query.get("ticket_id"), "down_1")
        return web.Response(
            body=b"desktop-download",
            headers={
                "Content-Type": "text/plain",
                "Content-Disposition": 'attachment; filename="report.txt"',
            },
        )

    async def _handle_client_ws(self, request: web.Request) -> web.StreamResponse:
        self._assert_core_auth(request)
        self.assertEqual(request.query.get("thread_id"), "thr_1")
        self.assertIsNone(request.query.get("access_token"))
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        async for message in websocket:
            if message.type == aiohttp.WSMsgType.TEXT:
                await websocket.send_str(message.data)
        return websocket

    async def test_status_endpoint_is_available_without_local_auth(self):
        async with ClientSession() as session:
            async with session.get(f"{self.bridge_base_url}{LOCAL_BRIDGE_STATUS_PATH}") as response:
                self.assertEqual(response.status, 200)
                payload = await response.json()
        self.assertEqual(payload["local_bridge_base_url"], self.bridge_base_url)
        self.assertEqual(payload["core_base_url"], self.core_base_url)
        self.assertEqual(payload["core_build_info"]["git_commit"], "core-commit")
        self.assertEqual(payload["build_info"]["component"], "desktop_backend")

    async def test_status_endpoint_does_not_wait_on_slow_core_health(self):
        self.health_delay_seconds = 2.0
        started_at = time.perf_counter()
        async with ClientSession() as session:
            async with session.get(f"{self.bridge_base_url}{LOCAL_BRIDGE_STATUS_PATH}") as response:
                self.assertEqual(response.status, 200)
                payload = await response.json()
        elapsed = time.perf_counter() - started_at
        self.assertLess(elapsed, 1.5)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["core_build_info"], {})

    async def test_http_proxy_requires_local_auth_and_rewrites_attachment_ticket_urls(self):
        async with ClientSession() as session:
            async with session.get(f"{self.bridge_base_url}/desktop/workspaces") as unauthorized:
                self.assertEqual(unauthorized.status, 401)

            headers = {"Authorization": "Bearer local-token"}
            async with session.get(f"{self.bridge_base_url}/desktop/workspaces", headers=headers) as response:
                self.assertEqual(response.status, 200)
                payload = await response.json()
            self.assertEqual(payload[0]["workspace_id"], "personal")

            async with session.post(
                f"{self.bridge_base_url}/desktop/attachments/upload-ticket",
                headers=headers,
                json={
                    "owner_type": "thread",
                    "owner_id": "thr_1",
                    "kind": "file",
                    "mime_type": "text/plain",
                },
            ) as upload_response:
                self.assertEqual(upload_response.status, 200)
                upload_payload = await upload_response.json()
            self.assertEqual(
                upload_payload["upload_url"],
                f"{self.bridge_base_url}/desktop/attachments/upload/up_1",
            )

            async with session.put(
                upload_payload["upload_url"],
                headers=headers,
                data=b"desktop-upload",
            ) as upload_content_response:
                self.assertEqual(upload_content_response.status, 200)
                upload_content_payload = await upload_content_response.json()
            self.assertEqual(upload_content_payload["status"], "uploaded")

            async with session.get(
                f"{self.bridge_base_url}/desktop/attachments/att_1/download-ticket",
                headers=headers,
            ) as download_response:
                self.assertEqual(download_response.status, 200)
                download_payload = await download_response.json()
            self.assertEqual(
                download_payload["download_url"],
                f"{self.bridge_base_url}/desktop/attachments/content/att_1?ticket_id=down_1",
            )
            self.assertEqual(
                download_payload["fallback_download_url"],
                f"{self.bridge_base_url}/desktop/attachments/content/att_1?ticket_id=down_1",
            )

            async with session.get(download_payload["download_url"], headers=headers) as download_content_response:
                self.assertEqual(download_content_response.status, 200)
                self.assertEqual(await download_content_response.read(), b"desktop-download")

    async def test_client_websocket_is_proxied_through_local_bridge(self):
        async with ClientSession() as session:
            websocket = await session.ws_connect(
                f"{self.bridge_base_url}/desktop/ws?thread_id=thr_1&access_token=local-token"
            )
            try:
                await websocket.send_str('{"text":"hello-bridge"}')
                message = await websocket.receive()
            finally:
                await websocket.close()

        self.assertEqual(message.type, aiohttp.WSMsgType.TEXT)
        self.assertEqual(message.data, '{"text":"hello-bridge"}')

    async def test_session_creation_triggers_runtime_start_callback(self):
        headers = {"Authorization": "Bearer local-token"}
        async with ClientSession() as session:
            async with session.post(
                f"{self.bridge_base_url}/desktop/sessions",
                headers=headers,
                json={
                    "thread_id": "thr_1",
                    "workspace_id": "personal",
                    "client_id": "desktop-app",
                    "client_type": "electron",
                    "display_name": "Desktop App",
                },
            ) as response:
                self.assertEqual(response.status, 200)
                payload = await response.json()

        self.assertEqual(payload["session_id"], "sess_1")
        self.assertEqual(self.session_start_count, 1)


class DesktopApiLocalConfigTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.temp_dir.name)
        self.config_path = self.runtime_root / "user" / "desktop_agent.json"
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(
                {
                    "core_base_url": "http://127.0.0.1:9",
                    "gateway_access_token": "",
                    "agent_access_token": "",
                }
            ),
            encoding="utf-8",
        )
        self.bridge_port = _unused_port()
        self.bridge_base_url = f"http://127.0.0.1:{self.bridge_port}"
        self.bridge = DesktopApiServer(
            DesktopAgentConfig(
                core_base_url="http://127.0.0.1:9",
                gateway_access_token="",
                agent_access_token="",
                local_bridge_port=self.bridge_port,
                local_bridge_access_token="local-token",
                config_file_path=str(self.config_path),
            )
        )
        await self.bridge.start()

    async def asyncTearDown(self):
        await self.bridge.stop()
        self.temp_dir.cleanup()

    async def test_config_page_can_update_remote_core_url_when_core_is_unreachable(self):
        headers = {"Authorization": "Bearer local-token"}
        async with ClientSession(headers=headers) as session:
            async with session.get(f"{self.bridge_base_url}/desktop/config/schema") as schema_response:
                self.assertEqual(schema_response.status, 200)
                schema_payload = await schema_response.json()
            self.assertEqual(schema_payload["kind"], "schema")
            self.assertIn(
                "core_base_url",
                [item["key"] for item in schema_payload["ui_schema"]["config_fields"]],
            )

            async with session.get(f"{self.bridge_base_url}/desktop/config") as config_response:
                self.assertEqual(config_response.status, 200)
                config_payload = await config_response.json()
            self.assertFalse(config_payload["core_config_available"])
            self.assertEqual(config_payload["items"]["core_base_url"]["value"], "http://127.0.0.1:9")

            async with session.patch(
                f"{self.bridge_base_url}/desktop/config",
                json={
                    "updates": {
                        "core_base_url": "https://core.example.com",
                        "gateway_access_token": "gateway-secret",
                    }
                },
            ) as patch_response:
                self.assertEqual(patch_response.status, 200)
                patch_payload = await patch_response.json()
            self.assertEqual(patch_payload["applied_keys"], ["core_base_url", "gateway_access_token"])

            async with session.get(f"{self.bridge_base_url}/desktop/status") as status_response:
                self.assertEqual(status_response.status, 200)
                status_payload = await status_response.json()

        persisted = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(status_payload["core_base_url"], "https://core.example.com")
        self.assertEqual(persisted["core_base_url"], "https://core.example.com")
        self.assertEqual(persisted["gateway_access_token"], "gateway-secret")
