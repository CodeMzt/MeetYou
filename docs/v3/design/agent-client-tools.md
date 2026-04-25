# Agent/Client Runtime Tools

## Tool Surface

- `list_active_agents(workspace_id?, include_capabilities?)` lists agents that are both registered as `online`/`ready` and currently connected through `/agent/ws`.
- `list_active_clients(workspace_id?, thread_id?, include_owned_agents?)` lists clients with active `/client/ws` connections after the socket has been bound to a session/client.
- `send_endpoint_message(...)` supports realtime notices and capability calls:
  - `delivery_kind="notice"` sends a transient `message.created` event to a Client or an `agent.message` notice to an Agent; it is not persisted.
  - `delivery_kind="capability_call"` dispatches through existing `capability.call.*` Agent protocol. Client targets are resolved to their owned online Agent, so desktop file, command, and local MCP tools remain inside Desktop Agent/Edge Agent boundaries.
- `emit_short_reply(content)` persists a standalone assistant message with `channel="short_reply"` and only works while the current turn is `thinking` or `tool_calling`. `emit_temporary_reply` remains as a compatibility alias.
- `restart_core(password, reason?, delay_seconds?)` validates `MEETYOU_CORE_ADMIN_PASSWORD`, then `core_admin_password`, then default `123456`, and schedules an in-process Core Service restart.

## Boundaries

- Online state is in-memory gateway connection state, not only database status.
- Short replies are persisted for chat history reload, but they are not written to ContextPool and are not appended to model turn history.
- Risky or confirmation-required Agent capabilities require `confirmed=true` before `send_endpoint_message(..., delivery_kind="capability_call")` dispatches them.
- MeetWeChat keeps the same tool surface in its `allowed_tool_bundle`; `short_reply` `message.created` events are sent as independent outbound messages and do not complete the pending final reply.
