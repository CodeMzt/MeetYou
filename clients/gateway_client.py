from __future__ import annotations

import asyncio
import inspect
import json
import os
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

import aiohttp


_HTTP_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15, sock_connect=5, sock_read=15)
_HTTP_SESSION_TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=5)


class GatewayClientError(RuntimeError):
    pass


def resolve_core_base_url(config: Any) -> str:
    configured_url = str(os.environ.get("MEETYOU_CORE_BASE_URL") or "").strip()
    if not configured_url and config is not None:
        get_value = getattr(config, "get", None)
        if callable(get_value):
            configured_url = str(get_value("core_base_url") or "").strip()
    if configured_url:
        if configured_url.startswith(("http://", "https://")):
            return configured_url.rstrip("/")
        raise GatewayClientError("MEETYOU_CORE_BASE_URL/core_base_url must start with http:// or https://")

    get_value = getattr(config, "get", None)
    host_value = get_value("gateway_host") if callable(get_value) else ""
    host = str(host_value or "127.0.0.1").strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::", "::0"}:
        host = "127.0.0.1"
    port_value = get_value("gateway_port") if callable(get_value) else 8000
    port = int(port_value or 8000)
    return f"http://{host}:{port}"


class GatewayConversationClient:
    def __init__(
        self,
        *,
        base_url: str,
        provider_id: str,
        provider_type: str,
        display_name: str,
        workspace_id: str = "personal",
        access_token: str = "",
        thread_title: str = "",
        thread_id: str = "",
        endpoint_id: str = "",
        conversation_key: str = "",
        address_id: str = "",
        thread_strategy: str = "",
        endpoint_addresses: list[dict[str, Any]] | None = None,
        supports_markdown: bool = True,
        bind_thread: bool = True,
        event_handler: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.ws_base_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        self.provider_id = provider_id
        self.provider_type = provider_type
        self.display_name = display_name
        self.workspace_id = workspace_id
        self.thread_title = thread_title or display_name or provider_id
        self.access_token = str(access_token or "").strip()
        self._event_handler = event_handler
        self._endpoint_id_override = str(endpoint_id or "").strip()
        self._conversation_key = str(conversation_key or "").strip()
        self._address_id = str(address_id or "").strip()
        self._thread_strategy = str(thread_strategy or "").strip()
        self._endpoint_addresses = list(endpoint_addresses or [])
        self.supports_markdown = bool(supports_markdown)
        self._bind_thread = bool(bind_thread)

        self._http_session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ws_task: asyncio.Task | None = None
        self._closed = False
        self._context_lock = asyncio.Lock()
        self._ws_connected = asyncio.Event()
        self._subscription_acknowledged = asyncio.Event()

        self.thread_id = str(thread_id or "").strip()
        self._explicit_thread_id = self.thread_id
        self.session_id = ""

    def _thread_default_key(self) -> str:
        provider_type = str(self.provider_type or "external").strip() or "external"
        provider_id = str(self.provider_id or self.endpoint_id or "default").strip() or "default"
        return f"endpoint.{provider_type}.{provider_id}"

    def _resolved_thread_strategy(self) -> str:
        if self._thread_strategy:
            return self._thread_strategy
        if self._conversation_key:
            return "per_conversation"
        if self._address_id:
            return "per_address"
        if self._explicit_thread_id:
            return "explicit_thread"
        return "shared_endpoint"

    @property
    def endpoint_id(self) -> str:
        if self._endpoint_id_override:
            return self._endpoint_id_override
        return f"{self.provider_type}.{self.provider_id}.ui"

    def _build_endpoint_ws_url(self) -> str:
        query_items = {
            "thread_id": self.thread_id,
            "session_id": self.session_id,
            "endpoint_id": self.endpoint_id,
            "provider_id": self.provider_id,
            "workspace_id": self.workspace_id,
            "provider_type": self.provider_type,
            "display_name": self.display_name,
        }
        query_string = urlencode(
            {
                key: str(value)
                for key, value in query_items.items()
                if str(value or "").strip()
            }
        )
        return f"{self.ws_base_url}/endpoint/ws?{query_string}"

    def _auth_headers(self) -> dict[str, str]:
        if not self.access_token:
            return {}
        return {"Authorization": f"Bearer {self.access_token}"}

    async def _ensure_http_session(self) -> None:
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession(headers=self._auth_headers(), timeout=_HTTP_SESSION_TIMEOUT)

    async def request_json(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
        await self._ensure_http_session()
        assert self._http_session is not None
        async with self._http_session.request(
            method,
            f"{self.base_url}{path}",
            params=params,
            json=json_body,
            timeout=_HTTP_REQUEST_TIMEOUT,
        ) as response:
            payload = await response.json()
            if response.status >= 400:
                message = payload.get("error", {}).get("message") if isinstance(payload, dict) else str(payload)
                raise GatewayClientError(f"{response.status} {message}")
            return payload

    async def ensure_context(self) -> None:
        if not self._bind_thread:
            return
        if self.thread_id and self.session_id:
            return
        async with self._context_lock:
            if self.thread_id and self.session_id:
                return
            workspaces = await self.request_json("GET", "/runtime/workspaces")
            if not isinstance(workspaces, list) or not workspaces:
                raise GatewayClientError("No available workspaces")
            workspace = next((item for item in workspaces if item.get("workspace_id") == self.workspace_id), workspaces[0])
            self.workspace_id = str(workspace.get("workspace_id") or self.workspace_id)

            resolved = await self.request_json(
                "POST",
                "/runtime/endpoint-sessions/resolve",
                json_body={
                    "endpoint_id": self.endpoint_id,
                    "workspace_id": self.workspace_id,
                    "provider_type": self.provider_type,
                    "endpoint_type": self.provider_type,
                    "display_name": self.display_name,
                    "conversation_key": self._conversation_key or self._thread_default_key(),
                    "address_id": self._address_id,
                    "thread_strategy": self._resolved_thread_strategy(),
                    "title": self.thread_title,
                    "explicit_thread_id": self._explicit_thread_id,
                    "metadata": {
                        "provider_id": self.provider_id,
                        "provider_type": self.provider_type,
                    },
                },
            )
            if not isinstance(resolved, dict):
                raise GatewayClientError("Unexpected endpoint session resolution response")
            thread = resolved.get("thread") if isinstance(resolved.get("thread"), dict) else {}
            session = resolved.get("session") if isinstance(resolved.get("session"), dict) else {}
            self.thread_id = str(thread.get("thread_id") or session.get("thread_id") or self.thread_id)
            self.session_id = str(session.get("session_id") or "")

    async def start(self) -> None:
        await self.ensure_context()
        if self._ws_task is not None and not self._ws_task.done() and self._subscription_acknowledged.is_set():
            return
        if self._ws_task is None or self._ws_task.done():
            self._closed = False
            self._ws_task = asyncio.create_task(self._maintain_ws())
        await asyncio.wait_for(self._subscription_acknowledged.wait(), timeout=15)

    async def _maintain_ws(self) -> None:
        while not self._closed:
            try:
                await self._connect_ws()
                await self._read_ws()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._ws_connected.clear()
                if self._closed:
                    break
                await asyncio.sleep(2)

    async def _connect_ws(self) -> None:
        await self.ensure_context()
        await self._ensure_http_session()
        assert self._http_session is not None
        self._ws = await self._http_session.ws_connect(
            self._build_endpoint_ws_url(),
            headers=self._auth_headers(),
        )
        self._ws_connected.clear()
        self._subscription_acknowledged.clear()
        await self._ws.send_json(
            {
                "schema": "meetyou.endpoint.ws.v4",
                "type": "endpoint.hello",
                "endpoint_id": self.endpoint_id,
                "payload": {
                    "provider": {
                        "provider_type": self.provider_type,
                        "provider_id": self.provider_id,
                        "display_name": self.display_name,
                        "transport_profile": "ui_ws",
                        "supports_markdown": self.supports_markdown,
                    },
                    "endpoints": [
                        {
                            "endpoint_id": self.endpoint_id,
                            "endpoint_type": f"{self.provider_type}_ui",
                            "roles": ["input", "output"],
                            "workspace_ids": [self.workspace_id],
                            "supports_markdown": self.supports_markdown,
                        }
                    ],
                    "supports_markdown": self.supports_markdown,
                },
            }
        )
        if self._endpoint_addresses:
            await self._ws.send_json(
                {
                    "schema": "meetyou.endpoint.ws.v4",
                    "type": "endpoint.addresses.snapshot",
                    "endpoint_id": self.endpoint_id,
                    "payload": {
                        "endpoint_id": self.endpoint_id,
                        "addresses": list(self._endpoint_addresses),
                    },
                }
            )
        if self._bind_thread:
            await self._ws.send_json(
                {
                    "schema": "meetyou.endpoint.ws.v4",
                    "type": "subscription.start",
                    "endpoint_id": self.endpoint_id,
                    "payload": {
                        "subscription_id": f"sub-{self.thread_id}",
                        "target_type": "thread",
                        "target_id": self.thread_id,
                        "last_seen_event_seq": 0,
                        "replay": False,
                    },
                }
            )

    async def upsert_address(self, address: dict[str, Any]) -> None:
        await self.start()
        if self._ws is None or self._ws.closed:
            raise GatewayClientError("Endpoint websocket is not connected")
        payload = dict(address or {})
        payload["endpoint_id"] = self.endpoint_id
        await self._ws.send_json(
            {
                "schema": "meetyou.endpoint.ws.v4",
                "type": "endpoint.address.upsert",
                "endpoint_id": self.endpoint_id,
                "payload": {"endpoint_id": self.endpoint_id, "address": payload},
            }
        )

    async def _read_ws(self) -> None:
        if self._ws is None:
            return
        async for message in self._ws:
            if message.type == aiohttp.WSMsgType.TEXT:
                payload = message.json(loads=json.loads)
                if payload.get("type") == "endpoint.hello.ack" and not self._bind_thread:
                    self._subscription_acknowledged.set()
                    self._ws_connected.set()
                if payload.get("type") == "subscription.ack":
                    self._subscription_acknowledged.set()
                    self._ws_connected.set()
                await self._dispatch_event(payload)
            elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                break

    async def _dispatch_event(self, payload: dict[str, Any]) -> None:
        if self._event_handler is None:
            return
        result = self._event_handler(payload)
        if inspect.isawaitable(result):
            await result

    async def send_message(
        self,
        content: str,
        *,
        role: str = "user",
        metadata: dict[str, Any] | None = None,
        preferred_mode: str | None = None,
        options: dict[str, Any] | None = None,
        endpoint_message_id: str | None = None,
    ) -> dict[str, Any]:
        await self.start()
        payload = await self.request_json(
            "POST",
            "/runtime/messages",
            json_body={
                "thread_id": self.thread_id,
                "workspace_id": self.workspace_id,
                "endpoint_id": self.endpoint_id,
                "session_id": self.session_id,
                "endpoint_type": self.provider_type,
                "display_name": self.display_name,
                "role": role,
                "content": content,
                "metadata": dict(metadata or {}),
                "preferred_mode": preferred_mode,
                "options": dict(options or {}),
                "endpoint_message_id": endpoint_message_id,
            },
        )
        return dict(payload)

    async def send_command(self, action: str, **payload: Any) -> None:
        await self.start()
        if self._ws is None or self._ws.closed:
            raise GatewayClientError("Endpoint websocket is not connected")
        await self._ws.send_json(
            {
                "schema": "meetyou.endpoint.ws.v4",
                "type": "runtime.command",
                "endpoint_id": self.endpoint_id,
                "action": action,
                "session_id": self.session_id,
                **payload,
            }
        )

    async def submit_confirm_response(
        self,
        *,
        request_id: str,
        accepted: bool,
        reason: str = "",
    ) -> dict[str, Any]:
        await self.ensure_context()
        payload = await self.request_json(
            "POST",
            f"/runtime/sessions/{self.session_id}/confirm-response",
            json_body={
                "request_id": request_id,
                "accepted": accepted,
                "reason": reason,
                "endpoint_id": self.endpoint_id,
            },
        )
        return dict(payload)

    async def submit_human_input_response(
        self,
        *,
        request_id: str,
        answer_text: str,
        selected_option: str | None = None,
    ) -> dict[str, Any]:
        await self.ensure_context()
        payload = await self.request_json(
            "POST",
            f"/runtime/sessions/{self.session_id}/human-input-response",
            json_body={
                "request_id": request_id,
                "answer_text": answer_text,
                "selected_option": selected_option,
                "endpoint_id": self.endpoint_id,
            },
        )
        return dict(payload)

    async def close(self) -> None:
        self._closed = True
        self._ws_connected.clear()
        if self._ws_task is not None:
            self._ws_task.cancel()
            with __import__("contextlib").suppress(asyncio.CancelledError):
                await self._ws_task
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._http_session is not None:
            await self._http_session.close()
        self._ws = None
        self._http_session = None
