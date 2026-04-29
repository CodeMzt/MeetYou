from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from core.event_bus import EventBus
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway


class GatewayStartupV4Tests(unittest.IsolatedAsyncioTestCase):
    async def test_start_waits_until_uvicorn_reports_ready(self):
        observed = {"returned_after_ready": False}

        class _FakeServer:
            def __init__(self, _config):
                self.started = False
                self.should_exit = False

            async def serve(self):
                await asyncio.sleep(0.03)
                self.started = True
                while not self.should_exit:
                    await asyncio.sleep(0.01)

        gateway = FastAPIGateway(EventBus(), SessionManager(), access_token="test-token")

        with (
            patch("gateway.api.uvicorn.Config", return_value=object()),
            patch("gateway.api.uvicorn.Server", _FakeServer),
        ):
            await gateway.start(host="127.0.0.1", port=38080)
            observed["returned_after_ready"] = bool(gateway._server.started)
            await gateway.stop()

        self.assertTrue(observed["returned_after_ready"])


if __name__ == "__main__":
    unittest.main()
