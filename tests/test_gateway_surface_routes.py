from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.session_manager import SessionManager
from gateway.api import FastAPIGateway
from gateway.endpoint_ws import ENDPOINT_WS_SCHEMA


class _EndpointService:
    def __init__(self):
        self.rows: dict[str, SimpleNamespace] = {}
        self.statuses: list[tuple[str, str]] = []

    def ensure_endpoint(self, **kwargs):
        endpoint_id = kwargs["endpoint_id"]
        row = self.rows.get(endpoint_id)
        if row is None:
            row = SimpleNamespace(id=f"row-{len(self.rows) + 1}", **kwargs)
            self.rows[endpoint_id] = row
        else:
            for key, value in kwargs.items():
                setattr(row, key, value)
        return row

    def get_by_endpoint_id(self, endpoint_id: str):
        return self.rows.get(endpoint_id)

    def list_all(self):
        return list(self.rows.values())

    def set_status(self, *, endpoint_id: str, status: str):
        self.statuses.append((endpoint_id, status))
        row = self.rows.get(endpoint_id)
        if row is not None:
            row.status = status
        return row


class _EndpointConnectionService:
    def __init__(self):
        self.connections: list[dict] = []
        self.heartbeats: list[dict] = []
        self.disconnected: list[str] = []

    def upsert_connection(self, **kwargs):
        self.connections.append(dict(kwargs))
        return SimpleNamespace(connection_id=kwargs["connection_id"])

    def heartbeat(self, **kwargs):
        self.heartbeats.append(dict(kwargs))

    def mark_disconnected(self, *, connection_id: str):
        self.disconnected.append(connection_id)


class _EndpointCapabilityService:
    def __init__(self):
        self.snapshots: list[dict] = []

    def replace_snapshot(self, **kwargs):
        self.snapshots.append(dict(kwargs))
        return len(kwargs.get("capabilities") or [])

    def list_for_endpoint(self, *, endpoint_row_id):
        for snapshot in self.snapshots:
            if snapshot.get("endpoint_row_id") == endpoint_row_id:
                return list(snapshot.get("capabilities") or [])
        return []


class _WorkspaceService:
    def get_by_id(self, row_id):
        if not row_id:
            return None
        return SimpleNamespace(id=row_id, workspace_id="desktop-main")

    def get_by_workspace_id(self, workspace_id: str):
        if workspace_id == "desktop-main":
            return SimpleNamespace(id="workspace-row", workspace_id="desktop-main")
        return None


class _SchedulerService:
    def __init__(self):
        self.jobs = {
            "system.heartbeat": SimpleNamespace(
                id="heartbeat-row",
                job_id="system.heartbeat",
                kind="system_heartbeat",
                name="System heartbeat",
                workspace_id=None,
                singleton_key="core.system.heartbeat",
                enabled=True,
                deletable=False,
                editable_fields=["enabled", "trigger_config.interval_seconds"],
                trigger_type="interval",
                trigger_config={"type": "interval", "interval_seconds": 600},
                timezone="UTC",
                action_ref="core.workflow.heartbeat",
                run_template={},
                execution_policy={},
                delivery_policy={},
                concurrency_policy={},
                misfire_policy={},
                meta={},
                created_at=None,
                updated_at=None,
            )
        }

    def list_jobs(self):
        return list(self.jobs.values())

    def create_job(self, **kwargs):
        job_id = kwargs.get("job_id") or "job-created"
        job = SimpleNamespace(
            id=f"{job_id}-row",
            job_id=job_id,
            kind=kwargs.get("kind") or "scheduled_task",
            name=kwargs.get("name") or "",
            workspace_id=kwargs.get("workspace_id"),
            singleton_key=kwargs.get("singleton_key"),
            enabled=kwargs.get("enabled", True),
            deletable=True,
            editable_fields=["enabled", "trigger_config"],
            trigger_type=kwargs.get("trigger_type") or "interval",
            trigger_config=kwargs.get("trigger_config") or {},
            timezone=kwargs.get("timezone") or "UTC",
            action_ref=kwargs.get("action_ref") or "",
            run_template=kwargs.get("run_template") or {},
            execution_policy=kwargs.get("execution_policy") or {},
            delivery_policy=kwargs.get("delivery_policy") or {},
            concurrency_policy=kwargs.get("concurrency_policy") or {},
            misfire_policy=kwargs.get("misfire_policy") or {},
            meta=kwargs.get("metadata") or {},
            created_at=None,
            updated_at=None,
        )
        self.jobs[job_id] = job
        return job

    def update_job(self, *, job_id: str, **updates):
        job = self.jobs.get(job_id)
        if job is None:
            return None
        for key, value in updates.items():
            if key == "metadata":
                setattr(job, "meta", value)
            else:
                setattr(job, key, value)
        return job

    def delete_job(self, *, job_id: str):
        job = self.jobs.get(job_id)
        if job is None:
            return False
        if not job.deletable:
            raise ValueError(f"scheduled job is not deletable: {job_id}")
        self.jobs.pop(job_id, None)
        return True


