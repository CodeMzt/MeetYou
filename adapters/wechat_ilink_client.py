"""
WeChat iLink Bot HTTP client.

This module deliberately only wraps the official iLink transport surface. It
does not know anything about MeetYou sessions or Gateway routing.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

try:
    import aiohttp
except ImportError:  # pragma: no cover - requirements-core includes aiohttp
    aiohttp = None


DEFAULT_ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_CHANNEL_VERSION = "2.1.7"
DEFAULT_ILINK_APP_ID = "bot"
SESSION_EXPIRED_ERRCODE = -14


class WeChatIlinkError(RuntimeError):
    pass


class WeChatIlinkSessionExpired(WeChatIlinkError):
    pass


@dataclass(slots=True)
class WeChatIlinkCredentials:
    bot_token: str
    ilink_bot_id: str = ""
    ilink_user_id: str = ""
    baseurl: str = DEFAULT_ILINK_BASE_URL

    @property
    def account_id(self) -> str:
        return self.ilink_bot_id or self.ilink_user_id or "default"

    def to_json(self) -> dict[str, str]:
        return {
            "bot_token": self.bot_token,
            "ilink_bot_id": self.ilink_bot_id,
            "ilink_user_id": self.ilink_user_id,
            "baseurl": self.baseurl or DEFAULT_ILINK_BASE_URL,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any] | None) -> "WeChatIlinkCredentials | None":
        if not isinstance(payload, dict):
            return None
        token = str(
            payload.get("bot_token")
            or payload.get("token")
            or payload.get("access_token")
            or ""
        ).strip()
        if not token:
            return None
        return cls(
            bot_token=token,
            ilink_bot_id=str(payload.get("ilink_bot_id") or payload.get("bot_id") or "").strip(),
            ilink_user_id=str(payload.get("ilink_user_id") or payload.get("user_id") or "").strip(),
            baseurl=str(payload.get("baseurl") or payload.get("base_url") or DEFAULT_ILINK_BASE_URL).strip()
            or DEFAULT_ILINK_BASE_URL,
        )


@dataclass(slots=True)
class WeChatQRCodeInfo:
    qrcode: str
    qrcode_url: str = ""
    qrcode_data: str = ""
    status: str = ""
    raw: dict[str, Any] | None = None


def build_wechat_uin_header() -> str:
    number = int.from_bytes(os.urandom(4), byteorder="big", signed=False)
    return base64.b64encode(str(number).encode("ascii")).decode("ascii")


def _without_ilink_prefix(path: str) -> str:
    prefix = "/ilink/bot"
    if path == prefix:
        return ""
    if path.startswith(f"{prefix}/"):
        return path[len(prefix):]
    return path


def build_ilink_url(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    base = str(base_url or DEFAULT_ILINK_BASE_URL).strip().rstrip("/")
    endpoint = path if path.startswith("/") else f"/{path}"
    if base.endswith("/ilink/bot"):
        endpoint = _without_ilink_prefix(endpoint)
    url = f"{base}{endpoint}"
    if params:
        query = urlencode({key: value for key, value in params.items() if value is not None})
        if query:
            url = f"{url}?{query}"
    return url


def build_ilink_client_version(channel_version: str) -> int:
    parts = str(channel_version or "").split(".")
    numbers: list[int] = []
    for part in parts[:3]:
        try:
            numbers.append(max(int(part), 0))
        except ValueError:
            numbers.append(0)
    while len(numbers) < 3:
        numbers.append(0)
    major, minor, patch = numbers
    return ((major & 0xFF) << 16) | ((minor & 0xFF) << 8) | (patch & 0xFF)


def build_ilink_common_headers(
    *,
    app_id: str = DEFAULT_ILINK_APP_ID,
    app_client_version: int | None = None,
    channel_version: str = DEFAULT_CHANNEL_VERSION,
) -> dict[str, str]:
    return {
        "iLink-App-Id": str(app_id or DEFAULT_ILINK_APP_ID),
        "iLink-App-ClientVersion": str(
            app_client_version
            if app_client_version is not None
            else build_ilink_client_version(channel_version)
        ),
    }


def build_ilink_headers(
    bot_token: str,
    *,
    app_id: str = DEFAULT_ILINK_APP_ID,
    app_client_version: int | None = None,
    channel_version: str = DEFAULT_CHANNEL_VERSION,
) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {bot_token}",
        "X-WECHAT-UIN": build_wechat_uin_header(),
        **build_ilink_common_headers(
            app_id=app_id,
            app_client_version=app_client_version,
            channel_version=channel_version,
        ),
    }


def with_base_info(payload: dict[str, Any], channel_version: str) -> dict[str, Any]:
    body = dict(payload)
    body.setdefault("base_info", {"channel_version": channel_version or DEFAULT_CHANNEL_VERSION})
    return body


def _payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _is_session_expired(payload: dict[str, Any]) -> bool:
    for key in ("errcode", "ret", "code"):
        try:
            if int(payload.get(key)) == SESSION_EXPIRED_ERRCODE:
                return True
        except (TypeError, ValueError):
            continue
    data = payload.get("data")
    return isinstance(data, dict) and _is_session_expired(data)


class WeChatIlinkClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_ILINK_BASE_URL,
        channel_version: str = DEFAULT_CHANNEL_VERSION,
        app_id: str = DEFAULT_ILINK_APP_ID,
        app_client_version: int | None = None,
        session: Any | None = None,
    ):
        self.base_url = str(base_url or DEFAULT_ILINK_BASE_URL).strip() or DEFAULT_ILINK_BASE_URL
        self.channel_version = str(channel_version or DEFAULT_CHANNEL_VERSION).strip() or DEFAULT_CHANNEL_VERSION
        self.app_id = str(app_id or DEFAULT_ILINK_APP_ID).strip() or DEFAULT_ILINK_APP_ID
        self.app_client_version = (
            int(app_client_version)
            if app_client_version is not None
            else build_ilink_client_version(self.channel_version)
        )
        self._session = session
        self._owns_session = False

    async def init(self) -> None:
        if self._session is None:
            if aiohttp is None:
                raise WeChatIlinkError("缺少 aiohttp 依赖，无法启动 WeChat iLink Bot")
            self._session = aiohttp.ClientSession()
            self._owns_session = True

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
        self._session = None
        self._owns_session = False

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        await self.init()
        assert self._session is not None
        request_kwargs: dict[str, Any] = {}
        if headers is not None:
            request_kwargs["headers"] = headers
        if json_body is not None:
            request_kwargs["json"] = json_body
        if timeout_ms is not None and aiohttp is not None:
            request_kwargs["timeout"] = aiohttp.ClientTimeout(total=max(timeout_ms / 1000, 1))
        async with self._session.request(method, url, **request_kwargs) as response:
            try:
                raw_text = await response.text()
                payload = json.loads(raw_text)
            except Exception as exc:
                raise WeChatIlinkError(f"iLink response is not JSON: {response.status}") from exc
            if response.status >= 400:
                raise WeChatIlinkError(f"iLink HTTP {response.status}")
            if not isinstance(payload, dict):
                raise WeChatIlinkError("iLink response payload must be a JSON object")
            if _is_session_expired(payload):
                raise WeChatIlinkSessionExpired("WeChat iLink session expired")
            return payload

    async def get_bot_qrcode(self, *, bot_type: int = 3) -> WeChatQRCodeInfo:
        url = build_ilink_url(self.base_url, "/ilink/bot/get_bot_qrcode", {"bot_type": bot_type})
        payload = await self._request_json(
            "GET",
            url,
            headers=build_ilink_common_headers(
                app_id=self.app_id,
                app_client_version=self.app_client_version,
                channel_version=self.channel_version,
            ),
        )
        data = _payload_data(payload)
        qrcode = str(data.get("qrcode") or data.get("qr_code") or data.get("ticket") or "").strip()
        qrcode_url = str(
            data.get("qrcode_img_content")
            or data.get("qrcode_url")
            or data.get("qr_code_url")
            or data.get("url")
            or ""
        ).strip()
        qrcode_data = str(data.get("qrcode_data") or data.get("qr_code_data") or data.get("image") or "").strip()
        if not qrcode and qrcode_url:
            qrcode = qrcode_url
        return WeChatQRCodeInfo(
            qrcode=qrcode,
            qrcode_url=qrcode_url,
            qrcode_data=qrcode_data,
            status=str(data.get("status") or "").strip(),
            raw=payload,
        )

    async def get_qrcode_status(
        self,
        qrcode: str,
        *,
        base_url: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        url = build_ilink_url(base_url or self.base_url, "/ilink/bot/get_qrcode_status", {"qrcode": qrcode})
        return await self._request_json(
            "GET",
            url,
            headers=build_ilink_common_headers(
                app_id=self.app_id,
                app_client_version=self.app_client_version,
                channel_version=self.channel_version,
            ),
            timeout_ms=timeout_ms,
        )

    async def get_updates(
        self,
        credentials: WeChatIlinkCredentials,
        *,
        get_updates_buf: str,
        timeout_ms: int,
    ) -> dict[str, Any]:
        url = build_ilink_url(credentials.baseurl or self.base_url, "/ilink/bot/getupdates")
        return await self._request_json(
            "POST",
            url,
            headers=build_ilink_headers(
                credentials.bot_token,
                app_id=self.app_id,
                app_client_version=self.app_client_version,
                channel_version=self.channel_version,
            ),
            json_body=with_base_info(
                {"get_updates_buf": str(get_updates_buf or "")},
                self.channel_version,
            ),
            timeout_ms=timeout_ms,
        )

    async def send_text(
        self,
        credentials: WeChatIlinkCredentials,
        *,
        to_user_id: str,
        context_token: str,
        text: str,
        client_id: str,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        url = build_ilink_url(credentials.baseurl or self.base_url, "/ilink/bot/sendmessage")
        body = build_send_text_payload(
            to_user_id=to_user_id,
            context_token=context_token,
            text=text,
            client_id=client_id,
            channel_version=self.channel_version,
        )
        return await self._request_json(
            "POST",
            url,
            headers=build_ilink_headers(
                credentials.bot_token,
                app_id=self.app_id,
                app_client_version=self.app_client_version,
                channel_version=self.channel_version,
            ),
            json_body=body,
            timeout_ms=timeout_ms,
        )


def build_send_text_payload(
    *,
    to_user_id: str,
    context_token: str,
    text: str,
    client_id: str,
    channel_version: str = DEFAULT_CHANNEL_VERSION,
) -> dict[str, Any]:
    return with_base_info(
        {
            "msg": {
                "to_user_id": to_user_id,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [
                    {
                        "type": 1,
                        "text_item": {"text": text},
                    }
                ],
            }
        },
        channel_version,
    )
