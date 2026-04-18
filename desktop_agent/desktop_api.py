from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from typing import Callable

import aiohttp
from aiohttp import web

from desktop_agent.config import DesktopAgentConfig
from desktop_agent.core_client import DesktopCoreClient, rewrite_attachment_ticket, rewrite_download_ticket


logger = logging.getLogger("meetyou.desktop_agent.desktop_api")

LOCAL_BRIDGE_STATUS_PATH = "/desktop/status"
LEGACY_LOCAL_BRIDGE_STATUS_PATH = "/desktop/bridge/status"
DESKTOP_WS_PATH = "/desktop/ws"
_HTTP_ERROR_SCHEMA = "meetyou.http.v1"


@dataclass(frozen=True, slots=True)
class DesktopApiRoute:
    method: str
    desktop_path: str
    core_path_builder: Callable[[web.Request], str]
    rewrite_json: Callable[[object, DesktopAgentConfig], object] | None = None
    binary_response: bool = False


def _build_error_response(
    *,
    status: int,
    code: str,
    message: str,
    category: str = "runtime",
    retryable: bool = False,
) -> web.Response:
    return web.json_response(
        {
            "schema": _HTTP_ERROR_SCHEMA,
            "kind": "error",
            "error": {
                "code": code,
                "category": category,
                "message": message,
                "retryable": retryable,
                "details": {},
                "occurred_at": "",
            },
        },
        status=status,
    )


def extract_local_access_token(request: web.Request) -> str:
    auth_header = str(request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return str(request.query.get("access_token") or "").strip()


@web.middleware
async def _cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-API-Key"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Expose-Headers"] = "Content-Type, Content-Disposition"
    return response


