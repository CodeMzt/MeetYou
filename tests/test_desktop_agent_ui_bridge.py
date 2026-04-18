from __future__ import annotations

import socket
import unittest

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
        self.core_port = _unused_port()
        self.bridge_port = _unused_port()
        self.core_base_url = f"http://127.0.0.1:{self.core_port}"
        self.bridge_base_url = f"http://127.0.0.1:{self.bridge_port}"
        self.core_runner = web.AppRunner(self._build_core_app())
        await self.core_runner.setup()
        self.core_site = web.TCPSite(self.core_runner, host="127.0.0.1", port=self.core_port)
        await self.core_site.start()

        self.bridge = DesktopApiServer(
            DesktopAgentConfig(
                core_base_url=self.core_base_url,
                agent_access_token="agent-token",
                gateway_access_token="core-token",
                local_bridge_port=self.bridge_port,
                local_bridge_access_token="local-token",
            )
        )
        await self.bridge.start()

    async def asyncTearDown(self):
        await self.bridge.stop()
        await self.core_runner.cleanup()

    def _build_core_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/client/workspaces", self._handle_workspaces)
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
        return web.json_response({"status": "ready"})

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
