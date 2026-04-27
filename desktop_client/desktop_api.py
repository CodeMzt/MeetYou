from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import aiohttp
from aiohttp import web

from build_info import load_build_info
from desktop_client.config import DesktopClientConfig
from desktop_client.core_client import DesktopCoreClient, rewrite_attachment_ticket, rewrite_download_ticket


logger = logging.getLogger("meetyou.desktop_client.desktop_api")

LOCAL_BRIDGE_STATUS_PATH = "/desktop/status"
LEGACY_LOCAL_BRIDGE_STATUS_PATH = "/desktop/bridge/status"
DESKTOP_WS_PATH = "/desktop/ws"
_HTTP_ERROR_SCHEMA = "meetyou.http.v1"
_LOCAL_CONFIG_KEYS = {"core_base_url", "gateway_access_token", "core_access_token"}
_LOCAL_SECRET_KEYS = {"gateway_access_token", "core_access_token"}
_LOCAL_CONFIG_FIELDS = [
    {
        "key": "core_base_url",
        "title": "Desktop Core Service URL",
        "description": "HTTP base URL used by this desktop backend when it proxies UI requests to Core Service.",
        "group": "advanced",
        "input": "text",
        "placeholder": "https://core.example.com",
        "advanced": False,
    },
    {
        "key": "gateway_access_token",
        "title": "Desktop Gateway Access Token",
        "description": "Bearer token used by this desktop backend for Core HTTP and client WebSocket requests.",
        "group": "secrets",
        "input": "password",
        "advanced": False,
    },
    {
        "key": "core_access_token",
        "title": "Desktop Client Access Token",
        "description": "Bearer token used by the packaged desktop provider when it connects to Core /endpoint/ws.",
        "group": "secrets",
        "input": "password",
        "advanced": True,
    },
]
_LOCAL_SCHEMA_ENVELOPE = {
    "schema": _HTTP_ERROR_SCHEMA,
    "kind": "schema",
    "ui_schema": {
        "http_schema": _HTTP_ERROR_SCHEMA,
        "ws_schema": "meetyou.ws.v1",
        "ws_frame_kinds": [],
        "ws_event_types": [],
        "ws_runtime_resources": [],
        "runtime_statuses": [],
        "providers": [],
        "thinking_efforts": [],
        "config_groups": [
            {
                "key": "secrets",
                "title": "Secrets",
                "description": "Local credentials used by the desktop backend.",
            },
            {
                "key": "advanced",
                "title": "Desktop Runtime",
                "description": "Local desktop backend connection settings.",
            },
        ],
        "config_fields": _LOCAL_CONFIG_FIELDS,
    },
}


@dataclass(frozen=True, slots=True)
class DesktopApiRoute:
    method: str
    desktop_path: str
    core_path_builder: Callable[[web.Request], str]
    rewrite_json: Callable[[object, DesktopClientConfig], object] | None = None
    binary_response: bool = False
    starts_runtime: bool = False


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
        DesktopApiRoute("GET", "/desktop/workspaces/{workspace_id}/clients", lambda request: f"/client/workspaces/{request.match_info['workspace_id']}/clients?include_tools=true"),
        DesktopApiRoute("GET", "/desktop/context-pool/query", lambda _request: "/client/context-pool/query"),
        DesktopApiRoute("POST", "/desktop/threads", lambda _request: "/client/threads"),
        DesktopApiRoute("POST", "/desktop/sessions", lambda _request: "/client/sessions", starts_runtime=True),
        DesktopApiRoute("PATCH", "/desktop/sessions/{session_id}/active-workspace", lambda request: f"/client/sessions/{request.match_info['session_id']}/active-workspace"),
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
        DesktopApiRoute("GET", "/desktop/danxi/floors/{floor_id}/target", lambda request: f"/client/danxi/floors/{request.match_info['floor_id']}/target"),
        DesktopApiRoute("GET", "/desktop/memory", lambda _request: "/operator/memory"),
        DesktopApiRoute("GET", "/desktop/memory/graph", lambda _request: "/operator/memory/graph"),
        DesktopApiRoute("DELETE", "/desktop/memory", lambda _request: "/operator/memory"),
        DesktopApiRoute("PATCH", "/desktop/memory/records/{memory_id}", lambda request: f"/operator/memory/records/{request.match_info['memory_id']}"),
        DesktopApiRoute("DELETE", "/desktop/memory/records/{memory_id}", lambda request: f"/operator/memory/records/{request.match_info['memory_id']}"),
        DesktopApiRoute("PATCH", "/desktop/workspaces/{workspace_id}", lambda request: f"/operator/workspaces/{request.match_info['workspace_id']}"),
        DesktopApiRoute("GET", "/desktop/source-profiles", lambda _request: "/operator/source-profiles"),
        DesktopApiRoute("GET", "/desktop/runtime/usage", lambda _request: "/runtime/usage"),
        DesktopApiRoute("GET", "/desktop/runtime/debug", lambda _request: "/developer/runtime/debug"),
    ]


