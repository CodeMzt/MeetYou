from __future__ import annotations

import base64
import random
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urljoin

import aiohttp


DEFAULT_CLAWBOT_ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_CLAWBOT_ILINK_CHANNEL_VERSION = "2.0.0"
DEFAULT_CLAWBOT_ILINK_CLIENT_VERSION = "1"
DEFAULT_CLAWBOT_ILINK_REQUEST_TIMEOUT_MS = 15000
DEFAULT_CLAWBOT_ILINK_LONG_POLL_TIMEOUT_MS = 35000
DEFAULT_CLAWBOT_ILINK_QR_POLL_TIMEOUT_MS = 30000


class ClawBotError(RuntimeError):
    pass


class ClawBotHTTPError(ClawBotError):
    def __init__(self, status: int, message: str, payload: Any = None):
        super().__init__(f"{status} {message}".strip())
        self.status = int(status or 0)
        self.payload = payload


class ClawBotAPIError(ClawBotError):
    def __init__(self, ret: int, message: str, payload: Any = None):
        super().__init__(f"ret={ret} {message}".strip())
        self.ret = int(ret or 0)
        self.payload = payload


class ClawBotSessionExpired(ClawBotAPIError):
    pass


@dataclass(slots=True)
class ClawBotLoginQRCode:
    qrcode: str
    qrcode_img_content: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def display_url(self) -> str:
        return self.qrcode_img_content or self.qrcode


@dataclass(slots=True)
class ClawBotLoginStatus:
    status: str
    bot_token: str = ""
    base_url: str = ""
    ilink_bot_id: str = ""
    ilink_user_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ClawBotLoginStatus":
        raw = dict(payload or {})
        data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        status = str(
            raw.get("status")
            or raw.get("qrcode_status")
            or raw.get("state")
            or raw.get("code")
            or data.get("status")
            or data.get("qrcode_status")
            or data.get("state")
            or data.get("code")
            or ""
        ).strip()
        bot_token = str(data.get("bot_token") or data.get("token") or "").strip()
        if bot_token and not status:
            status = "confirmed"
        return cls(
            status=status,
            bot_token=bot_token,
            base_url=str(data.get("baseurl") or data.get("base_url") or data.get("baseUrl") or "").strip(),
            ilink_bot_id=str(data.get("ilink_bot_id") or data.get("bot_id") or "").strip(),
            ilink_user_id=str(data.get("ilink_user_id") or data.get("user_id") or "").strip(),
            raw=raw,
        )

    @property
    def confirmed(self) -> bool:
        return bool(self.bot_token) or self.status.lower() == "confirmed"

    @property
    def expired(self) -> bool:
        return self.status.lower() == "expired"


@dataclass(slots=True)
class ClawBotMessageItem:
    type: int = 0
    text: str = ""
    is_completed: bool = True
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ClawBotMessageItem":
        raw = dict(payload or {})
        text_item = raw.get("text_item") if isinstance(raw.get("text_item"), dict) else {}
        return cls(
            type=_safe_int(raw.get("type")),
            text=str(text_item.get("text") or ""),
            is_completed=bool(raw.get("is_completed", True)),
            raw=raw,
        )


@dataclass(slots=True)
class ClawBotMessage:
    seq: int = 0
    message_id: str = ""
    from_user_id: str = ""
    to_user_id: str = ""
    create_time_ms: int = 0
    session_id: str = ""
    group_id: str = ""
    message_type: int = 0
    message_state: int = 0
    context_token: str = ""
    items: list[ClawBotMessageItem] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ClawBotMessage":
        raw = dict(payload or {})
        item_payloads = raw.get("item_list") if isinstance(raw.get("item_list"), list) else []
        return cls(
            seq=_safe_int(raw.get("seq")),
            message_id=str(raw.get("message_id") or ""),
            from_user_id=str(raw.get("from_user_id") or ""),
            to_user_id=str(raw.get("to_user_id") or ""),
            create_time_ms=_safe_int(raw.get("create_time_ms")),
            session_id=str(raw.get("session_id") or ""),
            group_id=str(raw.get("group_id") or ""),
            message_type=_safe_int(raw.get("message_type")),
            message_state=_safe_int(raw.get("message_state")),
            context_token=str(raw.get("context_token") or ""),
            items=[ClawBotMessageItem.from_payload(item) for item in item_payloads if isinstance(item, dict)],
            raw=raw,
        )

    def text_content(self) -> str:
        fragments = [item.text for item in self.items if item.type == 1 and item.text]
        return "\n".join(fragment.strip() for fragment in fragments if fragment.strip()).strip()

    def is_complete_text(self) -> bool:
        if self.message_state not in {0, 2}:
            return False
        text_items = [item for item in self.items if item.type == 1]
        if not text_items:
            return False
        return all(item.is_completed for item in text_items)


