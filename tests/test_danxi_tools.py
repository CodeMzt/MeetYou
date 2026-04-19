import os
import requests
import unittest
from unittest.mock import patch

from tools.danxi_tools import DanxiError, DanxiTools, _DanxiSessionState


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, url="https://forum.fduhole.com/api/test", text=""):
        self.status_code = status_code
        self._payload = payload
        self.url = url
        self.text = text or ""
        self.ok = 200 <= status_code < 400
        self.reason = "OK" if self.ok else "ERROR"

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self._responses:
            raise AssertionError("No fake responses left")
        next_response = self._responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response

    def close(self):
        return None


class _MemoryStateBackend:
    def __init__(self):
        self.payload = {}

    def load(self):
        return dict(self.payload)

    def save(self, payload):
        self.payload = dict(payload)


class DanxiToolsTests(unittest.TestCase):
    def test_login_and_list_posts_uses_cached_session(self):
        tools = DanxiTools()
        tools._direct_connect_available = True

        def _fake_login(state):
            state.access_token = "token-a"
            state.refresh_token = "token-r"
            return {"access": "token-a", "refresh": "token-r"}

        with patch.object(DanxiTools, "_post_auth_login", side_effect=_fake_login):
            with patch.object(DanxiTools, "_safe_load_profile", return_value={"user_id": 7, "email": "user@example.com"}):
                login_payload = tools.danxi_login("user@example.com", "secret123")

        with patch.object(DanxiTools, "_request_json", return_value=[{"hole_id": 101, "content": "hello"}]) as request_json:
            posts = tools.danxi_list_posts(length=5)

        self.assertEqual(login_payload["session_key"], "default")
        self.assertEqual(posts["count"], 1)
        self.assertEqual(posts["items"][0]["hole_id"], 101)
        self.assertEqual(tools._active_session_key, "default")
        self.assertEqual(tools._sessions["default"].access_token, "token-a")
        request_json.assert_called_once()

    def test_list_posts_for_division_uses_time_cursor_offset(self):
        tools = DanxiTools()
        state = _DanxiSessionState(
            session_key="default",
            email="user@example.com",
            password="secret",
            use_webvpn=False,
            webvpn_cookie="",
            http=_FakeSession([]),
            access_token="token-old",
        )
        tools._sessions["default"] = state
        tools._active_session_key = "default"

        with patch.object(DanxiTools, "_request_json", return_value=[{"hole_id": 201, "content": "hello"}]) as request_json:
            tools.danxi_list_posts(division_id=2, start_time="2026-04-15T10:00:00Z", length=5)

        request_json.assert_called_once()
        params = request_json.call_args.kwargs["params"]
        self.assertEqual(params["division_id"], 2)
        self.assertEqual(params["length"], 5)
        self.assertEqual(params["offset"], "2026-04-15T10:00:00Z")
        self.assertNotIn("start_time", params)

    def test_request_relogs_on_unauthorized(self):
        fake_http = _FakeSession(
            [
                _FakeResponse(status_code=401, payload={"message": "expired"}),
                _FakeResponse(payload={"access": "token-new"}),
                _FakeResponse(payload=[{"division_id": 1, "name": "综合"}]),
            ]
        )
        tools = DanxiTools()
        tools._direct_connect_available = True
        state = _DanxiSessionState(
            session_key="default",
            email="user@example.com",
            password="secret",
            use_webvpn=False,
            webvpn_cookie="",
            http=fake_http,
            access_token="token-old",
        )
        tools._sessions["default"] = state
        tools._active_session_key = "default"

        payload = tools.danxi_list_divisions()

        self.assertEqual(payload["count"], 1)
        self.assertEqual(state.access_token, "token-new")
        self.assertEqual(fake_http.calls[1]["url"], f"{tools.AUTH_BASE}/login")

    def test_webvpn_translation_matches_expected_shape(self):
        tools = DanxiTools()
        translated = tools._translate_url_to_webvpn("https://forum.fduhole.com/api/holes")
        self.assertIsNotNone(translated)
        self.assertTrue(translated.startswith("https://webvpn.fudan.edu.cn/https/"))
        self.assertTrue(translated.endswith("/api/holes"))

    def test_request_uses_webvpn_cookie_automatically_when_direct_is_unavailable(self):
        fake_http = _FakeSession([_FakeResponse(payload=[{"division_id": 1, "name": "综合"}])])
        tools = DanxiTools()
        tools._direct_connect_available = False
        state = _DanxiSessionState(
            session_key="default",
            email="user@example.com",
            password="secret",
            use_webvpn=False,
            webvpn_cookie="vpn=ok",
            http=fake_http,
            access_token="token-old",
        )
        tools._sessions["default"] = state
        tools._active_session_key = "default"

        payload = tools.danxi_list_divisions()

        self.assertEqual(payload["count"], 1)
        self.assertTrue(state.use_webvpn)
        self.assertTrue(fake_http.calls[0]["url"].startswith("https://webvpn.fudan.edu.cn/https/"))
        self.assertEqual(fake_http.calls[0]["headers"]["Cookie"], "vpn=ok")

    def test_request_retries_with_webvpn_cookie_when_direct_request_fails(self):
        fake_http = _FakeSession(
            [
                requests.exceptions.ConnectionError("direct down"),
                _FakeResponse(payload=[{"division_id": 1, "name": "综合"}], url="https://webvpn.fudan.edu.cn/https/demo/api"),
            ]
        )
        tools = DanxiTools()
        tools._direct_connect_available = True
        state = _DanxiSessionState(
            session_key="default",
            email="user@example.com",
            password="secret",
            use_webvpn=False,
            webvpn_cookie="vpn=ok",
            http=fake_http,
            access_token="token-old",
        )
        tools._sessions["default"] = state
        tools._active_session_key = "default"

        payload = tools.danxi_list_divisions()

        self.assertEqual(payload["count"], 1)
        self.assertTrue(state.use_webvpn)
        self.assertEqual(fake_http.calls[0]["url"], f"{tools.API_BASE}/divisions")
        self.assertTrue(fake_http.calls[1]["url"].startswith("https://webvpn.fudan.edu.cn/https/"))
        self.assertEqual(fake_http.calls[1]["headers"]["Cookie"], "vpn=ok")

    def test_persists_and_restores_encrypted_danxi_session_state(self):
        backend = _MemoryStateBackend()
        tools = DanxiTools()
        tools._direct_connect_available = True
        with patch.dict(os.environ, {"MEETYOU_CREDENTIAL_SECRET": "unit-test-secret"}, clear=False):
            tools.set_state_backend(backend)

            def _fake_login(state):
                state.access_token = "token-a"
                state.refresh_token = "token-r"
                return {"access": "token-a", "refresh": "token-r"}

            with patch.object(DanxiTools, "_post_auth_login", side_effect=_fake_login), patch.object(
                DanxiTools,
                "_safe_load_profile",
                return_value={"user_id": 7, "email": "user@example.com"},
            ):
                tools.danxi_login("user@example.com", "secret123", use_webvpn=True, webvpn_cookie="vpn=ok")

            self.assertIn("sessions", backend.payload)
            self.assertNotIn("secret123", str(backend.payload))
            self.assertNotIn("vpn=ok", str(backend.payload))

            restored = DanxiTools()
            restored._direct_connect_available = True
            with patch.object(DanxiTools, "_request_json", return_value={"user_id": 7, "email": "user@example.com"}):
                restored.set_state_backend(backend)
                payload = restored.danxi_get_session_status()

        self.assertTrue(payload["logged_in"])
        self.assertEqual(payload["email"], "user@example.com")
        self.assertEqual(restored._sessions["default"].password, "secret123")
        self.assertTrue(restored._sessions["default"].restore_validated)

    def test_invalid_restored_session_is_cleared(self):
        backend = _MemoryStateBackend()
        tools = DanxiTools()
        tools._direct_connect_available = True
        with patch.dict(os.environ, {"MEETYOU_CREDENTIAL_SECRET": "unit-test-secret"}, clear=False):
            tools.set_state_backend(backend)

            def _fake_login(state):
                state.access_token = "token-a"
                return {"access": "token-a", "refresh": ""}

            with patch.object(DanxiTools, "_post_auth_login", side_effect=_fake_login), patch.object(
                DanxiTools,
                "_safe_load_profile",
                return_value={"user_id": 7, "email": "user@example.com"},
            ):
                tools.danxi_login("user@example.com", "secret123")

            restored = DanxiTools()
            restored._direct_connect_available = True
            restored.set_state_backend(backend)
            with patch.object(DanxiTools, "_request_json", side_effect=DanxiError("Danxi API 401: expired token")):
                with self.assertRaises(DanxiError) as error_context:
                    restored.danxi_get_session_status()

        self.assertIn("已失效", str(error_context.exception))
        self.assertFalse(restored._sessions)
        self.assertEqual(backend.payload.get("sessions"), [])

    def test_set_webvpn_cookie_updates_session_status(self):
        tools = DanxiTools()
        tools._direct_connect_available = False
        state = _DanxiSessionState(
            session_key="default",
            email="user@example.com",
            password="secret",
            use_webvpn=False,
            webvpn_cookie="",
            http=_FakeSession([]),
            access_token="token-old",
        )
        tools._sessions["default"] = state
        tools._active_session_key = "default"

        status = tools.danxi_set_webvpn_cookie("a=1; b=2")

        self.assertTrue(status["has_webvpn_cookie"])
        self.assertEqual(status["transport"], "webvpn")
        self.assertTrue(status["webvpn_required"])

    def test_session_status_treats_existing_webvpn_cookie_as_available_fallback(self):
        tools = DanxiTools()
        tools._direct_connect_available = False
        state = _DanxiSessionState(
            session_key="default",
            email="user@example.com",
            password="secret",
            use_webvpn=False,
            webvpn_cookie="vpn=ok",
            http=_FakeSession([]),
            access_token="token-old",
        )
        tools._sessions["default"] = state
        tools._active_session_key = "default"

        status = tools.danxi_get_session_status()

        self.assertTrue(status["webvpn_enabled"])
        self.assertTrue(status["webvpn_required"])
        self.assertEqual(status["transport"], "webvpn")

    def test_delete_reply_requires_confirmation(self):
        tools = DanxiTools()
        with self.assertRaises(DanxiError):
            tools.danxi_delete_reply(123)

    def test_get_user_profile_reuses_cached_profile_and_session_state(self):
        tools = DanxiTools()
        tools._direct_connect_available = True
        state = _DanxiSessionState(
            session_key="default",
            email="user@example.com",
            password="secret",
            use_webvpn=False,
            webvpn_cookie="",
            http=_FakeSession([]),
            access_token="token-old",
            user_profile={"user_id": 7, "nickname": "阿明"},
        )
        tools._sessions["default"] = state
        tools._active_session_key = "default"

        payload = tools.danxi_get_user_profile()

        self.assertTrue(payload["logged_in"])
        self.assertEqual(payload["profile"]["nickname"], "阿明")
        self.assertEqual(payload["transport"], "direct")

    def test_summarize_post_builds_compact_summary_from_post_and_floors(self):
        tools = DanxiTools()
        with patch.object(
            DanxiTools,
            "danxi_get_post",
            return_value={"hole": {"hole_id": 101, "title": "宿舍报修", "content": "宿舍空调坏了，想问大家怎么报修。", "reply": 2}},
        ), patch.object(
            DanxiTools,
            "danxi_list_floors",
            return_value={
                "hole_id": 101,
                "count": 2,
                "items": [
                    {"floor_id": 1, "anonyname": "洞友A", "content": "先去企业微信里提工单。"},
                    {"floor_id": 2, "anonyname": "洞友B", "content": "宿管阿姨那边也可以登记一下。"},
                ],
            },
        ):
            payload = tools.danxi_summarize_post(101)

        self.assertEqual(payload["hole_id"], 101)
        self.assertIn("宿舍空调坏了", payload["summary"])
        self.assertEqual(payload["floor_count"], 2)
        self.assertGreaterEqual(payload["participant_count"], 2)
        self.assertTrue(payload["reply_highlights"])


if __name__ == "__main__":
    unittest.main()