class DesktopApiServer:
    def __init__(
        self,
        config: DesktopClientConfig,
        *,
        on_client_session_created: Callable[[], Awaitable[None]] | None = None,
    ):
        self._config = config
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._core_client = DesktopCoreClient(config)
        self._build_info = load_build_info(
            Path(__file__).resolve().with_name("build_info.json"),
            component="desktop_backend",
            package_version="0.0.0",
        )
        self._on_client_session_created = on_client_session_created

    async def start(self) -> None:
        if self._runner is not None:
            return
        await self._core_client.start()
        app = web.Application(client_max_size=1024**3, middlewares=[_cors_middleware])
        routes = [
            web.get(LOCAL_BRIDGE_STATUS_PATH, self._handle_status),
            web.get(LEGACY_LOCAL_BRIDGE_STATUS_PATH, self._handle_status),
            web.get(DESKTOP_WS_PATH, self._handle_client_ws),
            web.get("/desktop/config/schema", self._handle_config_schema),
            web.get("/desktop/config", self._handle_config_get),
            web.patch("/desktop/config", self._handle_config_patch),
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
        core_build_info: dict[str, object] = {}
        try:
            health_payload = await self._core_client.get_json("/health", timeout_seconds=0.75)
            if isinstance(health_payload, dict):
                health_node = health_payload.get("health")
                if isinstance(health_node, dict) and isinstance(health_node.get("build_info"), dict):
                    core_build_info = dict(health_node.get("build_info") or {})
        except Exception:
            logger.debug("Failed to fetch core build info for desktop status", exc_info=True)
        return web.json_response(
            {
                "status": "ready",
                "local_bridge_base_url": self._config.local_bridge_base_url,
                "core_base_url": self._config.core_base_url,
                "local_bridge_enabled": self._config.local_bridge_enabled,
                "api_prefix": "/desktop",
                "ws_path": DESKTOP_WS_PATH,
                "build_info": self._build_info,
                "core_build_info": core_build_info,
            }
        )

    def _config_path(self) -> Path:
        return Path(self._config.config_file_path or "user/desktop_client.json").expanduser()

    def _read_config_file_payload(self) -> dict[str, object]:
        path = self._config_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            logger.warning("Failed to read desktop config file %s", path, exc_info=True)
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_config_file_payload(self, payload: dict[str, object]) -> None:
        path = self._config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n", encoding="utf-8")

    @staticmethod
    def _mask_secret(value: object) -> str:
        text = str(value or "")
        if not text:
            return ""
        if len(text) <= 8:
            return "********"
        return f"{text[:2]}******{text[-2:]}"

    def _local_config_items(self) -> dict[str, dict[str, object]]:
        values = {
            "core_base_url": self._config.core_base_url,
            "gateway_access_token": self._config.gateway_access_token,
            "core_access_token": self._config.core_access_token,
        }
        env_keys = {
            "gateway_access_token": "MEETYOU_GATEWAY_ACCESS_TOKEN",
            "core_access_token": "MEETYOU_CLIENT_ACCESS_TOKEN",
        }
        items: dict[str, dict[str, object]] = {}
        for key, value in values.items():
            secret = key in _LOCAL_SECRET_KEYS
            items[key] = {
                "key": key,
                "value": self._mask_secret(value) if secret else value,
                "raw_value": None if secret else value,
                "is_secret": secret,
                "has_value": bool(str(value or "").strip()),
                "source": "desktop_client",
                "env_key": env_keys.get(key),
            }
        return items

    @staticmethod
    def _merge_local_config_schema(payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            payload = {}
        merged = json.loads(json.dumps(_LOCAL_SCHEMA_ENVELOPE))
        core_schema = payload.get("ui_schema")
        if isinstance(core_schema, dict):
            merged = dict(payload)
            ui_schema = dict(core_schema)
            existing_groups = {
                str(item.get("key") or ""): item
                for item in ui_schema.get("config_groups", [])
                if isinstance(item, dict)
            }
            for group in _LOCAL_SCHEMA_ENVELOPE["ui_schema"]["config_groups"]:
                existing_groups.setdefault(str(group["key"]), group)
            existing_fields = {
                str(item.get("key") or ""): item
                for item in ui_schema.get("config_fields", [])
                if isinstance(item, dict)
            }
            for field in _LOCAL_CONFIG_FIELDS:
                existing_fields[str(field["key"])] = field
            ui_schema["config_groups"] = list(existing_groups.values())
            ui_schema["config_fields"] = list(existing_fields.values())
            merged["ui_schema"] = ui_schema
        return merged

    async def _handle_config_schema(self, request: web.Request) -> web.Response:
        auth_error = self._check_local_auth(request)
        if auth_error is not None:
            return auth_error
        try:
            response = await self._core_client.request(request, method="GET", core_path="/operator/schema/ui")
            if response.status < 400:
                payload = json.loads(response.body.decode("utf-8")) if response.body else {}
                return web.json_response(self._merge_local_config_schema(payload), status=200)
        except Exception:
            logger.info("Using local desktop config schema because Core schema is unavailable", exc_info=True)
        return web.json_response(_LOCAL_SCHEMA_ENVELOPE)

    async def _handle_config_get(self, request: web.Request) -> web.Response:
        auth_error = self._check_local_auth(request)
        if auth_error is not None:
            return auth_error
        items: dict[str, object] = {}
        core_config_available = False
        try:
            response = await self._core_client.request(request, method="GET", core_path="/operator/config")
            if response.status < 400:
                payload = json.loads(response.body.decode("utf-8")) if response.body else {}
                if isinstance(payload, dict) and isinstance(payload.get("items"), dict):
                    items.update(payload["items"])
                    core_config_available = True
        except Exception:
            logger.info("Using local desktop config because Core config is unavailable", exc_info=True)
        items.update(self._local_config_items())
        return web.json_response(
            {
                "items": items,
                "core_config_available": core_config_available,
                "desktop_config_path": str(self._config_path()),
            }
        )

    @staticmethod
    def _validate_local_config_update(key: str, value: object) -> object:
        if key == "core_base_url":
            normalized = str(value or "").strip().rstrip("/")
            if not normalized.startswith(("http://", "https://")):
                raise ValueError("core_base_url must start with http:// or https://")
            return normalized
        return str(value or "").strip()

    def _apply_local_config_updates(self, updates: dict[str, object]) -> list[str]:
        payload = self._read_config_file_payload()
        applied: list[str] = []
        for key, value in updates.items():
            normalized = self._validate_local_config_update(key, value)
            payload[key] = normalized
            setattr(self._config, key, normalized)
            applied.append(key)
        if applied:
            self._write_config_file_payload(payload)
        return applied

    async def _handle_config_patch(self, request: web.Request) -> web.Response:
        auth_error = self._check_local_auth(request)
        if auth_error is not None:
            return auth_error
        try:
            payload = await request.json()
            raw_updates = payload.get("updates") if isinstance(payload, dict) else None
            updates = raw_updates if isinstance(raw_updates, dict) else {}
            local_updates = {key: value for key, value in updates.items() if key in _LOCAL_CONFIG_KEYS}
            core_updates = {key: value for key, value in updates.items() if key not in _LOCAL_CONFIG_KEYS}
            applied = self._apply_local_config_updates(local_updates)
            reloaded_components = ["desktop_backend"] if applied else []
            restart_required_keys: list[str] = []
            warnings: list[str] = []
            if "core_access_token" in applied:
                warnings.append("The running client websocket will use the updated client token on its next reconnect.")
            if core_updates:
                body = json.dumps({"updates": core_updates}, ensure_ascii=False).encode("utf-8")
                response = await self._core_client.request_with_body(
                    request,
                    method="PATCH",
                    core_path="/operator/config",
                    body=body,
                )
                if response.status >= 400:
                    return web.Response(status=response.status, body=response.body, headers=response.headers)
                core_result = json.loads(response.body.decode("utf-8")) if response.body else {}
                applied.extend([str(item) for item in core_result.get("applied_keys", [])])
                reloaded_components.extend([str(item) for item in core_result.get("reloaded_components", [])])
                restart_required_keys.extend([str(item) for item in core_result.get("restart_required_keys", [])])
                warnings.extend([str(item) for item in core_result.get("warnings", [])])
            return web.json_response(
                {
                    "applied_keys": sorted(set(applied)),
                    "reloaded_components": sorted(set(reloaded_components)),
                    "restart_required_keys": sorted(set(restart_required_keys)),
                    "warnings": warnings,
                }
            )
        except (ValueError, json.JSONDecodeError) as exc:
            return _build_error_response(
                status=400,
                code="invalid_desktop_config_update",
                category="validation",
                message=str(exc),
            )
        except Exception as exc:
            logger.exception("Desktop config update failed: %s", exc)
            return _build_error_response(
                status=502,
                code="desktop_config_update_failed",
                category="dependency",
                message="Failed to update desktop or Core configuration.",
                retryable=True,
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
            if response.status < 400 and route.starts_runtime and self._on_client_session_created is not None:
                await self._on_client_session_created()
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
