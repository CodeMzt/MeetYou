from __future__ import annotations

import base64
import json
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import aiohttp


DEFAULT_CLAWBOT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_OPENCLAW_STATE_DIR = "~/.openclaw"
DEFAULT_CLAWBOT_BOT_AGENT = "MeetYou/1.0"
DEFAULT_CLAWBOT_CHANNEL_VERSION = "meetyou"
DEFAULT_CLAWBOT_CLIENT_VERSION = "0"
DEFAULT_CLAWBOT_REQUEST_TIMEOUT_MS = 15000
DEFAULT_CLAWBOT_LONG_POLL_TIMEOUT_MS = 35000


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


@dataclass(slots=True)
class ClawBotAccount:
    account_id: str
    token: str
    base_url: str = DEFAULT_CLAWBOT_BASE_URL
    user_id: str = ""
    name: str = ""


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
            errmsg=str(raw.get("errmsg") or ""),
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


def resolve_openclaw_state_dir(configured: str = "") -> Path:
    configured = str(configured or "").strip()
    if configured:
        return Path(configured).expanduser()
    env_value = str(os.environ.get("OPENCLAW_STATE_DIR") or "").strip()
    if env_value:
        return Path(env_value).expanduser()
    return Path(DEFAULT_OPENCLAW_STATE_DIR).expanduser()


