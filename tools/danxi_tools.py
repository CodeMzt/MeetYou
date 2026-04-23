from __future__ import annotations

import base64
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from Crypto.Cipher import AES
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

from core.credential_transport import CredentialTransportError, decrypt_json_payload, encrypt_json_payload


class DanxiError(RuntimeError):
    pass


_SHARED_DANXI_TOOLS: "DanxiTools | None" = None
_DANXI_PERSISTENCE_PURPOSE = "danxi.session.persistence.v1"
logger = logging.getLogger("meetyou.danxi")


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None and value != ""}


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", "\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _first_non_empty(*values: Any) -> str:
    for value in values:
        normalized = _normalize_text(value)
        if normalized:
            return normalized
    return ""


def _collapse_inline(value: Any, limit: int = 120) -> str:
    text = " ".join(_normalize_text(value).split())
    if len(text) <= limit:
        return text
    return f"{text[: max(limit - 1, 0)].rstrip()}..."


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _first_env(*names: str) -> str:
    for name in names:
        value = str(os.getenv(name, "")).strip()
        if value:
            return value
    return ""


def _coerce_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso8601_utc(value: str | None) -> str | None:
    parsed = _coerce_datetime(value)
    if parsed is None:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _unix_seconds(value: str | None) -> int | None:
    parsed = _coerce_datetime(value)
    if parsed is None:
        return None
    return int(parsed.timestamp())


@dataclass
class _DanxiSessionState:
    session_key: str
    email: str
    password: str
    use_webvpn: bool
    webvpn_cookie: str
    http: requests.Session = field(default_factory=requests.Session)
    access_token: str = ""
    refresh_token: str = ""
    user_profile: dict[str, Any] | None = None
    restored_from_persistence: bool = False
    restore_validated: bool = False
    last_connection_error: str = ""
    floor_hole_cache: dict[int, int] = field(default_factory=dict)


