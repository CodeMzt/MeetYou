from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp
from aiohttp import web

from desktop_agent.config import DesktopAgentConfig


logger = logging.getLogger("meetyou.desktop_agent.ui_bridge")

LOCAL_BRIDGE_STATUS_PATH = "/desktop/bridge/status"
_HTTP_ERROR_SCHEMA = "meetyou.http.v1"
_HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


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


def _filter_request_headers(headers: aiohttp.typedefs.LooseHeaders) -> dict[str, str]:
    filtered: dict[str, str] = {}
    for key, value in dict(headers).items():
        name = str(key).strip()
        if not name or name.lower() in _HOP_BY_HOP_HEADERS:
            continue
        if name.lower() in {"authorization", "x-api-key", "host", "origin"}:
            continue
        filtered[name] = str(value)
    return filtered


def _filter_response_headers(headers: aiohttp.typedefs.LooseHeaders) -> dict[str, str]:
    filtered: dict[str, str] = {}
    for key, value in dict(headers).items():
        name = str(key).strip()
        if not name or name.lower() in _HOP_BY_HOP_HEADERS:
            continue
        if name.lower().startswith("access-control-"):
            continue
        filtered[name] = str(value)
    return filtered


def _build_core_auth_headers(token: str) -> dict[str, str]:
    resolved = str(token or "").strip()
    if not resolved:
        return {}
    return {"Authorization": f"Bearer {resolved}"}


def _extract_local_access_token(request: web.Request) -> str:
    auth_header = str(request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return str(request.query.get("access_token") or "").strip()


def _rewrite_url_to_local_bridge(url: str, config: DesktopAgentConfig) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.path.startswith("/client/attachments/"):
        local = urlsplit(config.local_bridge_base_url)
        return urlunsplit((local.scheme, local.netloc, parsed.path, parsed.query, parsed.fragment))
    if value.startswith("/client/attachments/"):
        local = urlsplit(config.local_bridge_base_url)
        return urlunsplit((local.scheme, local.netloc, value, "", ""))
    return value


def _rewrite_proxy_payload(path: str, payload: object, config: DesktopAgentConfig) -> object:
    if not isinstance(payload, dict):
        return payload
    if path == "/client/attachments/upload-ticket":
        next_payload = dict(payload)
        ticket_id = str(next_payload.get("ticket_id") or "").strip()
        if ticket_id:
            next_payload["upload_url"] = f"{config.local_bridge_base_url}/client/attachments/upload/{ticket_id}"
        return next_payload
    if path.startswith("/client/attachments/") and path.endswith("/download-ticket"):
        next_payload = dict(payload)
        next_payload["download_url"] = _rewrite_url_to_local_bridge(next_payload.get("download_url") or "", config)
        next_payload["fallback_download_url"] = _rewrite_url_to_local_bridge(
            next_payload.get("fallback_download_url") or "",
            config,
        )
        return next_payload
    return payload


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


class DesktopUiBridge:
    def __init__(self, config: DesktopAgentConfig):
        self._config = config
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._runner is not None:
            return
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=15))
        app = web.Application(client_max_size=1024**3, middlewares=[_cors_middleware])
        app.add_routes(
            [
                web.get(LOCAL_BRIDGE_STATUS_PATH, self._handle_status),
                web.get("/client/ws", self._handle_client_ws),
                web.route("*", "/{tail:.*}", self._handle_http_proxy),
            ]
        )
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self._config.local_bridge_host, port=self._config.local_bridge_port)
        await self._site.start()
        logger.info("Desktop UI bridge listening on %s", self._config.local_bridge_base_url)

    async def stop(self) -> None:
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _check_local_auth(self, request: web.Request) -> web.Response | None:
        expected = str(self._config.local_bridge_access_token or "").strip()
        if not expected or request.path == LOCAL_BRIDGE_STATUS_PATH:
            return None
        provided = _extract_local_access_token(request)
        if provided == expected:
            return None
        return _build_error_response(
            status=401,
            code="desktop_bridge_auth_required",
            category="authorization",
            message="本地桌面后端鉴权失败。",
        )

    def _build_core_http_url(self, request: web.Request) -> str:
        return f"{self._config.core_base_url.rstrip('/')}{request.rel_url.path_qs}"

    def _build_core_ws_url(self, request: web.Request) -> str:
        scheme = "wss" if self._config.core_base_url.startswith("https://") else "ws"
        base = self._config.core_base_url.rstrip("/")
        query_items = [
            (key, value)
            for key, value in parse_qsl(request.rel_url.query_string, keep_blank_values=True)
            if not (
                key == "access_token"
                and value == str(self._config.local_bridge_access_token or "").strip()
            )
        ]
        query_string = urlencode(query_items)
        path = request.path
        return f"{scheme}://{base.split('://', 1)[1]}{path}{('?' + query_string) if query_string else ''}"

    async def _handle_status(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ready",
                "local_bridge_base_url": self._config.local_bridge_base_url,
                "core_base_url": self._config.core_base_url,
                "local_bridge_enabled": self._config.local_bridge_enabled,
            }
        )

    async def _handle_http_proxy(self, request: web.Request) -> web.Response:
        auth_error = self._check_local_auth(request)
        if auth_error is not None:
            return auth_error
        if request.path.startswith("/desktop/bridge/"):
            return _build_error_response(status=404, code="desktop_bridge_path_not_found", message="未知桌面后端路径。")
        if self._session is None:
            return _build_error_response(status=503, code="desktop_bridge_unavailable", message="本地桌面后端尚未就绪。")
        target_url = self._build_core_http_url(request)
        headers = _filter_request_headers(request.headers)
        headers.update(_build_core_auth_headers(self._config.gateway_access_token))
        body = await request.read()
        try:
            async with self._session.request(
                request.method,
                target_url,
                headers=headers,
                data=body if body else None,
                allow_redirects=False,
            ) as response:
                response_headers = _filter_response_headers(response.headers)
                payload = await response.read()
                content_type = str(response.headers.get("Content-Type") or "")
                if content_type.lower().startswith("application/json") and payload:
                    parsed = json.loads(payload.decode("utf-8"))
                    rewritten = _rewrite_proxy_payload(request.path, parsed, self._config)
                    if rewritten is not parsed:
                        payload = json.dumps(rewritten, ensure_ascii=False).encode("utf-8")
                return web.Response(status=response.status, body=payload, headers=response_headers)
        except Exception as exc:
            logger.exception("Desktop UI bridge proxy failed: %s", exc)
            return _build_error_response(
                status=502,
                code="desktop_bridge_upstream_failed",
                category="dependency",
                message="本地桌面后端无法连接 Core Service。",
                retryable=True,
            )

    async def _handle_client_ws(self, request: web.Request) -> web.StreamResponse:
        auth_error = self._check_local_auth(request)
        if auth_error is not None:
            return auth_error
        if self._session is None:
            return _build_error_response(status=503, code="desktop_bridge_unavailable", message="本地桌面后端尚未就绪。")
        headers = _filter_request_headers(request.headers)
        headers.update(_build_core_auth_headers(self._config.gateway_access_token))
        try:
            upstream_ws = await self._session.ws_connect(self._build_core_ws_url(request), headers=headers)
        except Exception as exc:
            logger.exception("Desktop UI bridge websocket connect failed: %s", exc)
            return _build_error_response(
                status=502,
                code="desktop_bridge_ws_connect_failed",
                category="dependency",
                message="本地桌面后端无法建立客户端实时连接。",
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
