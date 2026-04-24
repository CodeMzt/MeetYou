from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from desktop_agent.backend import DesktopAgentBackend
from desktop_agent.config import DesktopAgentConfig


class DesktopAgentBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_start_callback_starts_runtime_only_once(self):
        runtime = mock.Mock()
        runtime.run = mock.AsyncMock(side_effect=self._wait_forever)
        runtime.stop = mock.Mock()
        api_server = mock.Mock()
        api_server.start = mock.AsyncMock()
        api_server.stop = mock.AsyncMock()

        with mock.patch("desktop_agent.backend.DesktopAgentRuntime", return_value=runtime):
            with mock.patch("desktop_agent.backend.DesktopApiServer", return_value=api_server):
                backend = DesktopAgentBackend(DesktopAgentConfig())

        await backend.ensure_runtime_started()
        await asyncio.sleep(0)
        first_task = backend._runtime_task
        await backend.ensure_runtime_started()
        await asyncio.sleep(0)

        self.assertIsNotNone(first_task)
        self.assertIs(backend._runtime_task, first_task)
        self.assertEqual(runtime.run.await_count, 1)

        await backend._stop_runtime()
        runtime.stop.assert_called_once_with()

    async def test_run_stops_runtime_and_api_server_on_shutdown(self):
        runtime = mock.Mock()
        runtime.run = mock.AsyncMock(side_effect=self._wait_forever)
        runtime.stop = mock.Mock()
        api_server = mock.Mock()
        api_server.start = mock.AsyncMock()
        api_server.stop = mock.AsyncMock()

        with mock.patch("desktop_agent.backend.DesktopAgentRuntime", return_value=runtime):
            with mock.patch("desktop_agent.backend.DesktopApiServer", return_value=api_server):
                backend = DesktopAgentBackend(DesktopAgentConfig())

        await backend.ensure_runtime_started()
        run_task = asyncio.create_task(backend.run())
        await asyncio.sleep(0)

        run_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await run_task

        runtime.stop.assert_called_once_with()
        api_server.start.assert_awaited_once_with()
        api_server.stop.assert_awaited_once_with()

    async def test_run_without_local_bridge_starts_runtime_immediately(self):
        runtime = mock.Mock()
        runtime.run = mock.AsyncMock(side_effect=self._wait_forever)
        runtime.stop = mock.Mock()

        with mock.patch("desktop_agent.backend.DesktopAgentRuntime", return_value=runtime):
            backend = DesktopAgentBackend(DesktopAgentConfig(local_bridge_enabled=False))

        run_task = asyncio.create_task(backend.run())
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        self.assertEqual(runtime.run.await_count, 1)

        run_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await run_task

        runtime.stop.assert_called_once_with()

    async def _wait_forever(self):
        await asyncio.Future()


if __name__ == "__main__":
    unittest.main()