def sanitize_bot_agent(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return DEFAULT_CLAWBOT_BOT_AGENT
    product_re = re.compile(r"^[A-Za-z0-9_.-]{1,32}/[A-Za-z0-9_.+\-]{1,32}$")
    comment_re = re.compile(r"^[\x20-\x27\x2A-\x7E]{1,64}$")
    pieces = text.split()
    accepted: list[str] = []
    pending: str | None = None
    index = 0
    while index < len(pieces):
        token = pieces[index]
        if token.startswith("(") and not token.endswith(")"):
            while index + 1 < len(pieces) and not token.endswith(")"):
                index += 1
                token += " " + pieces[index]
        if token.startswith("(") and token.endswith(")"):
            inner = token[1:-1]
            if pending and comment_re.fullmatch(inner):
                accepted.append(f"{pending} ({inner})")
                pending = None
            elif pending:
                accepted.append(pending)
                pending = None
            index += 1
            continue
        if pending:
            accepted.append(pending)
            pending = None
        if product_re.fullmatch(token):
            pending = token
        index += 1
    if pending:
        accepted.append(pending)
    if not accepted:
        return DEFAULT_CLAWBOT_BOT_AGENT
    truncated: list[str] = []
    total = 0
    for token in accepted:
        added = len(token.encode("utf-8")) + (1 if truncated else 0)
        if total + added > 256:
            break
        truncated.append(token)
        total += added
    return " ".join(truncated) if truncated else DEFAULT_CLAWBOT_BOT_AGENT


class ClawBotClient:
    def __init__(
        self,
        *,
        state_dir: str = "",
        base_url: str = "",
        bot_agent: str = DEFAULT_CLAWBOT_BOT_AGENT,
        channel_version: str = DEFAULT_CLAWBOT_CHANNEL_VERSION,
        ilink_app_id: str = "",
        ilink_app_client_version: str = DEFAULT_CLAWBOT_CLIENT_VERSION,
        request_timeout_ms: int = DEFAULT_CLAWBOT_REQUEST_TIMEOUT_MS,
        long_poll_timeout_ms: int = DEFAULT_CLAWBOT_LONG_POLL_TIMEOUT_MS,
        session: aiohttp.ClientSession | None = None,
    ):
        self.state_dir = resolve_openclaw_state_dir(state_dir)
        self.base_url = str(base_url or "").strip()
        self.bot_agent = sanitize_bot_agent(bot_agent)
        self.channel_version = str(channel_version or DEFAULT_CLAWBOT_CHANNEL_VERSION).strip()
        self.ilink_app_id = str(ilink_app_id or "").strip()
        self.ilink_app_client_version = str(ilink_app_client_version or DEFAULT_CLAWBOT_CLIENT_VERSION).strip()
        self.request_timeout_ms = int(request_timeout_ms or DEFAULT_CLAWBOT_REQUEST_TIMEOUT_MS)
        self.long_poll_timeout_ms = int(long_poll_timeout_ms or DEFAULT_CLAWBOT_LONG_POLL_TIMEOUT_MS)
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

    @property
    def accounts_root(self) -> Path:
        return self.state_dir / "openclaw-weixin" / "accounts"

    def list_account_ids(self) -> list[str]:
        index_path = self.state_dir / "openclaw-weixin" / "accounts.json"
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        if not isinstance(payload, list):
            return []
        return [str(item).strip() for item in payload if str(item or "").strip()]

    def load_account(self, account_id: str) -> ClawBotAccount | None:
        clean_id = str(account_id or "").strip()
        if not clean_id:
            return None
        path = self.accounts_root / f"{clean_id}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(payload, dict):
            return None
        token = str(payload.get("token") or "").strip()
        if not token:
            return None
        return ClawBotAccount(
            account_id=clean_id,
            token=token,
            base_url=self.base_url or str(payload.get("baseUrl") or DEFAULT_CLAWBOT_BASE_URL).strip(),
            user_id=str(payload.get("userId") or "").strip(),
            name=str(payload.get("name") or "").strip(),
        )

    def list_accounts(self) -> list[ClawBotAccount]:
        accounts: list[ClawBotAccount] = []
        for account_id in self.list_account_ids():
            account = self.load_account(account_id)
            if account is not None:
                accounts.append(account)
        return accounts

    def _base_info(self) -> dict[str, Any]:
        return {
            "channel_version": self.channel_version,
            "bot_agent": self.bot_agent,
        }

    def _headers(self, account: ClawBotAccount) -> dict[str, str]:
        random_uin = base64.b64encode(str(random.getrandbits(32)).encode("utf-8")).decode("ascii")
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {account.token}",
            "X-WECHAT-UIN": random_uin,
            "iLink-App-Id": self.ilink_app_id,
            "iLink-App-ClientVersion": self.ilink_app_client_version,
        }
        return headers

    async def _post_json(
        self,
        account: ClawBotAccount,
        endpoint: str,
        body: dict[str, Any],
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        await self.init()
        assert self._session is not None
        payload = dict(body or {})
        payload["base_info"] = self._base_info()
        url = urljoin(account.base_url.rstrip("/") + "/", endpoint.lstrip("/"))
        timeout = aiohttp.ClientTimeout(total=max(int(timeout_ms or self.request_timeout_ms), 1) / 1000)
        async with self._session.request(
            "POST",
            url,
            headers=self._headers(account),
            json=payload,
            timeout=timeout,
        ) as response:
            try:
                response_payload: Any = await response.json(content_type=None)
            except TypeError:
                response_payload = await response.json()
            except Exception:
                response_payload = {"message": await response.text()}
            if response.status >= 400:
                message = ""
                if isinstance(response_payload, dict):
                    message = str(response_payload.get("errmsg") or response_payload.get("message") or "")
                raise ClawBotHTTPError(response.status, message or "ClawBot HTTP error", response_payload)
            return response_payload if isinstance(response_payload, dict) else {"data": response_payload}

    async def get_updates(self, account: ClawBotAccount, *, get_updates_buf: str = "", timeout_ms: int | None = None) -> ClawBotGetUpdatesResult:
        payload = await self._post_json(
            account,
            "ilink/bot/getupdates",
            {"get_updates_buf": str(get_updates_buf or "")},
            timeout_ms=timeout_ms or self.long_poll_timeout_ms,
        )
        return ClawBotGetUpdatesResult.from_payload(payload)

    async def send_text(
        self,
        account: ClawBotAccount,
        *,
        to_user_id: str,
        context_token: str,
        text: str,
        timeout_ms: int | None = None,
    ) -> ClawBotSendResult:
        payload = await self._post_json(
            account,
            "ilink/bot/sendmessage",
            {
                "msg": {
                    "to_user_id": str(to_user_id or ""),
                    "context_token": str(context_token or ""),
                    "item_list": [
                        {
                            "type": 1,
                            "text_item": {"text": str(text or "")},
                        }
                    ],
                }
            },
            timeout_ms=timeout_ms or self.request_timeout_ms,
        )
        ret = payload.get("ret") if isinstance(payload, dict) else None
        if ret not in (None, 0):
            raise ClawBotAPIError(_safe_int(ret), str(payload.get("errmsg") or "sendmessage rejected"), payload)
        return ClawBotSendResult(ok=True, raw=payload)

    async def get_config(self, account: ClawBotAccount, *, ilink_user_id: str, context_token: str = "") -> dict[str, Any]:
        return await self._post_json(
            account,
            "ilink/bot/getconfig",
            {
                "ilink_user_id": str(ilink_user_id or ""),
                "context_token": str(context_token or ""),
            },
            timeout_ms=self.request_timeout_ms,
        )

    async def notify_start(self, account: ClawBotAccount) -> dict[str, Any]:
        return await self._post_json(account, "ilink/bot/msg/notifystart", {}, timeout_ms=self.request_timeout_ms)

    async def notify_stop(self, account: ClawBotAccount) -> dict[str, Any]:
        return await self._post_json(account, "ilink/bot/msg/notifystop", {}, timeout_ms=self.request_timeout_ms)
