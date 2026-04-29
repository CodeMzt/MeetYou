# MeetYou V4 EndpointAddress And Scheduled Delivery Output

## Goal

V4 separates provider identity from provider-internal destinations:

- `Endpoint` is the provider runtime: Desktop, Edge, Feishu Provider, MeetWeChat Provider, webhook, email, and similar surfaces.
- `EndpointAddress` is a sendable destination inside a provider: Feishu chat, WeChat private chat, WeChat group, channel, room, or inbox.
- `ActorDeliveryPreference` binds an actor alias such as `me` to a provider address.

This lets a user say from one provider, "send this to me on Feishu tomorrow morning", without requiring Feishu to first create a new conversation in the same moment.

Scheduling itself is documented in `docs/v4/meetyou-v4-scheduled-workflows.md`. Scheduled delivery is now a delivery-flavored Scheduled Workflow, not the only Scheduler use case.

## Data Model

`endpoint_addresses` stores provider-internal destinations:

- `address_id`
- `endpoint_id`
- `provider_type`
- `address_type`
- `external_ref`
- `display_name`
- `workspace_scope`
- `status`
- `capabilities`
- `last_seen_at`
- `last_verified_at`
- `metadata`

`actor_delivery_preferences` stores actor bindings:

- `preference_id`
- `actor_id`
- `provider_type`
- `address_id`
- `alias`
- `is_default`
- `verified`
- `metadata`

`scheduled_jobs` now stores persistent due state:

- `next_fire_at`
- `last_fire_at`
- `lease_owner`
- `lease_until_at`

`endpoint_outbox` and `delivery_attempts` can reference `target_address_id`.

## Protocol

Endpoint providers can publish addresses through:

- `endpoint.addresses.snapshot`
- `endpoint.address.upsert`
- `endpoint.address.delete`

Address-targeted delivery payloads include:

- `target_address_id`
- `target_provider_type`
- `target_address_type`
- `target_external_ref`

Feishu and MeetWeChat register provider-level endpoints and publish known addresses from configuration, local state, provider discovery, and inbound events.

## Assistant Tools

High-level user-facing tools:

- `list_delivery_targets`
- `set_delivery_preference`
- `send_delivery_message`
- `create_scheduled_workflow`
- `manage_scheduled_workflows`
- `create_scheduled_delivery`
- `manage_scheduled_deliveries`

Low-level maintenance tool:

- `manage_scheduled_jobs`

Assistant behavior:

- Use `list_delivery_targets(actor_ref="me", provider_type="feishu")` before creating cross-provider scheduled delivery.
- If no binding exists, ask the user to choose and confirm an address, then call `set_delivery_preference`.
- Use `create_scheduled_workflow` for ordinary scheduled work. Use `create_scheduled_delivery` only when the scheduled workflow must deliver its generated assistant Message to an EndpointAddress.
- Keep final generated content as a persisted assistant Message; Delivery only transports it.

## Scheduled Delivery Runtime

A scheduled delivery is a Scheduled Workflow with a delivery output:

```text
kind = scheduled_workflow
action_ref = core.workflow.scheduled_workflow
run_template.schema = meetyou.scheduler.workflow.v1
run_template.workflow_subtype = delivery
trigger_type = daily | interval | cron | one_shot
```

At fire time Core:

1. Acquires a Scheduler lease.
2. Creates `Run(trigger_type="scheduled_job")`.
3. Executes a Core-owned Scheduled Workflow background turn.
4. Persists the final assistant reply with `MessageService`.
5. Applies `delivery_policy.targets` and delivers the message through `DeliveryService` to `EndpointAddress`.
6. Stores `last_fire_at` and computes the next `next_fire_at`.

`system.heartbeat` remains a non-deletable Scheduler preset and is still restricted to enable/disable and interval changes.

## Example

User says in WeChat:

```text
设置一个定时任务，每天早上 Feishu 给我发送消息问好
```

Expected assistant flow:

1. Resolve `me + feishu` with `list_delivery_targets`.
2. If not bound, ask the user to select a Feishu address.
3. Bind with `set_delivery_preference`.
4. Create a daily Scheduled Workflow with delivery output at the confirmed time, defaulting to `08:00 Asia/Shanghai` only after confirmation.
5. At each fire time, generate the greeting, persist the assistant Message, and deliver it to the Feishu address.

## Verification

Minimum checks for this layer:

- Migration/bootstrap creates the new tables and columns.
- Endpoint protocol accepts address snapshot/upsert/delete.
- `list_delivery_targets`, `set_delivery_preference`, and `send_delivery_message` work through `EndpointAddress`.
- Daily, interval, cron, and one-shot scheduling compute persistent next fire times.
- Scheduled delivery manual trigger creates Run, Message, and address-targeted Delivery through the Scheduled Workflow runtime.
- Feishu/WeChat non-streaming outputs receive only one final message.
