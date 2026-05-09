from __future__ import annotations

import unittest
from types import SimpleNamespace

from tools.scheduler_tools import SchedulerTools


class _SchedulerService:
    def __init__(self):
        self.jobs = {
            "system.heartbeat": SimpleNamespace(
                id="job-system",
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
            )
        }

    def list_jobs(self):
        return list(self.jobs.values())

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def create_job(self, **kwargs):
        job_id = kwargs.get("job_id") or "job.created"
        row = SimpleNamespace(
            id=f"row-{job_id}",
            job_id=job_id,
            deletable=True,
            editable_fields=["name", "enabled", "trigger_config"],
            meta=kwargs.get("metadata") or {},
            **{key: value for key, value in kwargs.items() if key not in {"job_id", "metadata"}},
        )
        self.jobs[job_id] = row
        return row

    def update_job(self, *, job_id, **updates):
        row = self.jobs[job_id]
        if job_id == "system.heartbeat":
            disallowed = sorted(key for key in updates if key not in {"enabled", "trigger_config"})
            if disallowed:
                raise ValueError("system.heartbeat only allows enabled and interval_seconds updates.")
            if "trigger_config" in updates:
                trigger_config = dict(updates["trigger_config"] or {})
                if sorted(set(trigger_config) - {"type", "interval_seconds"}) or "interval_seconds" not in trigger_config:
                    raise ValueError("system.heartbeat trigger_config may only set interval_seconds.")
        for key, value in updates.items():
            if key == "metadata":
                row.meta = value
            else:
                setattr(row, key, value)
        return row

    def set_enabled(self, *, job_id, enabled):
        row = self.jobs[job_id]
        row.enabled = bool(enabled)
        return row

    def delete_job(self, *, job_id):
        row = self.jobs[job_id]
        if not row.deletable:
            raise ValueError(f"scheduled job is not deletable: {job_id}")
        del self.jobs[job_id]
        return True


class _RunService:
    def __init__(self):
        self.created = []

    def create_run(self, **kwargs):
        run = SimpleNamespace(id=f"run-row-{len(self.created) + 1}", run_id=f"run_{len(self.created) + 1}", **kwargs)
        self.created.append(run)
        return run

    def update_status(self, **kwargs):
        return SimpleNamespace(**kwargs)


class _EventService:
    def __init__(self):
        self.events = []

    def append_event(self, **kwargs):
        self.events.append(kwargs)
        return SimpleNamespace(**kwargs)


class _JobRunService:
    def __init__(self):
        self.created = []

    def create_job_run(self, **kwargs):
        row = SimpleNamespace(job_run_id=f"jobrun_{len(self.created) + 1}", **kwargs)
        self.created.append(row)
        return row


class _EndpointAddressService:
    def __init__(self):
        self.address = SimpleNamespace(
            id="address-row-1",
            address_id="addr.feishu.direct.chat-1",
            endpoint_id="endpoint-feishu.provider.ui",
            provider_type="feishu",
            address_type="direct",
            external_ref="chat-1",
            display_name="Feishu Chat",
            status="sendable",
            meta={},
        )

    def get_by_address_id(self, address_id):
        return self.address if address_id == self.address.address_id else None

    def get_by_id(self, row_id):
        return self.address if row_id == self.address.id else None


class _PreferenceService:
    def __init__(self):
        self.preference = None

    def get_default(self, **kwargs):
        return self.preference


