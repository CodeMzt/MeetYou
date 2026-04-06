from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar


logger = logging.getLogger("meetyou.session_actor")

PayloadT = TypeVar("PayloadT")
_STOP = object()


class _SessionActor(Generic[PayloadT]):
    def __init__(
        self,
        session_id: str,
        handler: Callable[[PayloadT], Awaitable[None]],
    ):
        self.session_id = session_id
        self._handler = handler
        self._queue: asyncio.Queue[PayloadT | object] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._closed = False

    async def enqueue(self, payload: PayloadT) -> None:
        if self._closed:
            raise RuntimeError(f"Session actor already closed: {self.session_id}")
        self._ensure_started()
        await self._queue.put(payload)

    async def join(self) -> None:
        await self._queue.join()

    async def stop(self) -> None:
        if self._closed:
            if self._task is not None:
                await self._task
            return
        self._closed = True
        self._ensure_started()
        await self._queue.put(_STOP)
        if self._task is not None:
            await self._task

    def _ensure_started(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"session-actor:{self.session_id}")

    async def _run(self) -> None:
        while True:
            payload = await self._queue.get()
            try:
                if payload is _STOP:
                    return
                await self._handler(payload)
            except Exception:
                logger.exception("Session actor failed while handling session %s", self.session_id)
            finally:
                self._queue.task_done()


class SessionActorRuntime(Generic[PayloadT]):
    def __init__(self, handler: Callable[[PayloadT], Awaitable[None]]):
        self._handler = handler
        self._actors: dict[str, _SessionActor[PayloadT]] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def submit(self, session_id: str, payload: PayloadT) -> None:
        async with self._lock:
            if self._closed:
                raise RuntimeError("Session actor runtime is closed")
            actor = self._actors.get(session_id)
            if actor is None:
                actor = _SessionActor(session_id, self._handler)
                self._actors[session_id] = actor
        await actor.enqueue(payload)

    async def join(self, session_id: str = "") -> None:
        if session_id:
            actor = self._actors.get(session_id)
            if actor is not None:
                await actor.join()
            return
        actors = list(self._actors.values())
        if actors:
            await asyncio.gather(*(actor.join() for actor in actors))

    async def shutdown(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            actors = list(self._actors.values())
            self._actors = {}
        if actors:
            await asyncio.gather(*(actor.stop() for actor in actors))

    def active_sessions(self) -> list[str]:
        return sorted(self._actors.keys())
