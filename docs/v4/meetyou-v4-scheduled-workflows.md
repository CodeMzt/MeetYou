# MeetYou V4 Scheduled Workflow

## Purpose

`ScheduledWorkflow` is the user-facing scheduling abstraction in V4. Scheduler owns trigger timing only. The triggered action is a Core workflow that can generate text, search, summarize, organize documents, route endpoint tools through ToolRouter, and optionally deliver the final assistant Message.

Message sending is only one output type. Do not model Scheduler as "timed message sender".

## Runtime Contract

Stored jobs use:

```text
kind = scheduled_workflow
action_ref = core.workflow.scheduled_workflow
run_template.schema = meetyou.scheduler.workflow.v1
```

At fire time Core:

1. Claims the due job using `next_fire_at` plus `lease_owner/lease_until_at`.
2. Creates `Run(trigger_type="scheduled_job")`.
3. Builds workflow messages from `run_template.instruction`.
4. Calls the model and allowed tools.
5. Persists the final assistant reply through `MessageService`.
6. Emits streaming/state events through `RunEventLog` plus Delivery fan-out.
7. Applies `delivery_policy.targets` only after the assistant Message exists.

`system.heartbeat` remains a non-deletable Scheduler preset and is not a Scheduled Workflow.

## Workflow Spec

`run_template` is the pluggable workflow spec:

```json
{
  "schema": "meetyou.scheduler.workflow.v1",
  "workflow_type": "assistant_run",
  "mode": "automation",
  "instruction": "每天整理昨天新增项目文档并生成摘要",
  "tool_bundle": ["get_current_system_time", "search_knowledge", "read_local_documents", "summarize_text"],
  "mcp_servers": [],
  "preferred_tool_key": "",
  "preferred_target_endpoint_ids": [],
  "preferred_endpoint_provider_types": [],
  "tool_target_routing_policy": "balanced",
  "output_policy": {
    "persist_message": true,
    "create_thread": true,
    "output_kinds": ["assistant_message"],
    "delivery_targets": []
  },
  "max_rounds": 0
}
```

`max_rounds=0` means the scheduled assistant run has no model/tool round limit. Set a positive value only for workflows that need an explicit cap. Legacy workflow templates that stored the previous default `max_rounds=6` without an explicit marker are interpreted as unlimited.

Current `workflow_type` values:

- `assistant_run`: Core creates a scheduled Run and lets the model plan/use tools.
- `tool_workflow`: reserved for a future deterministic tool graph.
- `external_workflow`: reserved for a future plugin/webhook workflow target.

## Output Policy

Default output is a persisted assistant Message in a Core Thread.

`persist_message=false` is not a supported V4 assistant workflow mode. If the workflow uses the model and produces a final assistant reply, Core must persist that reply through `MessageService`. `create_thread=false` is only valid when the workflow points to an existing `thread_id` or `session_id`.

Optional delivery output uses `delivery_policy.targets`:

```json
{
  "targets": [
    {
      "address_id": "addr.feishu.direct.oc_xxx",
      "provider_type": "feishu",
      "address_type": "direct",
      "message_type": "message",
      "offline_policy": "store_and_retry"
    }
  ]
}
```

Delivery sends the already persisted Message. Delivery must not generate content.

## Assistant Tools

Preferred tools:

- `create_scheduled_workflow`: create ordinary reminders, recurring analysis, document organization, research digest, or any other scheduled assistant work.
- `manage_scheduled_workflows`: list/detail/update/enable/disable/delete/trigger scheduled workflows.
- `create_scheduled_delivery`: convenience wrapper for a scheduled workflow whose output must be delivered to Feishu/WeChat/email/etc.
- `manage_scheduled_deliveries`: filtered maintenance for delivery-flavored scheduled workflows.
- `manage_scheduled_jobs`: low-level Scheduler/system.heartbeat maintenance only.

Default rule:

- "每天早上提醒我整理日报" uses `create_scheduled_workflow`.
- "每天早上在 Feishu 给我发问候" uses `list_delivery_targets` and then `create_scheduled_delivery` or `create_scheduled_workflow` with delivery output.
- If "早上" has no exact time, confirm `08:00 Asia/Shanghai` before creating the job.

## EndpointAddress Relationship

Endpoint provider online state is still provider-level. Feishu/WeChat internal personal chats and group chats are `EndpointAddress` records. Scheduled delivery output resolves:

- explicit `address_id`; or
- `actor_ref="me" + provider_type`, through `ActorDeliveryPreference`.

If "me" has no verified binding, the assistant must ask which address to bind before creating delivery output.

## Extensibility

New scheduled capabilities should add workflow/output types rather than new Scheduler clocks:

- new input sources go into `run_template.parameters` or future `input_policy`;
- new tool routing goes into `tool_policy`;
- new outputs go into `output_policy`;
- provider-specific delivery still targets `EndpointAddress`;
- deterministic or plugin flows can use future `workflow_type` values without changing due detection, leasing, or heartbeat.
