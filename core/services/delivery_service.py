from __future__ import annotations

from typing import Any, Awaitable, Callable
from uuid import uuid4

from core.delivery_formatting import delivery_target_supports_markdown, format_delivery_payload_for_endpoint
from core.services.delivery_queue import DatabaseDeliveryQueueBackend, DeliveryQueueBackend
from core.services.endpoint_service import DeliveryAttemptService, EndpointOutboxService


class DeliveryService:
    def __init__(
        self,
        *,
        outbox_service: EndpointOutboxService,
        attempt_service: DeliveryAttemptService,
        queue_backend: DeliveryQueueBackend | None = None,
    ):
        self._outbox_service = outbox_service
        self._attempt_service = attempt_service
        self._queue_backend = queue_backend or DatabaseDeliveryQueueBackend(outbox_service)
        self._transport: Callable[..., Awaitable[bool]] | None = None

    def set_transport(self, transport: Callable[..., Awaitable[bool]] | None) -> None:
        self._transport = transport

    @staticmethod
    def _delivery_id_from_frame(frame: dict[str, Any]) -> str:
        payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
        return str(payload.get("delivery_id") or frame.get("delivery_id") or "").strip()

    @staticmethod
    def _is_ack_success(status: str) -> bool:
        return str(status or "").strip().lower() in {"ok", "sent", "delivered", "succeeded", "success"}

    @staticmethod
    def _queueable_policy(policy: str) -> bool:
        return str(policy or "").strip() in {"store_and_retry", "store_in_outbox", "queue_until_online"}

    async def deliver(
        self,
        *,
        target_endpoint,
        target_address=None,
        message_type: str,
        payload: dict[str, Any],
        offline_policy: str = "store_and_retry",
    ) -> dict[str, Any]:
        endpoint_id = str(getattr(target_endpoint, "endpoint_id", "") or "")
        target_row_id = getattr(target_endpoint, "id", None)
        address_payload = {}
        if target_address is not None:
            address_payload = {
                "target_address_id": str(getattr(target_address, "address_id", "") or ""),
                "target_provider_type": str(getattr(target_address, "provider_type", "") or ""),
                "target_address_type": str(getattr(target_address, "address_type", "") or ""),
                "target_external_ref": str(getattr(target_address, "external_ref", "") or ""),
            }
        enriched_payload = {**dict(payload or {}), **address_payload}
        supports_markdown = delivery_target_supports_markdown(target_endpoint, target_address)
        enriched_payload = format_delivery_payload_for_endpoint(
            enriched_payload,
            supports_markdown=supports_markdown,
        )
        delivery_id = f"delivery_{uuid4().hex}"
        enriched_payload["delivery_id"] = delivery_id
        frame = {
            "schema": "meetyou.endpoint.ws.v4",
            "type": f"delivery.{message_type}",
            "target_endpoint_id": endpoint_id,
            "delivery_id": delivery_id,
            "payload": enriched_payload,
        }
        sent = False
        if self._transport is not None:
            sent = bool(await self._transport(endpoint_id=endpoint_id, frame=frame))
        status = "dispatched" if sent and target_address is not None else "sent" if sent else "queued"
        outbox = None
        if not sent and self._queueable_policy(offline_policy):
            outbox = self._queue_backend.enqueue(
                target_endpoint_id=target_row_id,
                target_address_id=getattr(target_address, "id", None),
                message_type=message_type,
                payload=frame,
                metadata={"offline_policy": offline_policy},
            )
        self._attempt_service.record(
            target_endpoint_id=target_row_id,
            target_address_id=getattr(target_address, "id", None),
            outbox_id=getattr(outbox, "id", None),
            message_type=message_type,
            payload=frame,
            status=status,
            metadata={"offline_policy": offline_policy},
            delivery_id=delivery_id,
        )
        return {"sent": sent, "status": status, "frame": frame}

    def handle_delivery_result(
        self,
        *,
        delivery_id: str,
        status: str,
        error: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_delivery_id = str(delivery_id or "").strip()
        if not normalized_delivery_id:
            return {"ok": False, "reason": "delivery_id_required"}
        attempt = self._attempt_service.get_by_delivery_id(normalized_delivery_id)
        if attempt is None:
            return {"ok": False, "reason": "delivery_not_found", "delivery_id": normalized_delivery_id}
        attempt_meta = dict(getattr(attempt, "meta", {}) or {})
        result_meta = {**dict(metadata or {}), "source": "endpoint_delivery_result"}
        if self._is_ack_success(status):
            outbox_id = getattr(attempt, "outbox_id", None)
            if outbox_id is not None:
                self._queue_backend.mark_sent(outbox_id=outbox_id)
            row = self._attempt_service.update_result(
                delivery_id=normalized_delivery_id,
                status="delivered",
                error={},
                metadata=result_meta,
            )
            return {"ok": True, "status": "delivered", "delivery_id": normalized_delivery_id, "attempt_status": getattr(row, "status", "")}

        error_payload = dict(error or {})
        if not error_payload:
            error_payload = {"message": str(status or "delivery failed"), "type": "endpoint_delivery_failed"}
        offline_policy = str(attempt_meta.get("offline_policy") or "store_and_retry")
        outbox_id = getattr(attempt, "outbox_id", None)
        queued = None
        if self._queueable_policy(offline_policy):
            if outbox_id is None:
                queued = self._queue_backend.enqueue(
                    target_endpoint_id=getattr(attempt, "target_endpoint_id", None),
                    target_address_id=getattr(attempt, "target_address_id", None),
                    message_type=str(getattr(attempt, "message_type", "") or "message"),
                    payload=dict(getattr(attempt, "payload", {}) or {}),
                    metadata={**attempt_meta, "queued_from_delivery_result": True},
                )
                outbox_id = getattr(queued, "id", None)
                next_status = "retry"
            else:
                queued = self._queue_backend.reschedule_failure(
                    outbox_id=outbox_id,
                    error=str(error_payload.get("message") or ""),
                )
                next_status = str(getattr(queued, "status", "") or "retry")
        else:
            next_status = "failed"
        row = self._attempt_service.update_result(
            delivery_id=normalized_delivery_id,
            status=next_status,
            error=error_payload,
            metadata=result_meta,
            outbox_id=outbox_id,
        )
        return {
            "ok": True,
            "status": next_status,
            "delivery_id": normalized_delivery_id,
            "queued": queued is not None,
            "attempt_status": getattr(row, "status", ""),
        }

    async def drain_endpoint_outbox(
        self,
        *,
        target_endpoint,
        limit: int = 50,
        max_attempts: int = 5,
        base_delay_seconds: int = 2,
        max_delay_seconds: int = 300,
    ) -> dict[str, Any]:
        if self._transport is None:
            return {"drained": 0, "sent": 0, "failed": 0, "dead_letter": 0}
        endpoint_id = str(getattr(target_endpoint, "endpoint_id", "") or "")
        target_row_id = getattr(target_endpoint, "id", None)
        rows = self._queue_backend.list_due(target_endpoint_id=target_row_id, limit=limit)
        drained = 0
        sent_count = 0
        failed_count = 0
        dead_letter_count = 0
        for row in rows:
            inflight = self._queue_backend.mark_inflight(outbox_id=getattr(row, "id", None))
            if inflight is None:
                continue
            drained += 1
            frame = dict(getattr(inflight, "payload", {}) or getattr(row, "payload", {}) or {})
            error_payload: dict[str, Any] = {}
            try:
                sent = bool(await self._transport(endpoint_id=endpoint_id, frame=frame))
            except Exception as exc:  # pragma: no cover - defensive, transport is external I/O.
                sent = False
                error_payload = {"message": str(exc), "type": type(exc).__name__}
            if sent:
                self._queue_backend.mark_sent(outbox_id=getattr(inflight, "id", None))
                sent_count += 1
                delivery_id = self._delivery_id_from_frame(frame)
                if delivery_id:
                    self._attempt_service.update_result(
                        delivery_id=delivery_id,
                        status="dispatched",
                        outbox_id=getattr(inflight, "id", None),
                        metadata={"source": "outbox_drain"},
                    )
                else:
                    self._attempt_service.record(
                        target_endpoint_id=getattr(inflight, "target_endpoint_id", target_row_id),
                        target_address_id=getattr(inflight, "target_address_id", None),
                        outbox_id=getattr(inflight, "id", None),
                        message_type=getattr(inflight, "message_type", ""),
                        payload=frame,
                        status="sent",
                        metadata={"source": "outbox_drain"},
                    )
                continue

            if not error_payload:
                error_payload = {"message": "endpoint transport unavailable", "type": "delivery_unavailable"}
            updated = self._queue_backend.reschedule_failure(
                outbox_id=getattr(inflight, "id", None),
                error=str(error_payload.get("message") or ""),
                max_attempts=max_attempts,
                base_delay_seconds=base_delay_seconds,
                max_delay_seconds=max_delay_seconds,
            )
            status = str(getattr(updated, "status", "") or "retry")
            if status == "dead_letter":
                dead_letter_count += 1
            else:
                failed_count += 1
            delivery_id = self._delivery_id_from_frame(frame)
            if delivery_id:
                self._attempt_service.update_result(
                    delivery_id=delivery_id,
                    status=status,
                    error=error_payload,
                    outbox_id=getattr(inflight, "id", None),
                    metadata={"source": "outbox_drain"},
                )
            else:
                self._attempt_service.record(
                    target_endpoint_id=getattr(inflight, "target_endpoint_id", target_row_id),
                    target_address_id=getattr(inflight, "target_address_id", None),
                    outbox_id=getattr(inflight, "id", None),
                    message_type=getattr(inflight, "message_type", ""),
                    payload=frame,
                    status=status,
                    error=error_payload,
                    metadata={"source": "outbox_drain"},
                )
        return {
            "drained": drained,
            "sent": sent_count,
            "failed": failed_count,
            "dead_letter": dead_letter_count,
        }

    async def deliver_to_address(
        self,
        *,
        target_endpoint,
        target_address,
        message_type: str,
        payload: dict[str, Any],
        offline_policy: str = "store_and_retry",
    ) -> dict[str, Any]:
        return await self.deliver(
            target_endpoint=target_endpoint,
            target_address=target_address,
            message_type=message_type,
            payload=payload,
            offline_policy=offline_policy,
        )

    async def publish_run_event(self, *, target_endpoint, run_event, offline_policy: str = "store_and_retry") -> dict[str, Any]:
        return await self.deliver(
            target_endpoint=target_endpoint,
            message_type="run_event",
            payload={
                "event_id": getattr(run_event, "event_id", ""),
                "run_id": str(getattr(run_event, "run_id", "")),
                "thread_id": str(getattr(run_event, "thread_id", "") or ""),
                "seq": getattr(run_event, "seq", 0),
                "type": getattr(run_event, "type", ""),
                "payload": dict(getattr(run_event, "payload", {}) or {}),
                "durable": bool(getattr(run_event, "durable", True)),
            },
            offline_policy=offline_policy,
        )
