import asyncio
import unittest

from core.session_actor import SessionActorRuntime


class SessionActorRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_session_tasks_run_in_submission_order(self):
        release_first = asyncio.Event()
        second_started = asyncio.Event()
        order: list[tuple[str, str]] = []

        async def handler(payload: str):
            order.append(("start", payload))
            if payload == "first":
                await release_first.wait()
            else:
                second_started.set()
            order.append(("end", payload))

        runtime = SessionActorRuntime(handler)
        try:
            await runtime.submit("session-1", "first")
            await runtime.submit("session-1", "second")
            await asyncio.sleep(0.05)
            self.assertFalse(second_started.is_set())
            release_first.set()
            await asyncio.wait_for(runtime.join("session-1"), timeout=1.0)
            self.assertEqual(
                order,
                [
                    ("start", "first"),
                    ("end", "first"),
                    ("start", "second"),
                    ("end", "second"),
                ],
            )
        finally:
            await runtime.shutdown()

    async def test_different_sessions_can_run_in_parallel(self):
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        release = asyncio.Event()
        completed: list[str] = []

        async def handler(payload: str):
            if payload == "first":
                first_started.set()
                await release.wait()
            elif payload == "second":
                second_started.set()
                await release.wait()
            completed.append(payload)

        runtime = SessionActorRuntime(handler)
        try:
            await runtime.submit("session-1", "first")
            await runtime.submit("session-2", "second")
            await asyncio.wait_for(
                asyncio.gather(first_started.wait(), second_started.wait()),
                timeout=1.0,
            )
            release.set()
            await asyncio.wait_for(runtime.join(), timeout=1.0)
            self.assertCountEqual(completed, ["first", "second"])
        finally:
            await runtime.shutdown()


if __name__ == "__main__":
    unittest.main()
