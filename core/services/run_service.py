from __future__ import annotations

from uuid import uuid4

from core.db.repositories import RunEventRepository, RunRepository
from core.services.base import ServiceBase


class RunService(ServiceBase):
    def create_run(
        self,
        *,
        workspace_id,
        trigger_type: str,
        origin_actor_id,
        thread_id=None,
        origin_endpoint_id=None,
        status: str = "queued",
        input: dict | None = None,
        output: dict | None = None,
        execution_policy: dict | None = None,
        delivery_policy: dict | None = None,
        metadata: dict | None = None,
    ):
        with self.session_scope() as session:
            return RunRepository(session).create(
                run_id=f"run_{uuid4().hex}",
                workspace_id=workspace_id,
                thread_id=thread_id,
                trigger_type=trigger_type,
                origin_actor_id=origin_actor_id,
                origin_endpoint_id=origin_endpoint_id,
                status=status,
                input=input,
                output=output,
                execution_policy=execution_policy,
                delivery_policy=delivery_policy,
                metadata=metadata,
            )

    def get_by_run_id(self, run_id: str):
        with self.session_scope() as session:
            return RunRepository(session).get_by_run_id(run_id)

    def get_by_id(self, row_id):
        with self.session_scope() as session:
            return RunRepository(session).get_by_id(row_id)

    def update_status(self, *, run_row_id, status: str, output: dict | None = None):
        with self.session_scope() as session:
            return RunRepository(session).update_status(run_id=run_row_id, status=status, output=output)


class RunEventService(ServiceBase):
    def append_event(
        self,
        *,
        run_id,
        type: str,
        payload: dict | None = None,
        thread_id=None,
        durable: bool = True,
    ):
        with self.session_scope() as session:
            return RunEventRepository(session).append(
                event_id=f"evt_{uuid4().hex}",
                run_id=run_id,
                thread_id=thread_id,
                type=type,
                payload=payload,
                durable=durable,
            )

    def emit_progress_notice(
        self,
        *,
        run_id,
        text: str,
        thread_id=None,
        severity: str = "info",
        ttl_seconds: int = 60,
        durable: bool = False,
    ):
        return self.append_event(
            run_id=run_id,
            thread_id=thread_id,
            type="assistant.progress_notice",
            durable=durable,
            payload={
                "text": str(text or ""),
                "severity": str(severity or "info") or "info",
                "ttl_seconds": int(ttl_seconds or 60),
            },
        )

    def list_for_run_after(self, *, run_id, after_seq: int = 0, durable_only: bool = False):
        with self.session_scope() as session:
            return RunEventRepository(session).list_for_run_after(run_id=run_id, after_seq=after_seq, durable_only=durable_only)

    def list_for_thread_after(self, *, thread_id, after_seq: int = 0, durable_only: bool = False):
        with self.session_scope() as session:
            return RunEventRepository(session).list_for_thread_after(thread_id=thread_id, after_seq=after_seq, durable_only=durable_only)