@dataclass(slots=True)
class ClawBotGetUpdatesResult:
    ret: int
    errcode: int = 0
    errmsg: str = ""
    messages: list[ClawBotMessage] = field(default_factory=list)
    get_updates_buf: str = ""
    longpolling_timeout_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ClawBotGetUpdatesResult":
        raw = dict(payload or {})
        msg_payloads = raw.get("msgs") if isinstance(raw.get("msgs"), list) else []
        return cls(
            ret=_safe_int(raw.get("ret")),
            errcode=_safe_int(raw.get("errcode")),
            errmsg=str(raw.get("errmsg") or raw.get("message") or ""),
            messages=[ClawBotMessage.from_payload(item) for item in msg_payloads if isinstance(item, dict)],
            get_updates_buf=str(raw.get("get_updates_buf") or raw.get("sync_buf") or ""),
            longpolling_timeout_ms=_safe_int(raw.get("longpolling_timeout_ms")),
            raw=raw,
        )


@dataclass(slots=True)
class ClawBotSendResult:
    ok: bool
    raw: dict[str, Any] = field(default_factory=dict)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _random_wechat_uin_header() -> str:
    return base64.b64encode(str(random.getrandbits(32)).encode("utf-8")).decode("ascii")


class ClawBotClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_CLAWBOT_ILINK_BASE_URL,
        bot_token: str = "",
        bot_id: str = "",
        ilink_user_id: str = "",
        channel_version: str = DEFAULT_CLAWBOT_ILINK_CHANNEL_VERSION,
        ilink_app_client_version: str = DEFAULT_CLAWBOT_ILINK_CLIENT_VERSION,
        route_tag: str = "",
        request_timeout_ms: int = DEFAULT_CLAWBOT_ILINK_REQUEST_TIMEOUT_MS,
        long_poll_timeout_ms: int = DEFAULT_CLAWBOT_ILINK_LONG_POLL_TIMEOUT_MS,
        session: aiohttp.ClientSession | None = None,
    ):
        self.base_url = str(base_url or DEFAULT_CLAWBOT_ILINK_BASE_URL).strip().rstrip("/") or DEFAULT_CLAWBOT_ILINK_BASE_URL
        self.bot_token = str(bot_token or "").strip()
        self.bot_id = str(bot_id or "").strip()
        self.ilink_user_id = str(ilink_user_id or "").strip()
        self.channel_version = str(channel_version or DEFAULT_CLAWBOT_ILINK_CHANNEL_VERSION).strip()
        self.ilink_app_client_version = str(ilink_app_client_version or DEFAULT_CLAWBOT_ILINK_CLIENT_VERSION).strip()
        self.route_tag = str(route_tag or "").strip()
        self.request_timeout_ms = int(request_timeout_ms or DEFAULT_CLAWBOT_ILINK_REQUEST_TIMEOUT_MS)
        self.long_poll_timeout_ms = int(long_poll_timeout_ms or DEFAULT_CLAWBOT_ILINK_LONG_POLL_TIMEOUT_MS)
        self._session = session
        self._owns_session = session is None

    async def init(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=10))
            self._owns_session = True

    async def close(self) -> None:
        if self._session is not None and self._owns_session:
            await self._session.close()
        self._session = None

    def update_credentials(
        self,
        *,
        bot_token: str,
        base_url: str = "",
        bot_id: str = "",
        ilink_user_id: str = "",
    ) -> None:
        self.bot_token = str(bot_token or "").strip()
        if base_url:
            self.base_url = str(base_url or "").strip().rstrip("/")
        if bot_id:
            self.bot_id = str(bot_id or "").strip()
        if ilink_user_id:
            self.ilink_user_id = str(ilink_user_id or "").strip()

    def _url(self, endpoint: str, *, query: dict[str, Any] | None = None) -> str:
        url = urljoin(self.base_url.rstrip("/") + "/", endpoint.lstrip("/"))
        if query:
            url = f"{url}?{urlencode({key: str(value) for key, value in query.items() if str(value or '').strip()})}"
        return url

    def _base_info(self) -> dict[str, Any]:
        return {"channel_version": self.channel_version}

    def _common_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.route_tag:
            headers["SKRouteTag"] = self.route_tag
        if self.ilink_app_client_version:
            headers["iLink-App-ClientVersion"] = self.ilink_app_client_version
        return headers

    def _auth_headers(self) -> dict[str, str]:
        if not self.bot_token:
            raise ClawBotError("clawbot_ilink_bot_token is not configured; run `python -m endpoint_providers.clawbot login`")
        headers = self._common_headers()
        headers.update(
            {
                "AuthorizationType": "ilink_bot_token",
                "Authorization": f"Bearer {self.bot_token}",
                "X-WECHAT-UIN": _random_wechat_uin_header(),
            }
        )
        return headers

    async def _request_json(
        self,
        method: str,
        endpoint: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        auth: bool = False,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        await self.init()
        assert self._session is not None
        headers = self._auth_headers() if auth else self._common_headers()
        body = dict(json_body or {})
        if method.upper() == "POST":
            body["base_info"] = self._base_info()
        timeout = aiohttp.ClientTimeout(total=max(int(timeout_ms or self.request_timeout_ms), 1) / 1000)
        async with self._session.request(
            method.upper(),
            self._url(endpoint, query=query),
            headers=headers,
            json=body if method.upper() == "POST" else None,
            timeout=timeout,
        ) as response:
            try:
                payload: Any = await response.json(content_type=None)
            except TypeError:
                payload = await response.json()
            except Exception:
                payload = {"message": await response.text()}
            if response.status >= 400:
                message = ""
                if isinstance(payload, dict):
                    message = str(payload.get("errmsg") or payload.get("message") or "")
                raise ClawBotHTTPError(response.status, message or "ClawBot iLink HTTP error", payload)
            if not isinstance(payload, dict):
                payload = {"data": payload}
            self._raise_for_api_error(payload)
            return payload

    @staticmethod
    def _raise_for_api_error(payload: dict[str, Any]) -> None:
        ret = _safe_int(payload.get("ret"), 0)
        errcode = _safe_int(payload.get("errcode"), 0)
        if ret == -14 or errcode == -14:
            raise ClawBotSessionExpired(-14, str(payload.get("errmsg") or "ClawBot iLink session expired"), payload)
        if ret not in {0}:
            raise ClawBotAPIError(ret, str(payload.get("errmsg") or payload.get("message") or "ClawBot iLink API error"), payload)
        if errcode not in {0}:
            raise ClawBotAPIError(errcode, str(payload.get("errmsg") or payload.get("message") or "ClawBot iLink API error"), payload)

    async def get_bot_qrcode(self, *, bot_type: int = 3) -> ClawBotLoginQRCode:
        payload = await self._request_json(
            "GET",
            "ilink/bot/get_bot_qrcode",
            query={"bot_type": int(bot_type or 3)},
            auth=False,
            timeout_ms=self.request_timeout_ms,
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        return ClawBotLoginQRCode(
            qrcode=str(data.get("qrcode") or ""),
            qrcode_img_content=str(data.get("qrcode_img_content") or data.get("qrcode_url") or ""),
            raw=payload,
        )

    async def get_qrcode_status(self, qrcode: str, *, timeout_ms: int | None = None) -> ClawBotLoginStatus:
        payload = await self._request_json(
            "GET",
            "ilink/bot/get_qrcode_status",
            query={"qrcode": str(qrcode or "")},
            auth=False,
            timeout_ms=timeout_ms or DEFAULT_CLAWBOT_ILINK_QR_POLL_TIMEOUT_MS,
        )
        return ClawBotLoginStatus.from_payload(payload)

    async def get_updates(self, *, get_updates_buf: str = "", timeout_ms: int | None = None) -> ClawBotGetUpdatesResult:
        payload = await self._request_json(
            "POST",
            "ilink/bot/getupdates",
            json_body={"get_updates_buf": str(get_updates_buf or "")},
            auth=True,
            timeout_ms=timeout_ms or self.long_poll_timeout_ms,
        )
        return ClawBotGetUpdatesResult.from_payload(payload)

    async def send_text(
        self,
        *,
        to_user_id: str,
        context_token: str,
        text: str,
        timeout_ms: int | None = None,
    ) -> ClawBotSendResult:
        payload = await self._request_json(
            "POST",
            "ilink/bot/sendmessage",
            json_body={
                "msg": {
                    "from_user_id": "",
                    "client_id": f"meetyou:{uuid.uuid4()}",
                    "to_user_id": str(to_user_id or ""),
                    "context_token": str(context_token or ""),
                    "message_type": 2,
                    "message_state": 2,
                    "item_list": [
                        {
                            "type": 1,
                            "text_item": {"text": str(text or "")},
                            "is_completed": True,
                        }
                    ],
                }
            },
            auth=True,
            timeout_ms=timeout_ms or self.request_timeout_ms,
        )
        return ClawBotSendResult(ok=True, raw=payload)

    async def get_config(self, *, ilink_user_id: str, context_token: str = "") -> dict[str, Any]:
        return await self._request_json(
            "POST",
            "ilink/bot/getconfig",
            json_body={
                "ilink_user_id": str(ilink_user_id or ""),
                "context_token": str(context_token or ""),
            },
            auth=True,
            timeout_ms=self.request_timeout_ms,
        )