class DanxiTools:
    API_BASE = "https://forum.fduhole.com/api"
    AUTH_BASE = "https://auth.fduhole.com/api"
    DIRECT_CONNECT_TEST_URL = "https://forum.fduhole.com"
    WEBVPN_HOST = "webvpn.fudan.edu.cn"
    WEBVPN_LOGIN_PREFIX = f"https://{WEBVPN_HOST}/login"
    WEBVPN_LOGIN_URL = f"{WEBVPN_LOGIN_PREFIX}?cas_login=true"
    WEBVPN_IDP_BASE = "https://id.fudan.edu.cn/idp"
    _WEBVPN_KEY = b"wrdvpnisthebest!"
    _DIRECT_REQUEST_TIMEOUT = (5, 20)
    _WEBVPN_REQUEST_TIMEOUT = (10, 45)
    _WEBVPN_LOGIN_PAGE_TIMEOUT = (10, 90)
    _WEBVPN_ALLOWED_HOSTS = {
        "www.fduhole.com",
        "auth.fduhole.com",
        "danke.fduhole.com",
        "forum.fduhole.com",
        "image.fduhole.com",
        "yjsxk.fudan.edu.cn",
        "10.64.130.6",
    }

    def __init__(self) -> None:
        self._sessions: dict[str, _DanxiSessionState] = {}
        self._active_session_key: str = ""
        self._host_cache: dict[str, str] = {}
        self._direct_connect_available: bool | None = None
        self._lock = threading.RLock()
        self._state_backend = None

    def set_state_backend(self, backend) -> None:
        self._state_backend = backend
        self._restore_persisted_sessions()

    def danxi_login(
        self,
        email: str = "",
        password: str = "",
        *,
        session_key: str = "default",
        use_webvpn: bool | None = None,
        webvpn_cookie: str = "",
    ) -> dict[str, Any]:
        resolved_email, resolved_password = self._resolve_danxi_credentials(email, password)
        if not resolved_email or not resolved_password:
            raise DanxiError("Danxi 登录需要 email 和 password，或配置 DANXI_MAIL / DANXI_PASSWORD 环境变量。")
        if use_webvpn is None:
            use_webvpn = self._resolve_default_use_webvpn()
        resolved_webvpn_cookie = str(webvpn_cookie or os.getenv("MEETYOU_DANXI_WEBVPN_COOKIE", "")).strip()
        state = _DanxiSessionState(
            session_key=str(session_key or "default").strip() or "default",
            email=resolved_email,
            password=resolved_password,
            use_webvpn=bool(use_webvpn),
            webvpn_cookie=resolved_webvpn_cookie,
        )
        state.http.headers.update({"Accept": "application/json", "User-Agent": "MeetYou-Danxi/1.0"})
        if state.use_webvpn and not state.webvpn_cookie:
            self._refresh_webvpn_cookie_from_env(state)
        payload = self._post_auth_login(state)
        with self._lock:
            self._sessions[state.session_key] = state
            self._active_session_key = state.session_key
        profile = self._safe_load_profile(state)
        self._mark_session_validated(state)
        self._persist_sessions()
        webvpn_enabled = self._is_webvpn_enabled(state)
        return {
            "session_key": state.session_key,
            "email": state.email,
            "transport": self._transport_label(state),
            "webvpn_enabled": webvpn_enabled,
            "has_webvpn_cookie": bool(state.webvpn_cookie),
            "logged_in": bool(state.access_token),
            "token": {
                "has_access_token": bool(state.access_token),
                "has_refresh_token": bool(state.refresh_token),
                "raw_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
            },
            "user_profile": profile,
        }

    def danxi_logout(self, session_key: str = "") -> dict[str, Any]:
        with self._lock:
            resolved_key = self._resolve_session_key(session_key, required=False)
            if not resolved_key:
                return {"logged_out": False, "reason": "no_active_session"}
            state = self._sessions.pop(resolved_key, None)
            if state is not None:
                state.http.close()
            if self._active_session_key == resolved_key:
                self._active_session_key = next(iter(self._sessions.keys()), "")
        self._persist_sessions()
        return {"logged_out": state is not None, "session_key": resolved_key}

    def danxi_set_webvpn_cookie(self, cookie_header: str, *, session_key: str = "", enable_webvpn: bool = True) -> dict[str, Any]:
        state = self._get_session(session_key)
        resolved_cookie = str(cookie_header or "").strip()
        if not resolved_cookie:
            raise DanxiError("设置 WebVPN cookie 时 cookie_header 不能为空。")
        state.webvpn_cookie = resolved_cookie
        if enable_webvpn:
            state.use_webvpn = True
        self._persist_sessions()
        return self.danxi_get_session_status(state.session_key)

    def danxi_clear_webvpn_cookie(self, session_key: str = "") -> dict[str, Any]:
        state = self._get_session(session_key)
        state.webvpn_cookie = ""
        self._persist_sessions()
        return self.danxi_get_session_status(state.session_key)

    def danxi_get_session_status(self, session_key: str = "") -> dict[str, Any]:
        state = self._get_session_or_login_from_env(session_key)
        self._ensure_restored_session_is_valid(state)
        direct_connect_available = self._can_connect_directly()
        webvpn_enabled = self._is_webvpn_enabled(state, direct_connect_available=direct_connect_available)
        webvpn_required = bool(webvpn_enabled and not direct_connect_available)
        connection_ok, connection_error = self._probe_session_connectivity(state)
        return {
            "session_key": state.session_key,
            "email": state.email,
            "transport": self._transport_label(state),
            "webvpn_enabled": webvpn_enabled,
            "has_webvpn_cookie": bool(state.webvpn_cookie),
            "webvpn_required": webvpn_required,
            "direct_connect_available": direct_connect_available,
            "logged_in": connection_ok,
            "connection_error": connection_error or None,
            "user_profile": state.user_profile,
        }

    def danxi_get_user_profile(self, *, session_key: str = "", refresh: bool = False) -> dict[str, Any]:
        state = self._get_session(session_key)
        self._ensure_restored_session_is_valid(state)
        if refresh or state.user_profile is None:
            profile = self._safe_load_profile(state)
            if profile is None:
                raise DanxiError("当前会话暂时无法读取 Danxi 用户信息。")
        status = self.danxi_get_session_status(state.session_key)
        return {
            "session_key": state.session_key,
            "logged_in": bool(status.get("logged_in")),
            "transport": str(status.get("transport") or ""),
            "webvpn_enabled": bool(status.get("webvpn_enabled")),
            "has_webvpn_cookie": bool(status.get("has_webvpn_cookie")),
            "webvpn_required": bool(status.get("webvpn_required")),
            "direct_connect_available": bool(status.get("direct_connect_available")),
            "profile": state.user_profile or {},
        }

    def danxi_list_divisions(self, session_key: str = "") -> dict[str, Any]:
        state = self._get_session(session_key)
        data = self._request_json("GET", f"{self.API_BASE}/divisions", state=state)
        return {"count": len(data) if isinstance(data, list) else 0, "items": data}

    def danxi_list_tags(self, session_key: str = "") -> dict[str, Any]:
        state = self._get_session(session_key)
        data = self._request_json("GET", f"{self.API_BASE}/tags", state=state)
        return {"count": len(data) if isinstance(data, list) else 0, "items": data}

    def danxi_list_posts(
        self,
        *,
        division_id: int | None = None,
        start_time: str = "",
        length: int = 20,
        offset: int = 0,
        tag: str = "",
        order: str = "time_created",
        session_key: str = "",
    ) -> dict[str, Any]:
        state = self._get_session(session_key)
        normalized_length = max(1, min(int(length or 20), 10))
        
        # Determine the start time for fetching
        # If start_time is not provided, use current time
        # Note: API uses ISO8601 strings for time-based pagination
        current_time_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        time_to_fetch = _iso8601_utc(start_time) or current_time_iso

        if division_id is None:
            params = {
                "offset": time_to_fetch,
                "size": normalized_length,
                "order": order or "time_created",
            }
            data = self._request_json("GET", f"{self.API_BASE}/holes/_homepage", state=state, params=params)
            scope = "homepage"
        else:
            params = _compact_dict(
                {
                    "offset": time_to_fetch,
                    "division_id": int(division_id),
                    "length": normalized_length,
                    "tag": str(tag or "").strip() or None,
                    "order": order or "time_created",
                }
            )
            data = self._request_json("GET", f"{self.API_BASE}/holes", state=state, params=params)
            scope = f"division:{division_id}"
        return {"scope": scope, "count": len(data) if isinstance(data, list) else 0, "items": data}

    def danxi_get_post(self, hole_id: int, *, session_key: str = "") -> dict[str, Any]:
        state = self._get_session(session_key)
        data = self._request_json("GET", f"{self.API_BASE}/holes/{int(hole_id)}", state=state)
        return {"hole": data}

    def danxi_list_floors(
        self,
        hole_id: int,
        *,
        offset: int = 0,
        size: int = 20,
        include_all: bool = False,
        session_key: str = "",
    ) -> dict[str, Any]:
        state = self._get_session(session_key)
        if include_all:
            params = {"start_floor": 0, "length": 0, "hole_id": int(hole_id)}
            data = self._request_json("GET", f"{self.API_BASE}/floors", state=state, params=params)
        else:
            params = {"offset": max(0, int(offset or 0)), "size": max(1, min(int(size or 20), 100))}
            data = self._request_json("GET", f"{self.API_BASE}/holes/{int(hole_id)}/floors", state=state, params=params)
        return {"hole_id": int(hole_id), "count": len(data) if isinstance(data, list) else 0, "items": data}

    def danxi_search_posts(
        self,
        query: str,
        *,
        accurate: bool = False,
        length: int = 20,
        start_floor: int | None = None,
        start_time: str = "",
        end_time: str = "",
        session_key: str = "",
    ) -> dict[str, Any]:
        state = self._get_session(session_key)
        params = _compact_dict(
            {
                "search": str(query or "").strip(),
                "accurate": bool(accurate),
                "size": max(1, min(int(length or 20), 10)),
                "offset": int(start_floor) if start_floor is not None else None,
                "start_time": _unix_seconds(start_time),
                "end_time": _unix_seconds(end_time),
            }
        )
        if not params.get("search"):
            raise DanxiError("Danxi 搜索需要 query。")
        floors = self._request_json("GET", f"{self.API_BASE}/floors/search", state=state, params=params)
        holes: list[int] = []
        grouped: dict[int, list[dict[str, Any]]] = {}
        if isinstance(floors, list):
            for item in floors:
                if not isinstance(item, dict):
                    continue
                hole_id = item.get("hole_id")
                if isinstance(hole_id, int):
                    if hole_id not in holes:
                        holes.append(hole_id)
                    grouped.setdefault(hole_id, []).append(item)
        return {
            "query": params["search"],
            "floor_hits": len(floors) if isinstance(floors, list) else 0,
            "hole_ids": holes,
            "hits_by_hole": grouped,
            "items": floors,
        }

    def danxi_create_post(
        self,
        division_id: int,
        content: str,
        *,
        tag_ids: list[int] | None = None,
        tag_names: list[str] | None = None,
        session_key: str = "",
    ) -> dict[str, Any]:
        state = self._get_session(session_key)
        body = {
            "content": str(content or "").strip(),
            "tags": self._build_tags_payload(tag_ids or [], tag_names or []),
        }
        if not body["content"]:
            raise DanxiError("发帖内容不能为空。")
        response = self._request(
            "POST",
            f"{self.API_BASE}/divisions/{int(division_id)}/holes",
            state=state,
            json_body=body,
        )
        return {"status_code": response.status_code, "ok": response.ok, "division_id": int(division_id)}

    def danxi_reply_post(self, hole_id: int, content: str, *, session_key: str = "") -> dict[str, Any]:
        state = self._get_session(session_key)
        body = {"content": str(content or "").strip()}
        if not body["content"]:
            raise DanxiError("回复内容不能为空。")
        response = self._request("POST", f"{self.API_BASE}/holes/{int(hole_id)}/floors", state=state, json_body=body)
        return {"status_code": response.status_code, "ok": response.ok, "hole_id": int(hole_id)}

    def danxi_edit_reply(self, floor_id: int, content: str, *, session_key: str = "") -> dict[str, Any]:
        state = self._get_session(session_key)
        body = {"content": str(content or "").strip()}
        if not body["content"]:
            raise DanxiError("编辑后的回复内容不能为空。")
        response = self._request("PATCH", f"{self.API_BASE}/floors/{int(floor_id)}/_webvpn", state=state, json_body=body)
        return {"status_code": response.status_code, "ok": response.ok, "floor_id": int(floor_id)}

    def danxi_delete_reply(self, floor_id: int, *, confirm: bool = False, session_key: str = "") -> dict[str, Any]:
        if not confirm:
            raise DanxiError("删除回复前必须显式传入 confirm=true。")
        state = self._get_session(session_key)
        response = self._request("DELETE", f"{self.API_BASE}/floors/{int(floor_id)}", state=state)
        return {"status_code": response.status_code, "ok": response.ok, "floor_id": int(floor_id)}

    def danxi_delete_post(self, hole_id: int, *, confirm: bool = False, session_key: str = "") -> dict[str, Any]:
        if not confirm:
            raise DanxiError("删除帖子前必须显式传入 confirm=true。")
        state = self._get_session(session_key)
        response = self._request("DELETE", f"{self.API_BASE}/holes/{int(hole_id)}", state=state)
        return {"status_code": response.status_code, "ok": response.ok, "hole_id": int(hole_id)}

    def danxi_manage_favorite(
        self,
        action: str,
        *,
        hole_id: int | None = None,
        length: int = 20,
        prefetch_length: int = 20,
        session_key: str = "",
    ) -> dict[str, Any]:
        state = self._get_session(session_key)
        normalized_action = str(action or "").strip().lower()
        if normalized_action == "list":
            params = {"length": max(1, min(int(length or 20), 100)), "prefetch_length": max(1, min(int(prefetch_length or 20), 100))}
            data = self._request_json("GET", f"{self.API_BASE}/user/favorites", state=state, params=params)
            return {"action": "list", "count": len(data) if isinstance(data, list) else 0, "items": data}
        if hole_id is None:
            raise DanxiError("收藏或取消收藏需要 hole_id。")
        if normalized_action == "add":
            response = self._request("POST", f"{self.API_BASE}/user/favorites", state=state, json_body={"hole_id": int(hole_id)})
        elif normalized_action == "remove":
            response = self._request("DELETE", f"{self.API_BASE}/user/favorites", state=state, json_body={"hole_id": int(hole_id)})
        else:
            raise DanxiError("收藏操作 action 仅支持 list / add / remove。")
        return {"action": normalized_action, "status_code": response.status_code, "ok": response.ok, "hole_id": int(hole_id)}

    def danxi_manage_subscription(
        self,
        action: str,
        *,
        hole_id: int | None = None,
        length: int = 20,
        prefetch_length: int = 20,
        session_key: str = "",
    ) -> dict[str, Any]:
        state = self._get_session(session_key)
        normalized_action = str(action or "").strip().lower()
        if normalized_action == "list":
            params = {"length": max(1, min(int(length or 20), 100)), "prefetch_length": max(1, min(int(prefetch_length or 20), 100))}
            data = self._request_json("GET", f"{self.API_BASE}/users/subscriptions", state=state, params=params)
            return {"action": "list", "count": len(data) if isinstance(data, list) else 0, "items": data}
        if hole_id is None:
            raise DanxiError("订阅或取消订阅需要 hole_id。")
        if normalized_action == "add":
            response = self._request("POST", f"{self.API_BASE}/users/subscriptions", state=state, json_body={"hole_id": int(hole_id)})
        elif normalized_action == "remove":
            response = self._request("DELETE", f"{self.API_BASE}/users/subscriptions", state=state, json_body={"hole_id": int(hole_id)})
        else:
            raise DanxiError("订阅操作 action 仅支持 list / add / remove。")
        return {"action": normalized_action, "status_code": response.status_code, "ok": response.ok, "hole_id": int(hole_id)}

    def danxi_list_messages(
        self,
        *,
        unread_only: bool = False,
        start_time: str = "",
        session_key: str = "",
    ) -> dict[str, Any]:
        state = self._get_session(session_key)
        params = _compact_dict({"not_read": bool(unread_only), "start_time": _iso8601_utc(start_time)})
        data = self._request_json("GET", f"{self.API_BASE}/messages", state=state, params=params)
        items = self._normalize_message_items(data, state=state) if isinstance(data, list) else data
        return {"count": len(items) if isinstance(items, list) else 0, "items": items}

    def _normalize_message_items(self, items: list[Any], *, state: _DanxiSessionState) -> list[Any]:
        normalized: list[Any] = []
        for item in items:
            if not isinstance(item, dict):
                normalized.append(item)
                continue
            normalized.append(self._normalize_message_item(item, state=state))
        return normalized

    def _normalize_message_item(self, item: dict[str, Any], *, state: _DanxiSessionState) -> dict[str, Any]:
        normalized = dict(item)
        related_hole_id = self._extract_message_hole_id(normalized)
        if related_hole_id is not None:
            normalized["related_hole_id"] = related_hole_id
            return normalized

        related_floor_id = self._extract_message_floor_id(normalized)
        if related_floor_id is None:
            return normalized
        normalized["related_floor_id"] = related_floor_id

        hole_id = state.floor_hole_cache.get(related_floor_id)
        if hole_id is None:
            hole_id = self._resolve_hole_id_from_floor(related_floor_id, state=state)
            if hole_id is not None:
                state.floor_hole_cache[related_floor_id] = hole_id
        if hole_id is not None:
            normalized["related_hole_id"] = hole_id
        return normalized

    def _extract_message_hole_id(self, item: dict[str, Any]) -> int | None:
        for key in ("hole_id", "post_id", "target_hole_id", "related_hole_id", "reply_hole_id", "thread_hole_id"):
            candidate = item.get(key)
            if isinstance(candidate, int) and candidate > 0:
                return candidate
            if isinstance(candidate, str) and candidate.isdigit():
                parsed = int(candidate)
                if parsed > 0:
                    return parsed
        for key in ("url", "link"):
            parsed = self._extract_id_from_message_path(item.get(key), marker="/api/holes/")
            if parsed is None:
                parsed = self._extract_id_from_message_path(item.get(key), marker="/holes/")
            if parsed is not None:
                return parsed
        return None

    def _extract_message_floor_id(self, item: dict[str, Any]) -> int | None:
        for key in ("floor_id", "reply_floor_id", "related_floor_id"):
            candidate = item.get(key)
            if isinstance(candidate, int) and candidate > 0:
                return candidate
            if isinstance(candidate, str) and candidate.isdigit():
                parsed = int(candidate)
                if parsed > 0:
                    return parsed
        for key in ("url", "link"):
            parsed = self._extract_id_from_message_path(item.get(key), marker="/api/floors/")
            if parsed is None:
                parsed = self._extract_id_from_message_path(item.get(key), marker="/floors/")
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _extract_id_from_message_path(value: Any, *, marker: str) -> int | None:
        text = str(value or "").strip()
        if not text:
            return None
        path = urlparse(text).path or text
        if marker not in path:
            return None
        suffix = path.split(marker, 1)[1]
        digits = []
        for char in suffix:
            if char.isdigit():
                digits.append(char)
                continue
            break
        if not digits:
            return None
        parsed = int("".join(digits))
        return parsed if parsed > 0 else None

    def _resolve_hole_id_from_floor(self, floor_id: int, *, state: _DanxiSessionState) -> int | None:
        try:
            payload = self._request_json("GET", f"{self.API_BASE}/floors/{int(floor_id)}", state=state)
        except Exception as exc:
            logger.debug("Failed to resolve Danxi floor %s to hole id: %s", floor_id, exc)
            return None
        if not isinstance(payload, dict):
            return None
        for key in ("hole_id", "post_id"):
            candidate = payload.get(key)
            if isinstance(candidate, int) and candidate > 0:
                return candidate
            if isinstance(candidate, str) and candidate.isdigit():
                parsed = int(candidate)
                if parsed > 0:
                    return parsed
        return None

    def danxi_mark_message_read(
        self,
        message_id: int,
        *,
        has_read: bool = True,
        session_key: str = "",
    ) -> dict[str, Any]:
        state = self._get_session(session_key)
        response = self._request(
            "PATCH",
            f"{self.API_BASE}/messages/{int(message_id)}",
            state=state,
            json_body={"has_read": bool(has_read)},
        )
        return {"status_code": response.status_code, "ok": response.ok, "message_id": int(message_id), "has_read": bool(has_read)}

    def danxi_resolve_message_target(self, floor_id: int, *, session_key: str = "") -> dict[str, Any]:
        state = self._get_session(session_key)
        hole_id = state.floor_hole_cache.get(int(floor_id))
        if hole_id is None:
            hole_id = self._resolve_hole_id_from_floor(int(floor_id), state=state)
            if hole_id is None:
                raise DanxiError(f"无法根据楼层 {int(floor_id)} 解析关联帖子。")
            state.floor_hole_cache[int(floor_id)] = hole_id
        return {"floor_id": int(floor_id), "hole_id": int(hole_id)}

    def danxi_summarize_post(self, hole_id: int, *, session_key: str = "", floor_limit: int = 50) -> dict[str, Any]:
        post_payload = self.danxi_get_post(hole_id, session_key=session_key)
        floors_payload = self.danxi_list_floors(
            hole_id,
            session_key=session_key,
            offset=0,
            size=max(1, min(int(floor_limit or 50), 100)),
        )
        hole = post_payload.get("hole") if isinstance(post_payload, dict) else {}
        floors = floors_payload.get("items") if isinstance(floors_payload, dict) else []
        if not isinstance(hole, dict):
            hole = {}
        if not isinstance(floors, list):
            floors = []

        original_text = _first_non_empty(
            (hole.get("floors") or {}).get("first_floor", {}).get("content") if isinstance(hole.get("floors"), dict) else None,
            hole.get("content"),
            hole.get("text"),
            hole.get("title"),
        )
        key_points: list[str] = []
        if original_text:
            key_points.append(_collapse_inline(original_text, limit=96))
        division_label = _first_non_empty(hole.get("division"), hole.get("division_name"), hole.get("division_id"))
        if division_label:
            key_points.append(f"分区信息: {division_label}")
        if isinstance(hole.get("reply"), int):
            key_points.append(f"当前帖子显示 {int(hole['reply'])} 条回复。")

        reply_highlights: list[str] = []
        participants: set[str] = set()
        for item in floors:
            if not isinstance(item, dict):
                continue
            author = _first_non_empty(
                item.get("anonyname"),
                item.get("nickname"),
                item.get("name"),
                item.get("user_name"),
                item.get("author"),
            ) or "匿名"
            if author:
                participants.add(author)
            content = _first_non_empty(item.get("content"), item.get("text"), item.get("description"))
            if not content:
                continue
            snippet = _collapse_inline(content, limit=84)
            if snippet and snippet not in reply_highlights:
                reply_highlights.append(f"{author}: {snippet}")
            if len(reply_highlights) >= 3:
                break

        if not key_points:
            key_points.append(f"帖子 #{int(hole_id)} 暂无可提炼的正文信息。")

        summary_parts = [
            _collapse_inline(original_text, limit=110) or f"帖子 #{int(hole_id)} 已加载。",
            f"共整理到 {len(floors)} 条楼层，参与者约 {max(len(participants), 1)} 位。",
        ]
        if reply_highlights:
            summary_parts.append("讨论集中在：" + "；".join(reply_highlights[:2]))

        return {
            "hole_id": int(hole_id),
            "title": _first_non_empty(hole.get("title"), f"帖子 #{int(hole_id)}"),
            "summary": " ".join(part for part in summary_parts if part).strip(),
            "key_points": key_points[:4],
            "reply_highlights": reply_highlights,
            "floor_count": len(floors),
            "participant_count": len(participants),
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    def _resolve_session_key(self, session_key: str, *, required: bool = True) -> str:
        normalized = str(session_key or "").strip() or self._active_session_key
        if normalized:
            return normalized
        if required:
            raise DanxiError("还没有活跃的 Danxi 会话，请先调用 danxi_login。")
        return ""

    def _get_session(self, session_key: str) -> _DanxiSessionState:
        resolved = self._resolve_session_key(session_key)
        state = self._sessions.get(resolved)
        if state is None:
            raise DanxiError(f"找不到 Danxi 会话: {resolved}")
        return state

    def _get_session_or_login_from_env(self, session_key: str) -> _DanxiSessionState:
        try:
            return self._get_session(session_key)
        except DanxiError:
            env_email, env_password = self._resolve_danxi_credentials()
            if not env_email or not env_password:
                raise
            resolved_key = str(session_key or "default").strip() or "default"
            self.danxi_login(session_key=resolved_key)
            return self._get_session(resolved_key)

    def _ensure_restored_session_is_valid(self, state: _DanxiSessionState) -> None:
        if not state.restored_from_persistence or state.restore_validated:
            return
        try:
            profile = self._request_json("GET", f"{self.API_BASE}/users/me", state=state)
        except Exception as exc:
            message = str(exc) or "Danxi 会话恢复失败"
            lowered = message.lower()
            if any(token in lowered for token in ("401", "token", "webvpn", "cookie", "撤销", "过期")):
                self._invalidate_session(
                    state.session_key,
                    message="已保存的 Danxi/WebVPN 登录态已失效，系统已清理，请重新登录。",
                )
                raise DanxiError("已保存的 Danxi/WebVPN 登录态已失效，系统已清理，请重新登录。") from exc
            raise DanxiError("恢复的 Danxi 会话暂时无法验证，请稍后重试。") from exc
        if isinstance(profile, dict):
            state.user_profile = profile
        self._mark_session_validated(state)
        self._persist_sessions()

    def _mark_session_validated(self, state: _DanxiSessionState) -> None:
        state.restored_from_persistence = False
        state.restore_validated = True
        state.last_connection_error = ""

    def _probe_session_connectivity(self, state: _DanxiSessionState) -> tuple[bool, str]:
        if not state.access_token:
            state.last_connection_error = ""
            return False, ""
        try:
            profile = self._request_json("GET", f"{self.API_BASE}/users/me", state=state)
        except Exception as exc:
            message = str(exc) or "Danxi 会话暂时不可用。"
            state.last_connection_error = message
            return False, message
        if isinstance(profile, dict):
            state.user_profile = profile
        self._mark_session_validated(state)
        self._persist_sessions()
        return True, ""

    def _restore_persisted_sessions(self) -> None:
        if self._state_backend is None:
            return
        try:
            payload = self._state_backend.load()
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load Danxi persistence state: %s", exc)
            return
        if not isinstance(payload, dict):
            return
        restored_sessions: dict[str, _DanxiSessionState] = {}
        for item in list(payload.get("sessions") or []):
            if not isinstance(item, dict):
                continue
            session_key = str(item.get("session_key") or "").strip()
            sealed_state = item.get("sealed_state")
            if not session_key or not isinstance(sealed_state, dict):
                continue
            try:
                session_payload = decrypt_json_payload(sealed_state, purpose=_DANXI_PERSISTENCE_PURPOSE)
            except CredentialTransportError as exc:
                logger.warning("Discarding persisted Danxi session %s: %s", session_key, exc.message)
                continue
            restored_state = self._build_state_from_persistence(session_key, session_payload)
            if restored_state is not None:
                restored_sessions[session_key] = restored_state
        with self._lock:
            if restored_sessions:
                self._sessions.update(restored_sessions)
                restored_active_key = str(payload.get("active_session_key") or "").strip()
                if restored_active_key in restored_sessions:
                    self._active_session_key = restored_active_key
                elif not self._active_session_key:
                    self._active_session_key = next(iter(restored_sessions.keys()), "")
            elif self._state_backend is not None and (payload.get("sessions") or payload.get("active_session_key")):
                self._state_backend.save({"active_session_key": "", "sessions": []})

    def _build_state_from_persistence(self, session_key: str, payload: dict[str, Any]) -> _DanxiSessionState | None:
        email = str(payload.get("email") or "").strip()
        password = str(payload.get("password") or "").strip()
        access_token = str(payload.get("access_token") or "").strip()
        if not email or not password or not access_token:
            return None
        state = _DanxiSessionState(
            session_key=session_key,
            email=email,
            password=password,
            use_webvpn=bool(payload.get("use_webvpn")),
            webvpn_cookie=str(payload.get("webvpn_cookie") or "").strip(),
            access_token=access_token,
            refresh_token=str(payload.get("refresh_token") or "").strip(),
            user_profile=payload.get("user_profile") if isinstance(payload.get("user_profile"), dict) else None,
            restored_from_persistence=True,
            restore_validated=False,
        )
        state.http.headers.update({"Accept": "application/json", "User-Agent": "MeetYou-Danxi/1.0"})
        return state

    def _persist_sessions(self) -> None:
        if self._state_backend is None:
            return
        sessions_payload = []
        for session_key, state in self._sessions.items():
            try:
                sessions_payload.append(
                    {
                        "session_key": session_key,
                        "sealed_state": encrypt_json_payload(self._serialize_state_for_persistence(state), purpose=_DANXI_PERSISTENCE_PURPOSE),
                    }
                )
            except CredentialTransportError as exc:
                raise DanxiError(f"无法安全持久化 Danxi/WebVPN 登录态：{exc.message}") from exc
        self._state_backend.save(
            {
                "active_session_key": self._active_session_key,
                "sessions": sessions_payload,
            }
        )

    def _serialize_state_for_persistence(self, state: _DanxiSessionState) -> dict[str, Any]:
        return {
            "email": state.email,
            "password": state.password,
            "use_webvpn": state.use_webvpn,
            "webvpn_cookie": state.webvpn_cookie,
            "access_token": state.access_token,
            "refresh_token": state.refresh_token,
            "user_profile": state.user_profile or {},
        }

    def _invalidate_session(self, session_key: str, *, message: str = "") -> None:
        with self._lock:
            state = self._sessions.pop(session_key, None)
            if state is not None:
                state.http.close()
            if self._active_session_key == session_key:
                self._active_session_key = next(iter(self._sessions.keys()), "")
        self._persist_sessions()
        if message:
            logger.info("Danxi session invalidated for %s: %s", session_key, message)

    def _post_auth_login(self, state: _DanxiSessionState) -> dict[str, Any]:
        payload = self._request_json(
            "POST",
            f"{self.AUTH_BASE}/login",
            state=state,
            json_body={"email": state.email, "password": state.password},
            include_auth=False,
            retry_on_unauthorized=False,
        )
        if not isinstance(payload, dict):
            raise DanxiError("Danxi 登录返回格式异常。")
        self._update_tokens(state, payload)
        return payload

    def _safe_load_profile(self, state: _DanxiSessionState) -> dict[str, Any] | None:
        try:
            profile = self._request_json("GET", f"{self.API_BASE}/users/me", state=state)
        except Exception:
            return None
        if isinstance(profile, dict):
            state.user_profile = profile
            return profile
        return None

    def _update_tokens(self, state: _DanxiSessionState, payload: dict[str, Any]) -> None:
        access = str(payload.get("access") or payload.get("access_token") or "").strip()
        refresh = str(payload.get("refresh") or payload.get("refresh_token") or "").strip()
        token_payload = payload.get("data")
        if not access and isinstance(token_payload, dict):
            access = str(token_payload.get("access") or token_payload.get("access_token") or "").strip()
            refresh = str(token_payload.get("refresh") or token_payload.get("refresh_token") or "").strip()
        if not access:
            raise DanxiError("Danxi 登录成功但未返回 access token。")
        state.access_token = access
        state.refresh_token = refresh

    def _transport_label(self, state: _DanxiSessionState) -> str:
        if self._is_webvpn_enabled(state) and not self._can_connect_directly():
            return "webvpn"
        return "direct"

    def _is_webvpn_enabled(self, state: _DanxiSessionState, *, direct_connect_available: bool | None = None) -> bool:
        if direct_connect_available is None:
            direct_connect_available = self._can_connect_directly()
        return bool(state.use_webvpn or (state.webvpn_cookie and not direct_connect_available))

    def _can_connect_directly(self) -> bool:
        with self._lock:
            if self._direct_connect_available is not None:
                return self._direct_connect_available
        try:
            response = requests.get(self.DIRECT_CONNECT_TEST_URL, timeout=(1, 1))
            direct_available = response.status_code > 0
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            direct_available = False
        except requests.RequestException:
            direct_available = False
        with self._lock:
            self._direct_connect_available = direct_available
        return direct_available

    def _should_use_webvpn_proxy(self, state: _DanxiSessionState, url: str) -> bool:
        translated = self._translate_url_to_webvpn(url)
        if translated is None:
            return False
        if state.use_webvpn:
            return True
        return bool(state.webvpn_cookie and not self._can_connect_directly())

    def _mark_webvpn_fallback_active(self, state: _DanxiSessionState) -> None:
        if state.use_webvpn:
            return
        state.use_webvpn = True
        self._persist_sessions()

    @staticmethod
    def _resolve_danxi_credentials(email: str = "", password: str = "") -> tuple[str, str]:
        manual_email = str(email or "").strip()
        manual_password = str(password or "").strip()
        if manual_email or manual_password:
            if not manual_email or not manual_password:
                raise DanxiError("Danxi 手动登录需要同时提供 email 和 password。")
            return manual_email, manual_password
        env_email = _first_env("DANXI_MAIL", "MEETYOU_DANXI_EMAIL")
        env_password = _first_env("DANXI_PASSWORD", "MEETYOU_DANXI_PASSWORD")
        return env_email, env_password

    @staticmethod
    def _resolve_stuvpn_credentials() -> tuple[str, str]:
        username = str(os.getenv("STUVPN_FUDAN_USER", "")).strip()
        password = str(os.getenv("STUVPN_FUDAN_PASSWORD", "")).strip()
        return username, password

    def _resolve_default_use_webvpn(self) -> bool:
        if _env_bool("MEETYOU_DANXI_USE_WEBVPN", default=False):
            return True
        username, password = self._resolve_stuvpn_credentials()
        if not username or not password:
            return False
        return not self._can_connect_directly()

    def _refresh_webvpn_cookie_from_env(self, state: _DanxiSessionState) -> bool:
        username, password = self._resolve_stuvpn_credentials()
        if not username or not password:
            return False
        login_session = requests.Session()
        login_session.headers.update({"Accept": "application/json", "User-Agent": "MeetYou-Danxi/1.0"})
        try:
            cookie_header = self._login_webvpn_with_stuvpn(login_session, username, password)
            if not cookie_header:
                return False
        finally:
            login_session.close()
        state.webvpn_cookie = cookie_header
        state.use_webvpn = True
        self._persist_sessions()
        return True

    def _login_webvpn_with_stuvpn(self, session: requests.Session, username: str, password: str) -> str:
        login_page = session.get(
            self.WEBVPN_LOGIN_URL,
            headers=self._webvpn_browser_headers(),
            timeout=self._WEBVPN_LOGIN_PAGE_TIMEOUT,
            allow_redirects=True,
        )
        login_page.raise_for_status()
        lck, entity_id = self._extract_webvpn_login_context_from_page(login_page.url, login_page.text)

        auth_methods = self._post_webvpn_idp_json(
            session,
            "/authn/queryAuthMethods",
            {"lck": lck, "entityId": entity_id},
        )
        chains = auth_methods.get("data") if isinstance(auth_methods.get("data"), list) else []
        password_chain = next(
            (
                item
                for item in chains
                if isinstance(item, dict) and "userAndPwd" in (item.get("moduleCodes") or [])
            ),
            None,
        )
        if not isinstance(password_chain, dict):
            raise DanxiError("当前 WebVPN 登录链路未返回可用的用户名密码认证方式。")

        auth_chain_code = str(password_chain.get("authChainCode") or "").strip()
        verify_code_state = self._post_webvpn_idp_json(
            session,
            "/authn/verifyCodeIsNeed",
            {
                "lang": "zh_CN",
                "loginName": username,
                "chainCode": auth_chain_code,
                "authModuleCode": "userAndPwd",
            },
        )
        if bool(verify_code_state.get("result")):
            raise DanxiError("当前 WebVPN 登录需要额外验证码，暂不支持自动完成。")

        public_key_payload = self._post_webvpn_idp_json(session, "/authn/getJsPublicKey", {})
        public_key = str(public_key_payload.get("data") or "").strip()
        if not public_key:
            raise DanxiError("当前 WebVPN 登录未返回可用的加密公钥。")

        auth_execute = self._post_webvpn_idp_json(
            session,
            "/authn/authExecute",
            {
                "authModuleCode": "userAndPwd",
                "authChainCode": auth_chain_code,
                "entityId": auth_methods.get("entityId") or entity_id,
                "requestType": auth_methods.get("requestType") or "chain_type",
                "lck": auth_methods.get("lck") or lck,
                "authPara": {
                    "loginName": username,
                    "password": self._encrypt_webvpn_password(password, public_key),
                    "verifyCode": "",
                },
            },
        )
        if str(auth_execute.get("code") or "") != "200":
            raise DanxiError(f"WebVPN 登录失败：authExecute 返回 {auth_execute.get('code')}")
        login_token = str(auth_execute.get("loginToken") or "").strip()
        if not login_token:
            raise DanxiError("WebVPN 登录失败：缺少 loginToken。")

        auth_center = session.post(
            f"{self.WEBVPN_IDP_BASE}/authCenter/authnEngine?locale=zh-CN",
            data={"loginToken": login_token},
            headers={"User-Agent": self._webvpn_browser_headers()["User-Agent"]},
            timeout=self._WEBVPN_REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        auth_center.raise_for_status()
        redirect_url = self._extract_webvpn_auth_center_redirect(auth_center.text, auth_center.url)
        final_page = session.get(
            redirect_url,
            headers=self._webvpn_browser_headers(),
            timeout=self._WEBVPN_REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        final_page.raise_for_status()
        cookie_header = self._build_webvpn_cookie_header(session)
        if not cookie_header:
            raise DanxiError("WebVPN 登录成功，但未生成可用的 WebVPN cookie。")
        return cookie_header

    @staticmethod
    def _webvpn_browser_headers() -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        }

    @staticmethod
    def _parse_webvpn_login_context(redirect_url: str) -> tuple[str, str]:
        parsed_url = urlparse(redirect_url)
        candidates = []
        fragment = parsed_url.fragment or ""
        _, _, fragment_query = fragment.partition("?")
        if fragment_query:
            candidates.append(fragment_query)
        if parsed_url.query:
            candidates.append(parsed_url.query)
        for query in candidates:
            parsed = parse_qs(query)
            lck = str((parsed.get("lck") or [""])[0]).strip()
            entity_id = str((parsed.get("entityId") or [""])[0]).strip()
            if lck and entity_id:
                return lck, entity_id
        raise DanxiError("WebVPN 登录页缺少必要的登录上下文。")

    @classmethod
    def _extract_webvpn_login_context_from_page(cls, redirect_url: str, html: str = "") -> tuple[str, str]:
        try:
            return cls._parse_webvpn_login_context(redirect_url)
        except DanxiError:
            pass
        text = str(html or "")
        lck_match = re.search(r'(?:"|\b)lck(?:"|\b)\s*[:=]\s*"?(context_[^"&<\s]+)', text)
        entity_match = re.search(r'(?:"|\b)entityId(?:"|\b)\s*[:=]\s*"?(https://[^"&<\s]+)', text)
        if lck_match and entity_match:
            return lck_match.group(1).strip(), entity_match.group(1).strip()
        raise DanxiError("WebVPN 登录页缺少必要的登录上下文。")

    def _post_webvpn_idp_json(self, session: requests.Session, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = session.post(
            f"{self.WEBVPN_IDP_BASE}{path}",
            json=payload,
            headers=self._webvpn_browser_headers(),
            timeout=self._WEBVPN_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise DanxiError(f"WebVPN 登录返回了异常响应：{path}")
        return data

    @staticmethod
    def _encrypt_webvpn_password(password: str, public_key_b64: str) -> str:
        public_key = RSA.import_key(base64.b64decode(public_key_b64))
        cipher = PKCS1_v1_5.new(public_key)
        encrypted = cipher.encrypt(password.encode("utf-8"))
        return base64.b64encode(encrypted).decode("ascii")

    @staticmethod
    def _extract_webvpn_auth_center_redirect(html: str, base_url: str) -> str:
        marker = 'locationValue = "'
        start = html.find(marker)
        if start >= 0:
            start += len(marker)
            end = html.find('"', start)
            if end > start:
                return urljoin(base_url, html[start:end].replace("&amp;", "&"))

        action_marker = 'form id ="logon" method = "GET" action="'
        action_start = html.find(action_marker)
        ticket_marker = 'name="ticket" value="'
        ticket_start = html.find(ticket_marker)
        if action_start >= 0 and ticket_start >= 0:
            action_start += len(action_marker)
            action_end = html.find('"', action_start)
            ticket_start += len(ticket_marker)
            ticket_end = html.find('"', ticket_start)
            if action_end > action_start and ticket_end > ticket_start:
                action = html[action_start:action_end].replace("&amp;", "&")
                ticket = html[ticket_start:ticket_end].replace("&amp;", "&")
                separator = "&" if "?" in action else "?"
                return f"{action}{separator}ticket={ticket}"

        raise DanxiError("WebVPN 登录完成后未找到可继续跳转的凭据。")

    def _build_webvpn_cookie_header(self, session: requests.Session) -> str:
        cookie_parts: list[str] = []
        for cookie in session.cookies:
            if self.WEBVPN_HOST not in str(cookie.domain or ""):
                continue
            cookie_parts.append(f"{cookie.name}={cookie.value}")
        return "; ".join(cookie_parts)

    def _request_timeout(self, *, proxied: bool) -> tuple[int, int]:
        return self._WEBVPN_REQUEST_TIMEOUT if proxied else self._DIRECT_REQUEST_TIMEOUT

    def _translate_url_to_webvpn(self, url: str) -> str | None:
        parsed = urlparse(url)
        scheme = parsed.scheme or "http"
        if scheme not in {"http", "https"}:
            return None
        if parsed.hostname not in self._WEBVPN_ALLOWED_HOSTS:
            return None
        formatted_host = parsed.hostname if ":" not in parsed.hostname else f"[{parsed.hostname}]"
        if parsed.hostname in self._host_cache:
            encoded_host = self._host_cache[parsed.hostname]
        else:
            padded = formatted_host
            remainder = len(padded) % 16
            if remainder:
                padded += "0" * (16 - remainder)
            cipher = AES.new(self._WEBVPN_KEY, AES.MODE_CFB, iv=self._WEBVPN_KEY, segment_size=128)
            encrypted = cipher.encrypt(padded.encode("utf-8")).hex()
            encoded_host = self._WEBVPN_KEY.hex() + encrypted[: 2 * len(formatted_host)]
            self._host_cache[parsed.hostname] = encoded_host
        segment = f"{scheme}-{parsed.port}" if parsed.port else scheme
        path = parsed.path or ""
        if parsed.query:
            path = f"{path}?{parsed.query}"
        if parsed.fragment:
            path = f"{path}#{parsed.fragment}"
        return f"https://{self.WEBVPN_HOST}/{segment}/{encoded_host}{path}"

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        state: _DanxiSessionState,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        include_auth: bool = True,
        retry_on_unauthorized: bool = True,
    ) -> Any:
        response = self._request(
            method,
            url,
            state=state,
            params=params,
            json_body=json_body,
            include_auth=include_auth,
            retry_on_unauthorized=retry_on_unauthorized,
        )
        try:
            return response.json()
        except ValueError as exc:
            raise DanxiError(f"Danxi 返回了非 JSON 响应: {response.text[:200]}") from exc

    def _request(
        self,
        method: str,
        url: str,
        *,
        state: _DanxiSessionState,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        include_auth: bool = True,
        retry_on_unauthorized: bool = True,
        retry_on_webvpn_refresh: bool = True,
    ) -> requests.Response:
        target_url = url
        headers = {"Accept": "application/json"}
        translated = self._translate_url_to_webvpn(url)
        proxied = self._should_use_webvpn_proxy(state, url)
        if proxied and not state.webvpn_cookie and retry_on_webvpn_refresh:
            self._refresh_webvpn_cookie_from_env(state)
        if proxied:
            if translated is None:
                raise DanxiError(f"当前 URL 不支持通过 WebVPN 代理: {url}")
            target_url = translated
            if state.webvpn_cookie:
                headers["Cookie"] = state.webvpn_cookie
        if include_auth:
            if not state.access_token:
                raise DanxiError("Danxi 会话缺少 access token，请先登录。")
            headers["Authorization"] = f"Bearer {state.access_token}"
        try:
            response = state.http.request(
                method.upper(),
                target_url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=self._request_timeout(proxied=proxied),
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            if proxied and retry_on_webvpn_refresh and self._refresh_webvpn_cookie_from_env(state):
                return self._request(
                    method,
                    url,
                    state=state,
                    params=params,
                    json_body=json_body,
                    include_auth=include_auth,
                    retry_on_unauthorized=retry_on_unauthorized,
                    retry_on_webvpn_refresh=False,
                )
            if not proxied and translated is not None and state.webvpn_cookie:
                self._mark_webvpn_fallback_active(state)
                headers = {"Accept": "application/json", "Cookie": state.webvpn_cookie}
                if include_auth:
                    headers["Authorization"] = f"Bearer {state.access_token}"
                try:
                    response = state.http.request(
                        method.upper(),
                        translated,
                        params=params,
                        json=json_body,
                        headers=headers,
                        timeout=self._request_timeout(proxied=True),
                        allow_redirects=True,
                    )
                    proxied = True
                except requests.RequestException as webvpn_exc:
                    if retry_on_webvpn_refresh and self._refresh_webvpn_cookie_from_env(state):
                        return self._request(
                            method,
                            url,
                            state=state,
                            params=params,
                            json_body=json_body,
                            include_auth=include_auth,
                            retry_on_unauthorized=retry_on_unauthorized,
                            retry_on_webvpn_refresh=False,
                        )
                    raise DanxiError(f"Danxi 请求失败: {webvpn_exc}") from webvpn_exc
            else:
                raise DanxiError(f"Danxi 请求失败: {exc}") from exc
        if proxied:
            self._mark_webvpn_fallback_active(state)
        if proxied and self._response_requires_webvpn_login(response):
            if retry_on_webvpn_refresh and self._refresh_webvpn_cookie_from_env(state):
                return self._request(
                    method,
                    url,
                    state=state,
                    params=params,
                    json_body=json_body,
                    include_auth=include_auth,
                    retry_on_unauthorized=retry_on_unauthorized,
                    retry_on_webvpn_refresh=False,
                )
            raise DanxiError("Danxi 已切到 WebVPN 路由，但当前没有有效的 WebVPN 登录态。请提供可用的 WebVPN cookie。")
        if response.status_code == 401 and include_auth and retry_on_unauthorized:
            try:
                self._post_auth_login(state)
                self._persist_sessions()
            except Exception as exc:
                self._invalidate_session(
                    state.session_key,
                    message="Danxi token 已失效且重新登录失败。",
                )
                raise DanxiError("Danxi 登录态已失效，请重新登录。") from exc
            return self._request(
                method,
                url,
                state=state,
                params=params,
                json_body=json_body,
                include_auth=include_auth,
                retry_on_unauthorized=False,
            )
        if response.status_code >= 400:
            detail = self._extract_error_detail(response)
            raise DanxiError(f"Danxi API {response.status_code}: {detail}")
        return response

    def _response_requires_webvpn_login(self, response: requests.Response) -> bool:
        final_url = str(response.url or "")
        lowered_url = final_url.lower()
        if final_url.startswith(self.WEBVPN_LOGIN_PREFIX) or "id.fudan.edu.cn" in lowered_url:
            return True
        if "authserver/login" in lowered_url or "cas_login=true" in lowered_url:
            return True
        content_type = str(response.headers.get("Content-Type") or "").lower()
        body = str(response.text or "")
        lowered_body = body[:2000].lower()
        if "html" in content_type or lowered_body.startswith("<!doctype html") or "<html" in lowered_body:
            if "authserver" in lowered_body or "资源访问控制系统" in body[:500]:
                return True
        return False

    def _extract_error_detail(self, response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:200] or response.reason
        if isinstance(payload, dict):
            for key in ("message", "detail", "error"):
                value = payload.get(key)
                if value:
                    return str(value)
        return str(payload)[:200]

    def _build_tags_payload(self, tag_ids: list[int], tag_names: list[str]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for index, tag_id in enumerate(tag_ids):
            result.append(
                {
                    "tag_id": int(tag_id),
                    "temperature": 0,
                    "name": tag_names[index] if index < len(tag_names) else "",
                }
            )
        return result


def get_shared_danxi_tools() -> DanxiTools:
    global _SHARED_DANXI_TOOLS
    if _SHARED_DANXI_TOOLS is None:
        _SHARED_DANXI_TOOLS = DanxiTools()
    return _SHARED_DANXI_TOOLS