class _FakeDomain:
    def __init__(self):
        self.services = SimpleNamespace(
            endpoint=_EndpointService(),
            endpoint_connection=_EndpointConnectionService(),
            endpoint_capability=_EndpointCapabilityService(),
            workspace=_WorkspaceService(),
            scheduler=_SchedulerService(),
            thread=SimpleNamespace(get_by_thread_id=lambda thread_id: None),
            run_event=SimpleNamespace(list_for_thread_after=lambda **kwargs: []),
            operation_call=SimpleNamespace(
                mark_succeeded=lambda **kwargs: None,
                mark_accepted=lambda **kwargs: None,
                mark_progress=lambda **kwargs: None,
                mark_failed=lambda **kwargs: None,
            ),
            tool_router=SimpleNamespace(
                notify_call_result=lambda call_id, result: None,
                notify_call_error=lambda call_id, error: None,
            ),
        )


class GatewaySurfaceRouteTests(unittest.TestCase):
    def test_endpoint_ws_hello_capability_and_subscription_flow(self):
        domain = _FakeDomain()
        gateway = FastAPIGateway(EventBus(), SessionManager(), core_domain=domain, access_token="surface-token")

        with TestClient(gateway.app) as client:
            with client.websocket_connect(
                "/endpoint/ws",
                headers={"Authorization": "Bearer surface-token"},
            ) as websocket:
                websocket.send_json(
                    {
                        "schema": ENDPOINT_WS_SCHEMA,
                        "type": "endpoint.hello",
                        "correlation_id": "hello-1",
                        "payload": {
                            "connection_id": "conn-1",
                            "provider": {"provider_type": "desktop", "provider_id": "desktop-main"},
                            "endpoints": [
                                {
                                    "endpoint_id": "desktop.main.ui",
                                    "endpoint_type": "desktop_ui",
                                    "workspace_ids": ["desktop-main"],
                                },
                                {
                                    "endpoint_id": "desktop.main.executor",
                                    "endpoint_type": "desktop_executor",
                                    "workspace_ids": ["desktop-main"],
                                }
                            ],
                        },
                    }
                )
                hello_ack = websocket.receive_json()
                self.assertEqual(hello_ack["schema"], ENDPOINT_WS_SCHEMA)
                self.assertEqual(hello_ack["type"], "endpoint.hello.ack")
                self.assertEqual(hello_ack["endpoint_id"], "desktop.main.ui")
                self.assertTrue(hello_ack["payload"]["accepted"])

                websocket.send_json(
                    {
                        "schema": ENDPOINT_WS_SCHEMA,
                        "type": "endpoint.capabilities.snapshot",
                        "endpoint_id": "desktop.main.executor",
                        "payload": {
                            "capabilities": [
                                {
                                    "capability_id": "endpoint.desktop.main.executor.file.read",
                                    "tool_key": "file.read",
                                    "risk_level": "read",
                                    "enabled": True,
                                }
                            ]
                        },
                    }
                )
                ready = websocket.receive_json()
                self.assertEqual(ready["type"], "endpoint.ready")
                self.assertEqual(ready["payload"]["registered_capability_count"], 1)

                websocket.send_json(
                    {
                        "schema": ENDPOINT_WS_SCHEMA,
                        "type": "subscription.start",
                        "payload": {
                            "subscription_id": "sub-1",
                            "target_type": "thread",
                            "target_id": "thr-1",
                        },
                    }
                )
                subscription_ack = websocket.receive_json()
                self.assertEqual(subscription_ack["type"], "subscription.ack")
                self.assertEqual(subscription_ack["payload"]["target_type"], "thread")
                self.assertTrue(gateway.endpoint_ws_manager.has_subscription(target_type="thread", target_id="thr-1"))

                endpoints_resp = client.get(
                    "/operator/endpoints",
                    headers={"Authorization": "Bearer surface-token"},
                )
                self.assertEqual(endpoints_resp.status_code, 200)
                endpoints = {item["endpoint_id"]: item for item in endpoints_resp.json()}
                self.assertTrue(endpoints["desktop.main.executor"]["connected"])
                self.assertEqual(endpoints["desktop.main.executor"]["connection_count"], 1)
                self.assertTrue(endpoints["desktop.main.ui"]["connected"])
                self.assertEqual(endpoints["desktop.main.ui"]["connection_count"], 1)

        self.assertIn("desktop.main.ui", domain.services.endpoint.rows)
        self.assertIn("desktop.main.executor", domain.services.endpoint.rows)
        self.assertEqual(domain.services.endpoint_connection.connections[0]["connection_id"], "conn-1")
        self.assertEqual(domain.services.endpoint_capability.snapshots[0]["endpoint_public_id"], "desktop.main.executor")

    def test_operator_scheduled_jobs_crud_and_system_heartbeat_guard(self):
        domain = _FakeDomain()
        gateway = FastAPIGateway(EventBus(), SessionManager(), core_domain=domain, access_token="surface-token")

        with TestClient(gateway.app) as client:
            headers = {"Authorization": "Bearer surface-token"}
            create_resp = client.post(
                "/operator/scheduled-jobs",
                headers=headers,
                json={
                    "job_id": "acceptance.job",
                    "kind": "acceptance",
                    "name": "Acceptance job",
                    "workspace_id": "desktop-main",
                    "interval_seconds": 90,
                },
            )
            self.assertEqual(create_resp.status_code, 200)
            self.assertEqual(create_resp.json()["trigger_config"]["interval_seconds"], 90)

            list_resp = client.get("/operator/scheduled-jobs", headers=headers)
            self.assertEqual(list_resp.status_code, 200)
            self.assertIn("system.heartbeat", {item["job_id"] for item in list_resp.json()})

            patch_resp = client.patch(
                "/operator/scheduled-jobs/system.heartbeat",
                headers=headers,
                json={"enabled": False, "interval_seconds": 137},
            )
            self.assertEqual(patch_resp.status_code, 200)
            self.assertFalse(patch_resp.json()["enabled"])
            self.assertEqual(patch_resp.json()["trigger_config"]["interval_seconds"], 137)

            delete_system_resp = client.delete("/operator/scheduled-jobs/system.heartbeat", headers=headers)
            self.assertEqual(delete_system_resp.status_code, 400)
            self.assertEqual(delete_system_resp.json()["error"]["code"], "scheduled_job_not_deletable")

            delete_resp = client.delete("/operator/scheduled-jobs/acceptance.job", headers=headers)
            self.assertEqual(delete_resp.status_code, 200)
            self.assertTrue(delete_resp.json()["deleted"])


if __name__ == "__main__":
    unittest.main()
