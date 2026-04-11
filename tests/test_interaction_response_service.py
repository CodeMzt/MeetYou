import asyncio
import unittest

from core.event_bus import EventBus
from core.interaction_response_service import InteractionResponseService


class InteractionResponseServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmation_wrapper_reflects_pending_state_and_submit(self):
        bus = EventBus()
        service = InteractionResponseService(bus)

        wait_task = asyncio.create_task(bus.request_confirmation("Continue?", session_id="sess-1"))
        await asyncio.sleep(0)

        self.assertTrue(service.has_pending_confirmation(session_id="sess-1"))
        request_id = service.get_pending_confirmation_request_id(session_id="sess-1")
        self.assertTrue(request_id)
        self.assertTrue(
            service.submit_confirmation_response(
                True,
                request_id=request_id,
                session_id="sess-1",
                client_id="test-client",
            )
        )
        self.assertTrue(await wait_task)

    async def test_human_input_wrapper_normalizes_and_submits(self):
        bus = EventBus()
        service = InteractionResponseService(bus)

        wait_task = asyncio.create_task(
            bus.request_human_input("Choose one", options=["A", "B"], session_id="sess-2")
        )
        await asyncio.sleep(0)

        pending = service.get_pending_human_input_request(session_id="sess-2")
        self.assertIsNotNone(pending)
        normalized = service.normalize_human_input_text("2", session_id="sess-2")
        self.assertEqual(normalized["selected_option"], "B")
        self.assertTrue(
            service.submit_human_input_response(
                normalized["answer_text"],
                request_id=normalized["request_id"],
                session_id=normalized["session_id"],
                selected_option=normalized["selected_option"],
            )
        )
        payload = await wait_task
        self.assertEqual(payload["selected_option"], "B")


if __name__ == "__main__":
    unittest.main()
