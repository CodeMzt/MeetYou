from __future__ import annotations

import aiohttp
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from desktop_client.config import DesktopClientConfig


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


@dataclass(slots=True)
class CoreHttpResult:
    status: int
    headers: dict[str, str]
    body: bytes


def filter_request_headers(headers: aiohttp.typedefs.LooseHeaders) -> dict[str, str]:
    filtered: dict[str, str] = {}
    for key, value in dict(headers).items():
        name = str(key).strip()
        if not name or name.lower() in _HOP_BY_HOP_HEADERS:
            continue
        if name.lower() in {"authorization", "x-api-key", "host", "origin"}:
            continue
        filtered[name] = str(value)
    return filtered


def filter_response_headers(headers: aiohttp.typedefs.LooseHeaders) -> dict[str, str]:
    filtered: dict[str, str] = {}
    for key, value in dict(headers).items():
        name = str(key).strip()
        if not name or name.lower() in _HOP_BY_HOP_HEADERS:
            continue
        if name.lower().startswith("access-control-"):
            continue
        filtered[name] = str(value)
    return filtered


def build_core_auth_headers(token: str) -> dict[str, str]:
    resolved = str(token or "").strip()
    if not resolved:
        return {}
    return {"Authorization": f"Bearer {resolved}"}


class DesktopCoreClient:
    def __init__(self, config: DesktopClientConfig):
        self._config = config
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is not None:
            return
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=15))

    async def stop(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _build_core_http_url(self, core_path: str, query_string: str = "") -> str:
        parsed = urlsplit(str(core_path or ""))
        query_items = parse_qsl(parsed.query, keep_blank_values=True)
        existing_keys = {key for key, _value in query_items}
        for key, value in parse_qsl(str(query_string or ""), keep_blank_values=True):
            if key in existing_keys:
                continue
            query_items.append((key, value))
        merged_path = urlunsplit(("", "", parsed.path, urlencode(query_items), parsed.fragment))
        suffix = merged_path or "/"
        return f"{self._config.core_base_url.rstrip('/')}{suffix}"

    def _build_core_ws_url(self, request, *, local_access_token: str) -> str:
        scheme = "wss" if self._config.core_base_url.startswith("https://") else "ws"
        base = self._config.core_base_url.rstrip("/")
        query_items = [
            (key, value)
            for key, value in parse_qsl(request.rel_url.query_string, keep_blank_values=True)
            if not (key == "access_token" and value == str(local_access_token or "").strip())
        ]
        query_string = urlencode(query_items)
        return f"{scheme}://{base.split('://', 1)[1]}/endpoint/ws{('?' + query_string) if query_string else ''}"

    def _build_core_request_headers(self, request) -> dict[str, str]:
        headers = filter_request_headers(request.headers)
        headers.update(build_core_auth_headers(self._config.gateway_access_token))
        return headers

    async def request(self, request, *, method: str, core_path: str) -> CoreHttpResult:
        if self._session is None:
            raise RuntimeError("desktop_backend_unavailable")
        body = await request.read()
        return await self.request_with_body(
            request,
            method=method,
            core_path=core_path,
            body=body if body else None,
            query_string=request.rel_url.query_string,
        )

    async def request_with_body(
        self,
        request,
        *,
        method: str,
        core_path: str,
        body: bytes | None = None,
        query_string: str = "",
    ) -> CoreHttpResult:
        if self._session is None:
            raise RuntimeError("desktop_backend_unavailable")
        response = await self._session.request(
            method,
            self._build_core_http_url(core_path, query_string),
            headers=self._build_core_request_headers(request),
            data=body if body else None,
            allow_redirects=False,
        )
        try:
            payload = await response.read()
            return CoreHttpResult(
                status=response.status,
                headers=filter_response_headers(response.headers),
                body=payload,
            )
        finally:
            response.release()

    async def connect_endpoint_ws(self, request, *, local_access_token: str) -> aiohttp.ClientWebSocketResponse:
        if self._session is None:
            raise RuntimeError("desktop_backend_unavailable")
        return await self._session.ws_connect(
            self._build_core_ws_url(request, local_access_token=local_access_token),
            headers=self._build_core_request_headers(request),
        )

    async def get_json(self, core_path: str, *, timeout_seconds: float | None = None) -> dict[str, object] | None:
        if self._session is None:
            raise RuntimeError("desktop_backend_unavailable")
        request_timeout = None
        if timeout_seconds is not None:
            request_timeout = aiohttp.ClientTimeout(
                total=max(0.1, float(timeout_seconds)),
                sock_connect=min(1.0, max(0.1, float(timeout_seconds))),
                sock_read=max(0.1, float(timeout_seconds)),
            )
        response = await self._session.get(
            self._build_core_http_url(core_path),
            headers=build_core_auth_headers(self._config.gateway_access_token),
            allow_redirects=False,
            timeout=request_timeout,
        )
        try:
            if response.status >= 400:
                return None
            payload = await response.json(content_type=None)
            if isinstance(payload, dict):
                return payload
            return None
        except Exception:
            return None
        finally:
            response.release()
