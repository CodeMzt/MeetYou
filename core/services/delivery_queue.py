from __future__ import annotations

from typing import Protocol

from core.services.endpoint_service import EndpointOutboxService


class DeliveryQueueBackend(Protocol):
    def enqueue(
        self,
        *,
        target_endpoint_id,
        target_address_id=None,
        message_type: str,
        payload: dict,
        metadata: dict | None = None,
    ):
        ...

    def list_due(self, *, target_endpoint_id=None, limit: int = 50):
        ...

    def mark_inflight(self, *, outbox_id):
        ...

    def mark_sent(self, *, outbox_id):
        ...

    def reschedule_failure(
        self,
        *,
        outbox_id,
        error: str,
        max_attempts: int = 5,
        base_delay_seconds: int = 2,
        max_delay_seconds: int = 300,
    ):
        ...


class DatabaseDeliveryQueueBackend:
    def __init__(self, outbox_service: EndpointOutboxService):
        self._outbox_service = outbox_service

    def enqueue(
        self,
        *,
        target_endpoint_id,
        target_address_id=None,
        message_type: str,
        payload: dict,
        metadata: dict | None = None,
    ):
        return self._outbox_service.enqueue(
            target_endpoint_id=target_endpoint_id,
            target_address_id=target_address_id,
            message_type=message_type,
            payload=payload,
            metadata=metadata,
        )

    def list_due(self, *, target_endpoint_id=None, limit: int = 50):
        return self._outbox_service.list_due(target_endpoint_id=target_endpoint_id, limit=limit)

    def mark_inflight(self, *, outbox_id):
        return self._outbox_service.mark_inflight(outbox_id=outbox_id)

    def mark_sent(self, *, outbox_id):
        return self._outbox_service.mark_sent(outbox_id=outbox_id)

    def reschedule_failure(
        self,
        *,
        outbox_id,
        error: str,
        max_attempts: int = 5,
        base_delay_seconds: int = 2,
        max_delay_seconds: int = 300,
    ):
        return self._outbox_service.reschedule_failure(
            outbox_id=outbox_id,
            error=error,
            max_attempts=max_attempts,
            base_delay_seconds=base_delay_seconds,
            max_delay_seconds=max_delay_seconds,
        )
