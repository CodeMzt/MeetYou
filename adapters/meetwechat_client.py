from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import aiohttp


DEFAULT_MEETWECHAT_BASE_URL = "http://127.0.0.1:38961"
DEFAULT_MEETWECHAT_REQUEST_TIMEOUT_SECONDS = 10


class MeetWeChatError(RuntimeError):
    pass


class MeetWeChatHTTPError(MeetWeChatError):
    def __init__(self, status: int, message: str, payload: Any = None):
        super().__init__(f"{status} {message}".strip())
        self.status = status
        self.payload = payload


@dataclass(slots=True)
class MeetWeChatEvent:
    event_id: str
    message_id: str
    chat_id: str
    chat_type: str
    sender_id: str
    sender_name: str = ""
    is_self: bool = False
    is_group_mention: bool = False
    content_type: str = "text"
    text: str = ""
    timestamp: str = ""
    raw_hash: str = ""
    dedup_key: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "MeetWeChatEvent":
        raw = dict(payload or {})
        return cls(
            event_id=str(raw.get("event_id") or ""),
            message_id=str(raw.get("message_id") or ""),
            chat_id=str(raw.get("chat_id") or ""),
            chat_type=str(raw.get("chat_type") or "private").strip().lower() or "private",
            sender_id=str(raw.get("sender_id") or ""),
            sender_name=str(raw.get("sender_name") or ""),
            is_self=bool(raw.get("is_self")),
            is_group_mention=bool(raw.get("is_group_mention")),
            content_type=str(raw.get("content_type") or "text").strip().lower() or "text",
            text=str(raw.get("text") or ""),
            timestamp=str(raw.get("timestamp") or ""),
            raw_hash=str(raw.get("raw_hash") or ""),
            dedup_key=str(raw.get("dedup_key") or ""),
            raw=raw,
        )


@dataclass(slots=True)
class MeetWeChatSendResult:
    ok: bool
    status: str = ""
    command_id: str = ""
    message_id: str = ""
    detail: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "MeetWeChatSendResult":
        raw = dict(payload or {})
        return cls(
            ok=bool(raw.get("ok", True)),
            status=str(raw.get("status") or ""),
            command_id=str(raw.get("command_id") or raw.get("commandId") or ""),
            message_id=str(raw.get("message_id") or raw.get("messageId") or ""),
            detail=str(raw.get("detail") or raw.get("message") or ""),
            raw=raw,
        )


class MeetWeChatClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_MEETWECHAT_BASE_URL,
        access_token: str = "",
        request_timeout_seconds: float = DEFAULT_MEETWECHAT_REQUEST_TIMEOUT_SECONDS,
        session: aiohttp.ClientSession | None = None,
    ):
        self.base_url = str(base_url or DEFAULT_MEETWECHAT_BASE_URL).strip().rstrip("/") or DEFAULT_MEETWECHAT_BASE_URL
        self.access_token = str(access_token or "").strip()
        self.request_timeout_seconds = float(request_timeout_seconds or DEFAULT_MEETWECHAT_REQUEST_TIMEOUT_SECONDS)
        self._session = session
        self._owns_session = session is None

    async def init(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=max(self.request_timeout_seconds, 0.1))
            self._session = aiohttp.ClientSession(headers=self._auth_headers(), timeout=timeout)
            self._owns_session = True

    async def close(self) -> None:
        if self._session is not None and self._owns_session:
            await self._session.close()
        self._session = None

    def _auth_headers(self) -> dict[str, str]:
        if not self.access_token:
            return {}
        return {"Authorization": f"Bearer {self.access_token}"}

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self.init()
        assert self._session is not None
        url = f"{self.base_url}{path}"
        async with self._session.request(method, url, params=params, json=json_body) as response:
            payload: Any
            try:
                payload = await response.json(content_type=None)
            except TypeError:
                payload = await response.json()
            except Exception:
                text = await response.text()
                payload = {"message": text}
            if response.status >= 400:
                message = ""
                if isinstance(payload, dict):
                    error = payload.get("error")
                    if isinstance(error, dict):
                        message = str(error.get("message") or "")
                    message = message or str(payload.get("message") or payload.get("detail") or "")
                raise MeetWeChatHTTPError(response.status, message or "MeetWeChat HTTP error", payload)
            if not isinstance(payload, dict):
                return {"data": payload}
            return payload

    async def health(self) -> dict[str, Any]:
        return await self._request_json("GET", "/v1/health")

    async def list_chats(self) -> list[dict[str, Any]]:
        payload = await self._request_json("GET", "/v1/chats")
        chats = payload.get("items", payload.get("chats", payload.get("data", [])))
        return list(chats) if isinstance(chats, list) else []

    async def get_events(self, *, limit: int = 20, cursor: str = "") -> tuple[list[MeetWeChatEvent], str]:
        params: dict[str, Any] = {"limit": int(limit or 20)}
        if cursor:
            params["cursor"] = cursor
        payload = await self._request_json("GET", "/v1/events", params=params)
        events_payload = payload.get("items", payload.get("events", payload.get("data", [])))
        if not isinstance(events_payload, list):
            events_payload = []
        events = [
            MeetWeChatEvent.from_payload(item)
            for item in events_payload
            if isinstance(item, dict)
        ]
        next_cursor = str(payload.get("next_cursor") or payload.get("cursor") or "")
        return events, next_cursor

    async def ack_events(self, event_ids: list[str]) -> dict[str, Any]:
        clean_ids = [str(item).strip() for item in event_ids if str(item).strip()]
        if not clean_ids:
            return {"ok": True, "acked": []}
        return await self._request_json("POST", "/v1/events/ack", json_body={"event_ids": clean_ids})

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        idempotency_key: str,
        is_group_mention: bool = False,
    ) -> MeetWeChatSendResult:
        body: dict[str, Any] = {
            "chat_id": str(chat_id or ""),
            "text": str(text or ""),
            "idempotency_key": str(idempotency_key or ""),
        }
        if is_group_mention:
            body["is_group_mention"] = True
        payload = await self._request_json("POST", "/v1/messages/text", json_body=body)
        return MeetWeChatSendResult.from_payload(payload)

    async def set_override(self, chat_id: str, *, mode: str, reason: str = "") -> dict[str, Any]:
        body = {"mode": str(mode or "").strip(), "reason": str(reason or "")}
        encoded_chat_id = quote(str(chat_id or ""), safe="")
        return await self._request_json("PUT", f"/v1/overrides/{encoded_chat_id}", json_body=body)