class SchedulerToolsV4Tests(unittest.IsolatedAsyncioTestCase):
    def _tools(self):
        scheduler = _SchedulerService()
        run = _RunService()
        events = _EventService()
        job_runs = _JobRunService()
        addresses = _EndpointAddressService()
        preferences = _PreferenceService()
        actor = SimpleNamespace(id="actor-user:self", actor_id="user:self")
        services = SimpleNamespace(
            scheduler=scheduler,
            workspace=SimpleNamespace(
                get_by_workspace_id=lambda workspace_id: SimpleNamespace(id=f"workspace-{workspace_id}", workspace_id=workspace_id),
                get_by_id=lambda row_id: SimpleNamespace(id=row_id, workspace_id="personal"),
            ),
            actor=SimpleNamespace(
                get_by_actor_id=lambda actor_id: actor if actor_id == "user:self" else SimpleNamespace(id=f"actor-{actor_id}", actor_id=actor_id),
                ensure_actor=lambda **kwargs: SimpleNamespace(id=f"actor-{kwargs['actor_id']}", **kwargs),
            ),
            endpoint=SimpleNamespace(
                get_by_endpoint_id=lambda endpoint_id: SimpleNamespace(id=f"endpoint-{endpoint_id}", endpoint_id=endpoint_id),
                get_by_id=lambda row_id: SimpleNamespace(id=row_id, endpoint_id="feishu.provider.ui"),
            ),
            endpoint_address=addresses,
            actor_delivery_preference=preferences,
            run=run,
            scheduled_job_run=job_runs,
            run_event=events,
        )
        tools = SchedulerTools()
        tools.set_core_domain(SimpleNamespace(principal=SimpleNamespace(principal_key="self", display_name="Self"), services=services))
        return tools, scheduler, run, events, job_runs

    async def test_manage_scheduled_jobs_updates_system_heartbeat_interval(self):
        tools, scheduler, *_ = self._tools()

        payload = await tools.manage_scheduled_jobs(
            action="update",
            job_id="system.heartbeat",
            interval_seconds=120,
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(scheduler.jobs["system.heartbeat"].trigger_config["interval_seconds"], 120)
        self.assertEqual(payload["job"]["trigger_config"]["interval_seconds"], 120)

    async def test_manage_scheduled_jobs_rejects_mutating_system_heartbeat_shape(self):
        tools, *_ = self._tools()

        with self.assertRaisesRegex(ValueError, "only allows enabled and interval_seconds"):
            await tools.manage_scheduled_jobs(
                action="update",
                job_id="system.heartbeat",
                name="Renamed heartbeat",
            )
        with self.assertRaisesRegex(ValueError, "may only set interval_seconds"):
            await tools.manage_scheduled_jobs(
                action="update",
                job_id="system.heartbeat",
                trigger_config={"type": "cron", "cron": "* * * * *"},
            )

    async def test_manage_scheduled_jobs_rejects_system_heartbeat_delete(self):
        tools, *_ = self._tools()

        with self.assertRaisesRegex(ValueError, "not deletable"):
            await tools.manage_scheduled_jobs(action="delete", job_id="system.heartbeat")

    async def test_manage_scheduled_jobs_rejects_creating_system_heartbeat(self):
        tools, *_ = self._tools()

        with self.assertRaisesRegex(ValueError, "cannot be created"):
            await tools.manage_scheduled_jobs(action="create", job_id="system.heartbeat", workspace_id="personal")
        with self.assertRaisesRegex(ValueError, "cannot be created"):
            await tools.manage_scheduled_jobs(action="create", kind="system_heartbeat", workspace_id="personal")
        with self.assertRaisesRegex(ValueError, "cannot be created"):
            await tools.manage_scheduled_jobs(action="create", action_ref="core.workflow.heartbeat", workspace_id="personal")

    async def test_manage_scheduled_jobs_rejects_ordinary_job_heartbeat_action_ref(self):
        tools, scheduler, *_ = self._tools()
        scheduler.create_job(
            job_id="ordinary.job",
            kind="workflow",
            name="Ordinary job",
            workspace_id=None,
            singleton_key=None,
            enabled=True,
            trigger_type="manual",
            trigger_config={},
            timezone="UTC",
            action_ref="core.workflow.assistant_turn",
            run_template={},
            execution_policy={},
            delivery_policy={},
            concurrency_policy={},
            misfire_policy={},
            metadata={},
        )

        with self.assertRaisesRegex(ValueError, "Only system.heartbeat"):
            await tools.manage_scheduled_jobs(action="update", job_id="ordinary.job", action_ref="core.workflow.heartbeat")

    async def test_manage_scheduled_jobs_trigger_creates_run_and_job_run(self):
        tools, scheduler, run_service, event_service, job_run_service = self._tools()
        scheduler.create_job(
            job_id="acceptance.job",
            kind="workflow",
            name="Acceptance job",
            workspace_id=None,
            singleton_key=None,
            enabled=True,
            trigger_type="manual",
            trigger_config={},
            timezone="UTC",
            action_ref="core.workflow.acceptance",
            run_template={},
            execution_policy={},
            delivery_policy={},
            concurrency_policy={},
            misfire_policy={},
            metadata={},
        )

        payload = await tools.manage_scheduled_jobs(action="trigger", job_id="acceptance.job", workspace_id="personal")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["actor_id"], "system.scheduler")
        self.assertEqual(len(run_service.created), 1)
        self.assertEqual(len(job_run_service.created), 1)
        self.assertEqual([event["type"] for event in event_service.events], ["run.started", "run.completed"])

    async def test_manage_scheduled_jobs_trigger_delegates_to_runtime_callback(self):
        tools, scheduler, run_service, event_service, job_run_service = self._tools()
        scheduler.create_job(
            job_id="runtime.job",
            kind="workflow",
            name="Runtime job",
            workspace_id=None,
            singleton_key=None,
            enabled=True,
            trigger_type="manual",
            trigger_config={},
            timezone="UTC",
            action_ref="core.workflow.assistant_turn",
            run_template={},
            execution_policy={},
            delivery_policy={},
            concurrency_policy={},
            misfire_policy={},
            metadata={},
        )
        calls = []

        async def _trigger(**kwargs):
            calls.append(dict(kwargs))
            return {"triggered": True, "job_id": kwargs["job_id"], "run_id": "run_runtime"}

        tools.set_trigger_job_callback(_trigger)

        payload = await tools.manage_scheduled_jobs(action="trigger", job_id="runtime.job", workspace_id="personal")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["run_id"], "run_runtime")
        self.assertEqual(calls, [{"job_id": "runtime.job", "workspace_id": "personal", "manual": True}])
        self.assertEqual(len(run_service.created), 0)
        self.assertEqual(len(event_service.events), 0)
        self.assertEqual(len(job_run_service.created), 0)

    async def test_manage_scheduled_jobs_daily_update_preserves_time_when_shape_only(self):
        tools, scheduler, *_ = self._tools()
        scheduler.create_job(
            job_id="daily.job",
            kind="scheduled_workflow",
            name="Daily job",
            workspace_id=None,
            singleton_key=None,
            enabled=True,
            trigger_type="daily",
            trigger_config={"type": "daily", "time_of_day": "08:00"},
            timezone="Asia/Shanghai",
            action_ref="core.workflow.scheduled_workflow",
            run_template={},
            execution_policy={},
            delivery_policy={},
            concurrency_policy={},
            misfire_policy={},
            metadata={},
        )

        payload = await tools.manage_scheduled_jobs(
            action="update",
            job_id="daily.job",
            trigger_config={"type": "daily"},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(scheduler.jobs["daily.job"].trigger_config, {"type": "daily", "time_of_day": "08:00"})

    async def test_manage_scheduled_jobs_daily_update_accepts_hour_minute_alias(self):
        tools, scheduler, *_ = self._tools()
        scheduler.create_job(
            job_id="daily.job",
            kind="scheduled_workflow",
            name="Daily job",
            workspace_id=None,
            singleton_key=None,
            enabled=True,
            trigger_type="daily",
            trigger_config={"type": "daily", "time_of_day": "08:00"},
            timezone="Asia/Shanghai",
            action_ref="core.workflow.scheduled_workflow",
            run_template={},
            execution_policy={},
            delivery_policy={},
            concurrency_policy={},
            misfire_policy={},
            metadata={},
        )

        payload = await tools.manage_scheduled_jobs(
            action="update",
            job_id="daily.job",
            trigger_config={"type": "daily", "hour": 7, "minute": 0},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(scheduler.jobs["daily.job"].trigger_config, {"type": "daily", "time_of_day": "07:00"})

    async def test_create_scheduled_delivery_requires_me_binding(self):
        tools, *_ = self._tools()

        payload = await tools.create_scheduled_delivery(
            name="Morning greeting",
            schedule={"type": "daily", "time_of_day": "08:00"},
            target={"actor_ref": "me", "provider_type": "feishu"},
            instruction="Say good morning.",
        )

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["requires_binding"])
        self.assertEqual(payload["provider_type"], "feishu")

    async def test_create_scheduled_workflow_creates_generic_job_without_delivery_target(self):
        tools, scheduler, *_ = self._tools()

        payload = await tools.create_scheduled_workflow(
            name="Daily document digest",
            schedule={"type": "daily", "time_of_day": "09:30", "timezone": "Asia/Shanghai"},
            instruction="Summarize new project notes and persist the result.",
            tool_policy={"tool_bundle": ["get_current_system_time", "summarize_text"], "max_rounds": 3},
            output_policy={"output_kinds": ["assistant_message"]},
        )

        self.assertTrue(payload["ok"])
        job = scheduler.jobs[payload["job"]["job_id"]]
        self.assertEqual(job.kind, "scheduled_workflow")
        self.assertEqual(job.action_ref, "core.workflow.scheduled_workflow")
        self.assertEqual(job.delivery_policy["targets"], [])
        self.assertEqual(job.run_template["schema"], "meetyou.scheduler.workflow.v1")
        self.assertEqual(job.run_template["workflow_type"], "assistant_run")
        self.assertEqual(job.run_template["tool_bundle"], ["get_current_system_time", "summarize_text"])
        self.assertEqual(job.run_template["max_rounds"], 3)
        self.assertTrue(job.run_template["max_rounds_explicit"])
        self.assertEqual(job.run_template["output_policy"]["output_kinds"], ["assistant_message"])

    async def test_create_scheduled_workflow_defaults_to_unlimited_rounds(self):
        tools, scheduler, *_ = self._tools()

        payload = await tools.create_scheduled_workflow(
            name="Deep daily digest",
            schedule={"type": "daily", "time_of_day": "09:30", "timezone": "Asia/Shanghai"},
            instruction="Research and summarize everything needed.",
            output_policy={"output_kinds": ["assistant_message"]},
        )

        self.assertTrue(payload["ok"])
        job = scheduler.jobs[payload["job"]["job_id"]]
        self.assertEqual(job.run_template["max_rounds"], 0)
        self.assertFalse(job.run_template["max_rounds_explicit"])

    async def test_create_scheduled_workflow_rejects_non_persisted_assistant_output(self):
        tools, *_ = self._tools()

        with self.assertRaisesRegex(ValueError, "must be persisted"):
            await tools.create_scheduled_workflow(
                name="Ephemeral digest",
                schedule={"type": "daily", "time_of_day": "09:30"},
                instruction="Summarize notes.",
                output_policy={"persist_message": False},
            )

    async def test_create_scheduled_workflow_requires_thread_when_not_creating_one(self):
        tools, *_ = self._tools()

        with self.assertRaisesRegex(ValueError, "create_thread=false requires"):
            await tools.create_scheduled_workflow(
                name="Existing thread only",
                schedule={"type": "daily", "time_of_day": "09:30"},
                instruction="Summarize notes.",
                output_policy={"create_thread": False},
            )

    async def test_create_scheduled_delivery_creates_address_targeted_job(self):
        tools, scheduler, *_ = self._tools()

        payload = await tools.create_scheduled_delivery(
            name="Morning greeting",
            schedule={"type": "daily", "time_of_day": "08:00", "timezone": "Asia/Shanghai"},
            target={"address_id": "addr.feishu.direct.chat-1"},
            instruction="Say good morning.",
            generation_policy="generate_at_fire_time",
        )

        self.assertTrue(payload["ok"])
        job = scheduler.jobs[payload["job"]["job_id"]]
        self.assertEqual(job.kind, "scheduled_workflow")
        self.assertEqual(job.action_ref, "core.workflow.scheduled_workflow")
        self.assertEqual(job.trigger_type, "daily")
        self.assertEqual(job.trigger_config["time_of_day"], "08:00")
        self.assertEqual(job.delivery_policy["targets"][0]["address_id"], "addr.feishu.direct.chat-1")
        self.assertEqual(job.run_template["workflow_subtype"], "delivery")
        self.assertEqual(job.run_template["generation_policy"], "generate_at_fire_time")
        self.assertEqual(job.run_template["instruction"], "Say good morning.")
        self.assertEqual(job.run_template["max_rounds"], 0)
        self.assertTrue(job.run_template["max_rounds_explicit"])

        deliveries = await tools.manage_scheduled_deliveries(action="list")
        workflows = await tools.manage_scheduled_workflows(action="list")
        self.assertEqual(deliveries["count"], 1)
        self.assertEqual(workflows["count"], 1)

    async def test_scheduled_delivery_schedule_update_accepts_time_alias(self):
        tools, scheduler, *_ = self._tools()
        payload = await tools.create_scheduled_delivery(
            name="Morning greeting",
            schedule={"type": "daily", "time_of_day": "08:00", "timezone": "Asia/Shanghai"},
            target={"address_id": "addr.feishu.direct.chat-1"},
            instruction="Say good morning.",
        )
        job_id = payload["job"]["job_id"]

        updated = await tools.manage_scheduled_deliveries(
            action="update",
            job_id=job_id,
            schedule={"type": "daily", "time": "7:00", "timezone": "Asia/Shanghai"},
        )

        self.assertTrue(updated["ok"])
        self.assertEqual(scheduler.jobs[job_id].trigger_config, {"type": "daily", "time_of_day": "07:00"})

    async def test_scheduled_delivery_schedule_update_preserves_existing_time_when_missing(self):
        tools, scheduler, *_ = self._tools()
        payload = await tools.create_scheduled_delivery(
            name="Morning greeting",
            schedule={"type": "daily", "time_of_day": "06:30", "timezone": "Asia/Shanghai"},
            target={"address_id": "addr.feishu.direct.chat-1"},
            instruction="Say good morning.",
        )
        job_id = payload["job"]["job_id"]

        updated = await tools.manage_scheduled_deliveries(
            action="update",
            job_id=job_id,
            schedule={"type": "daily", "timezone": "Asia/Shanghai"},
        )

        self.assertTrue(updated["ok"])
        self.assertEqual(scheduler.jobs[job_id].trigger_config, {"type": "daily", "time_of_day": "06:30"})

    async def test_scheduled_delivery_schedule_update_preserves_target_with_empty_defaults(self):
        tools, scheduler, *_ = self._tools()
        payload = await tools.create_scheduled_delivery(
            name="Morning greeting",
            schedule={"type": "daily", "time_of_day": "08:00", "timezone": "Asia/Shanghai"},
            target={"address_id": "addr.feishu.direct.chat-1"},
            instruction="Say good morning.",
        )
        job_id = payload["job"]["job_id"]

        updated = await tools.manage_scheduled_deliveries(
            action="update",
            job_id=job_id,
            schedule={"type": "daily", "time_of_day": "07:00", "timezone": "Asia/Shanghai"},
            target={},
            delivery_policy={},
        )

        self.assertTrue(updated["ok"])
        job = scheduler.jobs[job_id]
        self.assertEqual(job.trigger_config["time_of_day"], "07:00")
        self.assertEqual(job.delivery_policy["targets"][0]["address_id"], "addr.feishu.direct.chat-1")
        self.assertEqual(job.run_template["tool_bundle"], ["get_current_system_time", "emit_progress_notice"])

    async def test_scheduled_workflow_schedule_update_preserves_output_with_empty_defaults(self):
        tools, scheduler, *_ = self._tools()
        payload = await tools.create_scheduled_delivery(
            name="Morning greeting",
            schedule={"type": "daily", "time_of_day": "08:00", "timezone": "Asia/Shanghai"},
            target={"address_id": "addr.feishu.direct.chat-1"},
            instruction="Say good morning.",
        )
        job_id = payload["job"]["job_id"]

        updated = await tools.manage_scheduled_workflows(
            action="update",
            job_id=job_id,
            schedule={"type": "daily", "time_of_day": "07:00", "timezone": "Asia/Shanghai"},
            tool_policy={},
            output_policy={},
        )

        self.assertTrue(updated["ok"])
        job = scheduler.jobs[job_id]
        self.assertEqual(job.trigger_config["time_of_day"], "07:00")
        self.assertEqual(job.delivery_policy["targets"][0]["address_id"], "addr.feishu.direct.chat-1")
        self.assertEqual(job.run_template["output_policy"]["delivery_targets"][0]["address_id"], "addr.feishu.direct.chat-1")
        self.assertEqual(job.run_template["tool_bundle"], ["get_current_system_time", "emit_progress_notice"])


if __name__ == "__main__":
    unittest.main()
