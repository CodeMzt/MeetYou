from __future__ import annotations

import asyncio
import contextlib

from desktop_client.config import DesktopClientConfig
from desktop_client.desktop_api import DesktopApiServer
from desktop_client.runtime import DesktopClientRuntime


class DesktopClientBackend:
    def __init__(self, config: DesktopClientConfig):
        self.config = config
        self.runtime = DesktopClientRuntime(config)
        self._runtime_task: asyncio.Task | None = None
        self._runtime_start_lock = asyncio.Lock()
        self.api_server = (
            DesktopApiServer(config, on_client_session_created=self.ensure_runtime_started)
            if config.local_bridge_enabled
            else None
        )

    async def ensure_runtime_started(self) -> None:
        async with self._runtime_start_lock:
            if self._runtime_task is not None and not self._runtime_task.done():
                return
            self._runtime_task = asyncio.create_task(self.runtime.run())

    async def _stop_runtime(self) -> None:
        if self._runtime_task is None:
            return
        self.runtime.stop()
        self._runtime_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._runtime_task
        self._runtime_task = None

    async def run(self) -> None:
        if self.api_server is not None:
            await self.api_server.start()
        else:
            await self.ensure_runtime_started()
        try:
            await asyncio.Future()
        finally:
            await self._stop_runtime()
            if self.api_server is not None:
                await self.api_server.stop()
