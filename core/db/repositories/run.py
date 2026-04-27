from __future__ import annotations

from sqlalchemy import func

from core.db.base import utcnow
from core.db.models.run import Run, RunEvent
from core.db.repositories.base import RepositoryBase


class RunRepository(RepositoryBase):
    def create(
        self,
        *,
        run_id: str,
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
    ) -> Run:
        row = Run(
            run_id=run_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            trigger_type=trigger_type,
            origin_actor_id=origin_actor_id,
            origin_endpoint_id=origin_endpoint_id,
            status=status,
            input=dict(input or {}),
            output=dict(output or {}),
            execution_policy=dict(execution_policy or {}),
            delivery_policy=dict(delivery_policy or {}),
            meta=dict(metadata or {}),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_by_run_id(self, run_id: str) -> Run | None:
        return self.session.query(Run).filter_by(run_id=run_id).one_or_none()

    def get_by_id(self, row_id) -> Run | None:
        return self.session.query(Run).filter_by(id=row_id).one_or_none()

    def update_status(self, *, run_id, status: str, output: dict | None = None) -> Run | None:
        row = self.get_by_id(run_id)
        if row is None:
            return None
        row.status = status
        if status == "running" and row.started_at is None:
            row.started_at = utcnow()
        if status in {"succeeded", "failed", "cancelled"}:
            row.finished_at = utcnow()
        if output is not None:
            row.output = dict(output)
        self.session.flush()
        return row


class RunEventRepository(RepositoryBase):
    def append(
        self,
        *,
        event_id: str,
        run_id,
        type: str,
        payload: dict | None = None,
        thread_id=None,
        durable: bool = True,
    ) -> RunEvent:
        seq = int(
            self.session.query(func.coalesce(func.max(RunEvent.seq), 0))
            .filter_by(run_id=run_id)
            .scalar()
            or 0
        ) + 1
        row = RunEvent(
            event_id=event_id,
            run_id=run_id,
            thread_id=thread_id,
            seq=seq,
            type=type,
            payload=dict(payload or {}),
            durable=bool(durable),
            created_at=utcnow(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_for_run_after(self, *, run_id, after_seq: int = 0, durable_only: bool = False) -> list[RunEvent]:
        query = self.session.query(RunEvent).filter(RunEvent.run_id == run_id, RunEvent.seq > int(after_seq or 0))
        if durable_only:
            query = query.filter(RunEvent.durable.is_(True))
        return list(query.order_by(RunEvent.seq.asc()).all())

    def list_for_thread_after(self, *, thread_id, after_seq: int = 0, durable_only: bool = False) -> list[RunEvent]:
        query = self.session.query(RunEvent).filter(RunEvent.thread_id == thread_id, RunEvent.seq > int(after_seq or 0))
        if durable_only:
            query = query.filter(RunEvent.durable.is_(True))
        return list(query.order_by(RunEvent.created_at.asc(), RunEvent.seq.asc()).all())