def _desktop_routes() -> list[DesktopApiRoute]:
    return [
        DesktopApiRoute("GET", "/desktop/health", lambda _request: "/health"),
        DesktopApiRoute("GET", "/desktop/workspaces", lambda _request: "/client/workspaces"),
        DesktopApiRoute("GET", "/desktop/workspaces/{workspace_id}/agents", lambda request: f"/client/workspaces/{request.match_info['workspace_id']}/agents"),
        DesktopApiRoute("POST", "/desktop/threads", lambda _request: "/client/threads"),
        DesktopApiRoute("POST", "/desktop/sessions", lambda _request: "/client/sessions"),
        DesktopApiRoute("POST", "/desktop/messages", lambda _request: "/client/messages"),
        DesktopApiRoute("GET", "/desktop/threads/{thread_id}/messages", lambda request: f"/client/threads/{request.match_info['thread_id']}/messages"),
        DesktopApiRoute("POST", "/desktop/operations", lambda _request: "/client/operations"),
        DesktopApiRoute("GET", "/desktop/procedures", lambda _request: "/client/procedures"),
        DesktopApiRoute("GET", "/desktop/procedures/{procedure_id}", lambda request: f"/client/procedures/{request.match_info['procedure_id']}"),
        DesktopApiRoute("GET", "/desktop/threads/{thread_id}/procedure-context", lambda request: f"/client/threads/{request.match_info['thread_id']}/procedure-context"),
        DesktopApiRoute("PUT", "/desktop/threads/{thread_id}/pinned-procedure", lambda request: f"/client/threads/{request.match_info['thread_id']}/pinned-procedure"),
        DesktopApiRoute("DELETE", "/desktop/threads/{thread_id}/pinned-procedure", lambda request: f"/client/threads/{request.match_info['thread_id']}/pinned-procedure"),
        DesktopApiRoute("POST", "/desktop/approvals/{approval_id}/decision", lambda request: f"/client/approvals/{request.match_info['approval_id']}/decision"),
        DesktopApiRoute("POST", "/desktop/sessions/{session_id}/confirm-response", lambda request: f"/client/sessions/{request.match_info['session_id']}/confirm-response"),
        DesktopApiRoute("POST", "/desktop/sessions/{session_id}/human-input-response", lambda request: f"/client/sessions/{request.match_info['session_id']}/human-input-response"),
        DesktopApiRoute("POST", "/desktop/attachments/upload-ticket", lambda _request: "/client/attachments/upload-ticket", rewrite_json=rewrite_attachment_ticket),
        DesktopApiRoute("PUT", "/desktop/attachments/upload/{ticket_id}", lambda request: f"/client/attachments/upload/{request.match_info['ticket_id']}", binary_response=True),
        DesktopApiRoute("POST", "/desktop/attachments/{attachment_id}/complete", lambda request: f"/client/attachments/{request.match_info['attachment_id']}/complete"),
        DesktopApiRoute("GET", "/desktop/threads/{thread_id}/attachments", lambda request: f"/client/threads/{request.match_info['thread_id']}/attachments"),
        DesktopApiRoute("DELETE", "/desktop/attachments/{attachment_id}", lambda request: f"/client/attachments/{request.match_info['attachment_id']}"),
        DesktopApiRoute("GET", "/desktop/attachments/{attachment_id}/download-ticket", lambda request: f"/client/attachments/{request.match_info['attachment_id']}/download-ticket", rewrite_json=rewrite_download_ticket),
        DesktopApiRoute("GET", "/desktop/attachments/content/{attachment_id}", lambda request: f"/client/attachments/content/{request.match_info['attachment_id']}", binary_response=True),
        DesktopApiRoute("GET", "/desktop/danxi/session", lambda _request: "/client/danxi/session"),
        DesktopApiRoute("POST", "/desktop/danxi/session/login", lambda _request: "/client/danxi/session/login"),
        DesktopApiRoute("PATCH", "/desktop/danxi/session/webvpn-cookie", lambda _request: "/client/danxi/session/webvpn-cookie"),
        DesktopApiRoute("GET", "/desktop/danxi/profile", lambda _request: "/client/danxi/profile"),
        DesktopApiRoute("GET", "/desktop/danxi/divisions", lambda _request: "/client/danxi/divisions"),
        DesktopApiRoute("GET", "/desktop/danxi/posts", lambda _request: "/client/danxi/posts"),
        DesktopApiRoute("GET", "/desktop/danxi/posts/{hole_id}", lambda request: f"/client/danxi/posts/{request.match_info['hole_id']}"),
        DesktopApiRoute("GET", "/desktop/danxi/posts/{hole_id}/floors", lambda request: f"/client/danxi/posts/{request.match_info['hole_id']}/floors"),
        DesktopApiRoute("POST", "/desktop/danxi/posts/{hole_id}/replies", lambda request: f"/client/danxi/posts/{request.match_info['hole_id']}/replies"),
        DesktopApiRoute("PATCH", "/desktop/danxi/floors/{floor_id}", lambda request: f"/client/danxi/floors/{request.match_info['floor_id']}"),
        DesktopApiRoute("DELETE", "/desktop/danxi/floors/{floor_id}", lambda request: f"/client/danxi/floors/{request.match_info['floor_id']}"),
        DesktopApiRoute("GET", "/desktop/danxi/posts/{hole_id}/summary", lambda request: f"/client/danxi/posts/{request.match_info['hole_id']}/summary"),
        DesktopApiRoute("GET", "/desktop/danxi/search", lambda _request: "/client/danxi/search"),
        DesktopApiRoute("GET", "/desktop/danxi/messages", lambda _request: "/client/danxi/messages"),
        DesktopApiRoute("GET", "/desktop/config/schema", lambda _request: "/operator/schema/ui"),
        DesktopApiRoute("GET", "/desktop/config", lambda _request: "/operator/config"),
        DesktopApiRoute("PATCH", "/desktop/config", lambda _request: "/operator/config"),
        DesktopApiRoute("GET", "/desktop/memory", lambda _request: "/operator/memory"),
        DesktopApiRoute("GET", "/desktop/memory/graph", lambda _request: "/operator/memory/graph"),
        DesktopApiRoute("PATCH", "/desktop/workspaces/{workspace_id}", lambda request: f"/operator/workspaces/{request.match_info['workspace_id']}"),
        DesktopApiRoute("GET", "/desktop/source-profiles", lambda _request: "/operator/source-profiles"),
        DesktopApiRoute("GET", "/desktop/runtime/usage", lambda _request: "/runtime/usage"),
        DesktopApiRoute("GET", "/desktop/runtime/debug", lambda _request: "/developer/runtime/debug"),
    ]


