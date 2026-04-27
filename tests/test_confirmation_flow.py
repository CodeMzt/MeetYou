import asyncio
import unittest

from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway
from tools import system_tools


class ConfirmationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_confirmation_response_unblocks_waiter(self):
        bus = EventBus()

        wait_task = asyncio.create_task(
            bus.request_confirmation(
                "请求执行危险命令",
                timeout=1.0,
                session_id="web:test-session",
            )
        )

        await asyncio.sleep(0)

        resolved = bus.submit_confirmation_response(
            True,
            request_id=bus.pending_request_id,
            session_id="web:test-session",
        )

        self.assertTrue(resolved)
        self.assertTrue(await wait_task)


class _GatewayConfirmEventBus:
    def __init__(self):
        self.inbound_queue = asyncio.Queue()
        self.calls: list[tuple[bool, str, str, str, str]] = []

    def submit_confirmation_response(
        self,
        accepted: bool,
        request_id: str = "",
        session_id: str = "",
        client_id: str = "",
        approval_id: str = "",
        reason: str = "",
    ) -> bool:
        del reason
        self.calls.append((accepted, request_id, session_id, client_id, approval_id))
        return True


class GatewayConfirmResponseTests(unittest.TestCase):
    def test_http_confirm_response_resolves_immediately(self):
        bus = _GatewayConfirmEventBus()
        gateway = FastAPIGateway(bus, SessionManager(), access_token="ws-token")
        with TestClient(gateway.app) as client:
            response = client.post(
                "/client/sessions/web:test/confirm-response",
                headers={"Authorization": "Bearer ws-token"},
                json={
                    "action": "confirm_response",
                    "client_id": "desktop",
                    "request_id": "req-123",
                    "accepted": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["accepted"])
        self.assertEqual(payload["session_id"], "web:test")
        self.assertEqual(bus.calls, [(True, "req-123", "web:test", "desktop", "")])
        self.assertTrue(bus.inbound_queue.empty())


class SystemToolsPolicyTests(unittest.TestCase):
    def setUp(self):
        self._original_policy = system_tools._cmd_policy

    def tearDown(self):
        system_tools._cmd_policy = self._original_policy

    def test_builtin_blacklist_patterns_cover_common_dangerous_commands(self):
        system_tools._cmd_policy = {"mode": "blacklist", "blacklist_patterns": []}

        status, _ = system_tools._check_command_safety("Remove-Item -Recurse -Force .\\tmp")
        self.assertEqual(status, "needs_confirm")

        status, _ = system_tools._check_command_safety("shutdown /s /t 0")
        self.assertEqual(status, "needs_confirm")

        status, _ = system_tools._check_command_safety("git reset --hard HEAD")
        self.assertEqual(status, "needs_confirm")


if __name__ == "__main__":
    unittest.main()
