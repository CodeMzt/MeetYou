# Endpoint Provider Template

Use this checklist when adding a new V4 Endpoint Provider such as Desktop, Edge, Feishu, WeChatBot, webhook, or email.

## Required provider shape

- Connect to Core through `GET /endpoint/ws` with schema `meetyou.endpoint.ws.v4`.
- Send `endpoint.hello` with a V4 protocol offer, provider identity, endpoint rows, workspace scope, and markdown support metadata.
- Send `endpoint.capabilities.snapshot` for executable endpoints, even when the snapshot is empty.
- Send `endpoint.ready` after local startup is complete and `endpoint.heartbeat` only as connection keepalive.
- Represent provider-internal destinations as `EndpointAddress` rows via `endpoint.addresses.snapshot`, `endpoint.address.upsert`, and `endpoint.address.delete`.

## Execution capability contract

- Expose executable tools through capability snapshots; Core routes calls through ToolRouter and `ExecutionTarget`.
- Handle `tool.call.request`, then emit `tool.call.accepted`, optional `tool.call.progress`, and exactly one terminal `tool.call.result`, `tool.call.error`, or cancellation error.
- Handle `tool.call.cancel` by cancelling only the matching call id.
- Do not own Thread, Message, Run, Scheduler, Heartbeat, Memory, Operation, or Delivery semantics.

## Delivery contract

- Receive human-visible outbound content through Delivery frames: `delivery.message`, `delivery.run_event`, `delivery.notice`, `delivery.operation_update`, and `delivery.inbox_item`.
- Address-targeted delivery must use `target_address_id`, `target_provider_type`, `target_address_type`, and `target_external_ref`.
- Providers may adapt formatting to channel capability, but must not generate assistant replies.

## Conformance tests

- Handshake negotiation rejects unsupported schema/version and accepts the current V4 offer.
- Capability snapshot replacement disables removed tools.
- Address snapshot/upsert/delete persists expected `EndpointAddress` rows.
- Subscription start/update/stop changes fan-out targets without reconnecting.
- Tool request/result/error/cancel round-trips preserve `call_id` and operation updates.
- Disconnect/reconnect invalidates ToolRouter cache and replays durable RunEvents for thread subscriptions.
