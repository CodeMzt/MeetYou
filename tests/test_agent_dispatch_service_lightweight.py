from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest

from core.services.agent_dispatch_service import AgentDispatchError, AgentDispatchService


class _AgentService:
    def __init__(self):
        self.agent = SimpleNamespace(
            id="agent-row",
            agent_id="desktop-main-agent",
            status="online",
        )

    def get_by_agent_id(self, agent_id: str):
        return self.agent if agent_id == self.agent.agent_id else None

    def is_bound_to_workspace(self, *, agent_id: str, workspace_id: str) -> bool:
        return agent_id == self.agent.agent_id and workspace_id == "desktop-main"


class _CapabilityService:
    def __init__(self, *, requires_confirmation: bool):
        self.capability = SimpleNamespace(
            id="cap-row",
            capability_id="agent.desktop-main-agent.file.write",
            provider_ref="desktop-main-agent",
            risk_level="write",
            requires_confirmation=requires_confirmation,
        )

    def get_by_capability_id(self, capability_id: str):
        return self.capability if capability_id == self.capability.capability_id else None

    def is_available_in_workspace(self, *, capability_id: str, workspace_id) -> bool:
        return capability_id == self.capability.capability_id and workspace_id == "workspace-row"

    def resolve_capability_reference(self, **kwargs):
        return None


class _SessionService:
    def get_by_session_id(self, session_id: str):
        if session_id == "sess-1":
            return SimpleNamespace(id="session-row", session_id="sess-1", thread_id="thread-row", active_workspace_id="workspace-row")
        return None


class _ThreadService:
    def get_by_id(self, row_id):
        return SimpleNamespace(id="thread-row", workspace_id="workspace-row") if row_id == "thread-row" else None


class _WorkspaceService:
    def get_by_id(self, row_id):
        return SimpleNamespace(id="workspace-row", workspace_id="desktop-main") if row_id == "workspace-row" else None

    def get_by_workspace_id(self, workspace_id: str):
        return SimpleNamespace(id="workspace-row", workspace_id="desktop-main") if workspace_id == "desktop-main" else None


class _OperationService:
    def create_operation(self, **kwargs):
        return SimpleNamespace(id="operation-row", operation_id="op-1", **kwargs)


class _OperationCallService:
    def __init__(self):
        self.failed = []
        self.dispatched = []

    def create_call(self, **kwargs):
        return SimpleNamespace(id="call-row", call_id="call-1", **kwargs)

    def mark_failed(self, *, call_id: str, error: dict):
        self.failed.append({"call_id": call_id, "error": dict(error)})

    def mark_dispatched(self, *, call_id: str):
        self.dispatched.append(call_id)


def _build_service(*, requires_confirmation: bool = True) -> AgentDispatchService:
    return AgentDispatchService(
        agent_service=_AgentService(),
        capability_service=_CapabilityService(requires_confirmation=requires_confirmation),
        session_service=_SessionService(),
        thread_service=_ThreadService(),
        workspace_service=_WorkspaceService(),
        operation_service=_OperationService(),
        operation_call_service=_OperationCallService(),
    )


class AgentDispatchServiceLightweightTests(unittest.IsolatedAsyncioTestCase):
    async def test_specific_capability_requires_confirmation_for_risky_call(self):
        service = _build_service(requires_confirmation=True)

        with self.assertRaises(AgentDispatchError) as error_context:
            await service.dispatch_specific_agent_capability(
                agent_id="desktop-main-agent",
                capability_ref="file.write",
                arguments={"path": "demo.txt", "content": "hello"},
                session_id="sess-1",
                confirmed=False,
            )

        self.assertEqual(error_context.exception.tool_error_code, "agent_capability_confirmation_required")

    async def test_specific_capability_dispatches_after_confirmation(self):
        service = _build_service(requires_confirmation=True)
        transport_payload = {}

        async def fake_transport(*, agent_id: str, payload: dict) -> bool:
            transport_payload.update(payload)

            async def resolve_later():
                await asyncio.sleep(0.01)
                await service.notify_call_result(call_id=payload["payload"]["call_id"], result={"summary": "ok"})

            asyncio.create_task(resolve_later())
            return True

        service.set_transport(fake_transport)
        result = await service.dispatch_specific_agent_capability(
            agent_id="desktop-main-agent",
            capability_ref="file.write",
            arguments={"path": "demo.txt", "content": "hello"},
            session_id="sess-1",
            confirmed=True,
            timeout_seconds=5,
        )

        self.assertEqual(result["summary"], "ok")
        self.assertEqual(transport_payload["payload"]["capability_id"], "agent.desktop-main-agent.file.write")


if __name__ == "__main__":
    unittest.main()
