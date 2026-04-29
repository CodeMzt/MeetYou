from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.services.delivery_service import DeliveryService


class _Recorder:
    def __init__(self):
        self.rows = []

    def enqueue(self, **kwargs):
        row = SimpleNamespace(id="outbox_1", **kwargs)
        self.rows.append(row)
        return row

    def record(self, **kwargs):
        row = SimpleNamespace(id="delivery_1", **kwargs)
        self.rows.append(row)
        return row


class DeliveryV4Tests(unittest.IsolatedAsyncioTestCase):
    async def test_delivery_queues_when_endpoint_transport_is_offline(self):
        outbox = _Recorder()
        attempts = _Recorder()
        service = DeliveryService(outbox_service=outbox, attempt_service=attempts)

        result = await service.deliver(
            target_endpoint=SimpleNamespace(id="endpoint-row", endpoint_id="desktop.home.ui"),
            message_type="notice",
            payload={"text": "hello"},
        )

        self.assertFalse(result["sent"])
        self.assertEqual(result["status"], "queued")
        self.assertEqual(outbox.rows[0].message_type, "notice")
        self.assertEqual(attempts.rows[0].status, "queued")

    async def test_delivery_strips_markdown_for_plain_text_endpoint(self):
        outbox = _Recorder()
        attempts = _Recorder()
        service = DeliveryService(outbox_service=outbox, attempt_service=attempts)
        sent_frames = []

        async def transport(**kwargs):
            sent_frames.append(dict(kwargs))
            return True

        service.set_transport(transport)

        result = await service.deliver(
            target_endpoint=SimpleNamespace(
                id="endpoint-row",
                endpoint_id="feishu.provider.ui",
                provider_type="feishu",
                meta={"supports_markdown": False},
            ),
            message_type="message",
            payload={"role": "assistant", "content": "**bold** and [Docs](https://example.test)"},
        )

        self.assertTrue(result["sent"])
        self.assertEqual(sent_frames[0]["frame"]["payload"]["content"], "bold and Docs (https://example.test)")


if __name__ == "__main__":
    unittest.main()
