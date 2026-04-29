from __future__ import annotations

import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.db.base import Base
from core.db.models import Endpoint
from core.services.delivery_service import DeliveryService
from core.services.endpoint_service import EndpointOutboxService


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


class _Queue:
    def __init__(self, rows):
        self.rows = list(rows)

    def enqueue(self, **kwargs):
        row = SimpleNamespace(id=f"outbox_{len(self.rows) + 1}", status="pending", attempt_count=0, **kwargs)
        self.rows.append(row)
        return row

    def list_due(self, *, target_endpoint_id=None, limit=50):
        return [
            row
            for row in self.rows
            if row.status in {"pending", "retry"} and (target_endpoint_id is None or row.target_endpoint_id == target_endpoint_id)
        ][:limit]

    def mark_inflight(self, *, outbox_id):
        row = next((item for item in self.rows if item.id == outbox_id), None)
        if row is None:
            return None
        row.status = "sending"
        row.attempt_count += 1
        return row

    def mark_sent(self, *, outbox_id):
        row = next((item for item in self.rows if item.id == outbox_id), None)
        if row is None:
            return None
        row.status = "sent"
        row.last_error = ""
        return row

    def reschedule_failure(
        self,
        *,
        outbox_id,
        error,
        max_attempts=5,
        base_delay_seconds=2,
        max_delay_seconds=300,
    ):
        del base_delay_seconds, max_delay_seconds
        row = next((item for item in self.rows if item.id == outbox_id), None)
        if row is None:
            return None
        row.last_error = error
        row.status = "dead_letter" if row.attempt_count >= max_attempts else "retry"
        row.available_at = "later" if row.status == "retry" else None
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

    async def test_delivery_outbox_drain_marks_sent_and_records_attempt(self):
        attempts = _Recorder()
        frame = {"schema": "meetyou.endpoint.ws.v4", "type": "delivery.notice", "payload": {"text": "hello"}}
        queue = _Queue([
            SimpleNamespace(
                id="outbox_1",
                target_endpoint_id="endpoint-row",
                target_address_id=None,
                message_type="notice",
                payload=frame,
                status="pending",
                attempt_count=0,
                last_error="",
            )
        ])
        service = DeliveryService(outbox_service=_Recorder(), attempt_service=attempts, queue_backend=queue)
        sent_frames = []

        async def transport(**kwargs):
            sent_frames.append(dict(kwargs))
            return True

        service.set_transport(transport)

        result = await service.drain_endpoint_outbox(
            target_endpoint=SimpleNamespace(id="endpoint-row", endpoint_id="desktop.home.ui"),
        )

        self.assertEqual(result["sent"], 1)
        self.assertEqual(queue.rows[0].status, "sent")
        self.assertEqual(queue.rows[0].attempt_count, 1)
        self.assertEqual(sent_frames[0]["frame"], frame)
        self.assertEqual(attempts.rows[0].status, "sent")

    async def test_delivery_outbox_drain_retries_then_dead_letters(self):
        attempts = _Recorder()
        frame = {"schema": "meetyou.endpoint.ws.v4", "type": "delivery.notice", "payload": {"text": "hello"}}
        retry_row = SimpleNamespace(
            id="outbox_retry",
            target_endpoint_id="endpoint-row",
            target_address_id=None,
            message_type="notice",
            payload=frame,
            status="pending",
            attempt_count=0,
            last_error="",
        )
        queue = _Queue([retry_row])
        service = DeliveryService(outbox_service=_Recorder(), attempt_service=attempts, queue_backend=queue)

        async def offline_transport(**kwargs):
            del kwargs
            return False

        service.set_transport(offline_transport)

        first = await service.drain_endpoint_outbox(
            target_endpoint=SimpleNamespace(id="endpoint-row", endpoint_id="desktop.home.ui"),
            max_attempts=2,
        )
        second = await service.drain_endpoint_outbox(
            target_endpoint=SimpleNamespace(id="endpoint-row", endpoint_id="desktop.home.ui"),
            max_attempts=2,
        )

        self.assertEqual(first["failed"], 1)
        self.assertEqual(second["dead_letter"], 1)
        self.assertEqual(retry_row.status, "dead_letter")
        self.assertEqual([row.status for row in attempts.rows], ["retry", "dead_letter"])

    async def test_endpoint_outbox_service_tracks_retry_backoff_and_dead_letter(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        try:
            with Session() as session:
                endpoint = Endpoint(
                    endpoint_id="desktop.home.ui",
                    endpoint_type="desktop_ui",
                    provider_type="desktop",
                    transport_type="websocket",
                )
                session.add(endpoint)
                session.commit()
                endpoint_row_id = endpoint.id

            service = EndpointOutboxService(Session)
            row = service.enqueue(
                target_endpoint_id=endpoint_row_id,
                message_type="notice",
                payload={"type": "delivery.notice"},
            )
            due = service.list_due(target_endpoint_id=endpoint_row_id)
            inflight = service.mark_inflight(outbox_id=row.id)
            retry = service.reschedule_failure(outbox_id=row.id, error="offline", max_attempts=2)
            inflight_again = service.mark_inflight(outbox_id=row.id)
            dead = service.reschedule_failure(outbox_id=row.id, error="offline", max_attempts=2)

            self.assertEqual([item.outbox_id for item in due], [row.outbox_id])
            self.assertEqual(inflight.attempt_count, 1)
            self.assertEqual(retry.status, "retry")
            self.assertIsNotNone(retry.available_at)
            self.assertEqual(inflight_again.attempt_count, 2)
            self.assertEqual(dead.status, "dead_letter")
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
