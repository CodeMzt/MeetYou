from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

from core.app import App
from core.io_protocol import EventTarget, TargetKind


def _dt() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _Row:
    id: int
    session_id: str = ""
    thread_id: str = ""
    workspace_id: str = ""
    client_id: str = ""
    status: str = "pending"
    operation_id: str = ""
    approval_id: str = ""
    approval_type: str = ""
    risk_level: str = ""
    decision: str = ""
    reason: str = ""
    requested_by_client_id: int | None = None
    requested_by_session_id: int | None = None
    operation_type: str = ""
    execution_target: str = ""
    title: str = ""
    meta: dict = None
    result_summary: str = ""
    created_at: datetime = _dt()

    def __post_init__(self):
        if self.meta is None:
            self.meta = {}


class _FakeSessionService:
    def __init__(self, session_row: _Row):
        self._row = session_row

    def get_by_session_id(self, session_id: str):
        if session_id == self._row.session_id:
            return self._row
        return None


class _FakeThreadService:
    def __init__(self, thread_row: _Row):
        self._row = thread_row

    def get_by_id(self, row_id):
        if row_id == self._row.id:
            return self._row
        return None


class _FakeWorkspaceService:
    def __init__(self, workspace_row: _Row):
        self._row = workspace_row

    def get_by_id(self, row_id):
        if row_id == self._row.id:
            return self._row
        return None


class _FakeClientService:
    def __init__(self, client_row: _Row):
        self._row = client_row

    def get_by_client_id(self, client_id: str):
        if client_id == self._row.client_id:
            return self._row
        return None

    def get_by_id(self, row_id):
        if row_id == self._row.id:
            return self._row
        return None


class _FakeOperationService:
    def __init__(self):
        self._counter = 1
        self.rows: dict[int, _Row] = {}

    def create_operation(
        self,
        *,
        thread_id,
        workspace_id,
        operation_type: str,
        execution_target: str,
        title: str = "",
        target_endpoint_id=None,
        requested_by_client_id=None,
        requested_by_session_id=None,
        status: str = "queued",
        metadata: dict | None = None,
    ):
        del target_endpoint_id
        row = _Row(
            id=self._counter,
            operation_id=f"op_{self._counter}",
            thread_id="",
            workspace_id="",
            requested_by_client_id=requested_by_client_id,
            requested_by_session_id=requested_by_session_id,
            operation_type=operation_type,
            execution_target=execution_target,
            title=title,
            status=status,
            meta=dict(metadata or {}),
        )
        row.thread_id = str(thread_id)
        row.workspace_id = str(workspace_id)
        self.rows[row.id] = row
        self._counter += 1
        return row

    def update_status(self, *, operation_id, status: str, result_summary: str | None = None, metadata: dict | None = None):
        row = self.rows.get(int(operation_id))
        if row is None:
            return None
        row.status = status
        if result_summary is not None:
            row.result_summary = result_summary
        if metadata:
            merged = dict(row.meta)
            merged.update(dict(metadata))
            row.meta = merged
        return row


class _FakeApprovalService:
    def __init__(self):
        self._counter = 1
        self.rows: dict[str, _Row] = {}

    def create_approval(self, *, operation_id, approval_type: str, risk_level: str):
        approval_id = f"approval_{self._counter}"
        row = _Row(
            id=self._counter,
            approval_id=approval_id,
            operation_id=str(operation_id),
            approval_type=approval_type,
            risk_level=risk_level,
            status="pending",
            decision="",
            reason="",
        )
        self.rows[approval_id] = row
        self._counter += 1
        return row

    def get_by_approval_id(self, approval_id: str):
        return self.rows.get(approval_id)

    def decide_approval(self, *, approval_id: str, decision: str, reason: str = "", decided_by_client_id=None):
        del decided_by_client_id
        row = self.rows.get(approval_id)
        if row is None:
            return None
        row.decision = decision
        row.reason = reason
        row.status = "approved" if decision == "approve" else "rejected"
        return row


class _FakeBrain:
    def __init__(self):
        self._snapshots = {
            "sess_1": {
                "active_tools": ["exec_sys_cmd"],
                "stream_id": "stream-1",
                "turn_id": "turn-1",
            }
        }

    def get_session_runtime_snapshot(self, session_id: str):
        return dict(self._snapshots.get(session_id, {}))

    def set_session_runtime_state(self, *args, **kwargs):
        del args, kwargs
        return None


class _FakeSpeaker:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


class _FakeGateway:
    def __init__(self):
        self.events = []

    async def publish_client_thread_event(self, thread_id: str, *, event_type: str, payload: dict):
        self.events.append((thread_id, event_type, dict(payload)))


class ConfirmApprovalFlowTests(unittest.TestCase):
    def _build_app(self):
        app = App.__new__(App)
        app._confirm_approval_requests = {}
        app.brain = _FakeBrain()
        app.speaker = _FakeSpeaker()
        app.gateway = _FakeGateway()
        app._emit_runtime_status_event = self._noop_async

        session_row = _Row(id=10, session_id="sess_1", thread_id="", workspace_id="", client_id="", status="active")
        session_row.thread_id = 20
        session_row.workspace_id = 30
        session_row.client_id = 40
        thread_row = _Row(id=20, thread_id="thr_1", workspace_id="", status="active")
        thread_row.workspace_id = 30
        workspace_row = _Row(id=30, workspace_id="personal", status="active")
        client_row = _Row(id=40, client_id="electron-main")

        operation_service = _FakeOperationService()
        approval_service = _FakeApprovalService()

        app.core_services = SimpleNamespace(
            session=_FakeSessionService(session_row),
            thread=_FakeThreadService(thread_row),
            workspace=_FakeWorkspaceService(workspace_row),
            client=_FakeClientService(client_row),
            operation=operation_service,
            approval=approval_service,
        )
        return app, operation_service, approval_service

    @staticmethod
    async def _noop_async(*args, **kwargs):
        del args, kwargs
        return None

    def test_confirm_request_creates_approval_context_and_resolution_updates_rows(self):
        app, operation_service, approval_service = self._build_app()

        event = SimpleNamespace(
            session_id="sess_1",
            content="是否允许执行危险操作？",
            request_id="req_1",
            timeout=30.0,
            default_decision=False,
            target=EventTarget(kind=TargetKind.CURRENT_SESSION.value),
            metadata={"risk_level": "system"},
        )

        asyncio.run(app._handle_confirm_request(event))

        context = app.get_confirm_approval_context("req_1")
        self.assertEqual(context.get("approval_status"), "pending")
        self.assertTrue(context.get("approval_id"))
        self.assertEqual(len(operation_service.rows), 1)
        self.assertEqual(len(approval_service.rows), 1)
        self.assertTrue(app.gateway.events)
        _, event_type, payload = app.gateway.events[-1]
        self.assertEqual(event_type, "confirm.requested")
        self.assertEqual(payload.get("approval_id"), context.get("approval_id"))

        payload = {
            "session_id": "sess_1",
            "request_id": "req_1",
            "accepted": True,
            "client_id": "electron-main",
        }
        asyncio.run(app._handle_confirm_response(payload))

        updated_context = app.get_confirm_approval_context("req_1")
        self.assertEqual(updated_context, {})
        approval = next(iter(approval_service.rows.values()))
        self.assertEqual(approval.status, "approved")
        operation = next(iter(operation_service.rows.values()))
        self.assertEqual(operation.status, "succeeded")


if __name__ == "__main__":
    unittest.main()