class DesktopApiServer:
    def __init__(self, config: DesktopAgentConfig):
        self._config = config
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._core_client = DesktopCoreClient(config)

    async def start(self) -> None:
        if self._runner is not None:
            return
        await self._core_client.start()
        app = web.Application(client_max_size=1024**3, middlewares=[_cors_middleware])
        routes = [
            web.get(LOCAL_BRIDGE_STATUS_PATH, self._handle_status),
            web.get(LEGACY_LOCAL_BRIDGE_STATUS_PATH, self._handle_status),
            web.get(DESKTOP_WS_PATH, self._handle_client_ws),
        ]
        for route in _desktop_routes():
            routes.append(web.route(route.method, route.desktop_path, self._build_route_handler(route)))
        app.add_routes(routes)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self._config.local_bridge_host, port=self._config.local_bridge_port)
        await self._site.start()
        logger.info("Desktop backend listening on %s", self._config.local_bridge_base_url)

    async def stop(self) -> None:
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        await self._core_client.stop()

    def _build_route_handler(self, route: DesktopApiRoute):
        async def handler(request: web.Request) -> web.Response:
            if route.binary_response:
                return await self._forward_binary(request, route=route)
            return await self._forward_json(request, route=route)

        return handler

    def _check_local_auth(self, request: web.Request) -> web.Response | None:
        expected = str(self._config.local_bridge_access_token or "").strip()
        if not expected or request.path in {LOCAL_BRIDGE_STATUS_PATH, LEGACY_LOCAL_BRIDGE_STATUS_PATH}:
            return None
        provided = extract_local_access_token(request)
        if provided == expected:
            return None
        return _build_error_response(
            status=401,
            code="desktop_backend_auth_required",
            category="authorization",
            message="本地桌面后端鉴权失败。",
        )

    async def _handle_status(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ready",
                "local_bridge_base_url": self._config.local_bridge_base_url,
                "core_base_url": self._config.core_base_url,
                "local_bridge_enabled": self._config.local_bridge_enabled,
                "api_prefix": "/desktop",
                "ws_path": DESKTOP_WS_PATH,
            }
        )

    async def _forward_json(self, request: web.Request, *, route: DesktopApiRoute) -> web.Response:
        auth_error = self._check_local_auth(request)
        if auth_error is not None:
            return auth_error
        try:
            response = await self._core_client.request(request, method=route.method, core_path=route.core_path_builder(request))
            payload = response.body
            content_type = str(response.headers.get("Content-Type") or "")
            if content_type.lower().startswith("application/json") and payload and route.rewrite_json is not None:
                parsed = json.loads(payload.decode("utf-8"))
                payload = json.dumps(route.rewrite_json(parsed, self._config), ensure_ascii=False).encode("utf-8")
            return web.Response(status=response.status, body=payload, headers=response.headers)
        except Exception as exc:
            logger.exception("Desktop backend request failed: %s", exc)
            return _build_error_response(
                status=502,
                code="desktop_backend_upstream_failed",
                category="dependency",
                message="本地桌面后端无法连接 Core Service。",
                retryable=True,
            )

    async def _forward_binary(self, request: web.Request, *, route: DesktopApiRoute) -> web.Response:
        auth_error = self._check_local_auth(request)
        if auth_error is not None:
            return auth_error
        try:
            response = await self._core_client.request(request, method=route.method, core_path=route.core_path_builder(request))
            return web.Response(status=response.status, body=response.body, headers=response.headers)
        except Exception as exc:
            logger.exception("Desktop backend binary request failed: %s", exc)
            return _build_error_response(
                status=502,
                code="desktop_backend_upstream_failed",
                category="dependency",
                message="本地桌面后端无法连接 Core Service。",
                retryable=True,
            )

    async def _handle_client_ws(self, request: web.Request) -> web.StreamResponse:
        auth_error = self._check_local_auth(request)
        if auth_error is not None:
            return auth_error
        try:
            upstream_ws = await self._core_client.connect_client_ws(
                request,
                local_access_token=str(self._config.local_bridge_access_token or "").strip(),
            )
        except Exception as exc:
            logger.exception("Desktop backend websocket connect failed: %s", exc)
            return _build_error_response(
                status=502,
                code="desktop_backend_ws_connect_failed",
                category="dependency",
                message="本地桌面后端无法建立实时连接。",
                retryable=True,
            )

        client_ws = web.WebSocketResponse(autoping=True)
        await client_ws.prepare(request)

        async def _client_to_upstream() -> None:
            async for message in client_ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    await upstream_ws.send_str(message.data)
                elif message.type == aiohttp.WSMsgType.BINARY:
                    await upstream_ws.send_bytes(message.data)
                elif message.type == aiohttp.WSMsgType.CLOSE:
                    await upstream_ws.close()
                    return

        async def _upstream_to_client() -> None:
            async for message in upstream_ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    await client_ws.send_str(message.data)
                elif message.type == aiohttp.WSMsgType.BINARY:
                    await client_ws.send_bytes(message.data)
                elif message.type == aiohttp.WSMsgType.CLOSE:
                    await client_ws.close(code=upstream_ws.close_code or 1000)
                    return
                elif message.type == aiohttp.WSMsgType.ERROR:
                    await client_ws.close(code=1011)
                    return

        tasks = {
            asyncio.create_task(_client_to_upstream()),
            asyncio.create_task(_upstream_to_client()),
        }
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in pending:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            for task in done:
                task.result()
        finally:
            await upstream_ws.close()
            await client_ws.close()
        return client_ws


DesktopUiBridge = DesktopApiServer
