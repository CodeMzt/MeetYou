import asyncio
import unittest

from core.heart import Heart


class _FakeAdapter:
    pass


class _FakeConfig:
    def get(self, key: str, default=None):
        values = {
            "heartbeat_interval": 180,
            "housekeeping_interval": 60,
            "scheduler_interval": 15,
            "heartbeat_api_url": "",
            "heartbeat_api_key": "",
            "heart_model": "",
        }
        return values.get(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        return bool(self.get(key, default))


class _FakeMemory:
    def set_housekeeping_adapter(self, adapter):
        return None


class _FakeTaskManager:
    def __init__(self):
        self.remembered = []

    async def claim_due_tasks(self, limit=8, lease_seconds=120):
        del limit, lease_seconds
        return [
            {
                "task_key": "daily-news",
                "content": "Every day at 9 summarize AI news",
                "auto_run": True,
                "active_claim_token": "claim-1",
                "delivery_target": {
                    "session_id": "web:session-1",
                },
                "origin_session_id": "web:session-1",
                "preferred_tool_key": "manage_tasks",
                "preferred_target_endpoint_ids": ["desktop-main-client"],
                "preferred_endpoint_provider_types": ["desktop"],
                "tool_target_routing_policy": "balanced",
            }
        ]

    async def remember_task_operation(self, task_key: str, *, operation_id: str, status: str, now=None):
        del now
        self.remembered.append({"task_key": task_key, "operation_id": operation_id, "status": status})


class _FakeExceptionRouter:
    def wrap(self, message: str, exc: Exception):
        return RuntimeError(f"{message}: {exc}")


class _FakeEventBus:
    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self.inbound_queue = asyncio.Queue()


class _FakeOperationRow:
    def __init__(self, operation_id: str, metadata: dict):
        self.id = operation_id
        self.operation_id = operation_id
        self.meta = dict(metadata)


class _FakeOperationService:
    def __init__(self):
        self.rows = []

    def create_operation(self, **kwargs):
        row = _FakeOperationRow(f"op-heart-{len(self.rows) + 1}", kwargs.get("metadata") or {})
        self.rows.append(row)
        return row


class _FakeSessionService:
    def get_by_session_id(self, session_id: str):
        if session_id == "web:session-1":
            return type("SessionRow", (), {"id": "session-row-1", "client_id": "client-row-1", "thread_id": "thread-row-1", "workspace_id": "workspace-row-1"})()
        return None


class _FakeThreadService:
    def get_by_id(self, row_id):
        if row_id == "thread-row-1":
            return type("ThreadRow", (), {"id": "thread-row-1", "thread_id": "thread-1"})()
        return None


class _FakeWorkspaceService:
    def get_by_id(self, row_id):
        if row_id == "workspace-row-1":
            return type("WorkspaceRow", (), {"id": "workspace-row-1", "workspace_id": "desktop-main"})()
        return None


class HeartSchedulerOperationTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_precreates_operation_and_attaches_operation_id_to_control_event(self):
        event_bus = _FakeEventBus()
        task_manager = _FakeTaskManager()
        heart = Heart(
            _FakeAdapter(),
            _FakeConfig(),
            tools_manager=object(),
            memory=_FakeMemory(),
            task_manager=task_manager,
            event_bus=event_bus,
            exception_router=_FakeExceptionRouter(),
        )
        heart._http_session = object()
        heart._scheduler_interval = 9999
        heart.set_core_services(
            type(
                "CoreServices",
                (),
                {
                    "operation": _FakeOperationService(),
                    "session": _FakeSessionService(),
                    "thread": _FakeThreadService(),
                    "workspace": _FakeWorkspaceService(),
                },
            )()
        )

        task = asyncio.create_task(heart.scheduler_processor())
        await asyncio.sleep(0.05)
        event_bus.shutdown_event.set()
        await task

        inbound = await event_bus.inbound_queue.get()
        self.assertEqual(inbound.metadata["control_kind"], "scheduled_task")
        self.assertTrue(inbound.metadata["operation_id"])
        self.assertEqual(inbound.content["operation_id"], inbound.metadata["operation_id"])
        self.assertEqual(task_manager.remembered[0]["status"], "queued")


if __name__ == "__main__":
    unittest.main()
