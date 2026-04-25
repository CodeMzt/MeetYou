# Agent/Client Runtime Tools

## Tool Surface

- `list_active_agents(workspace_id?, include_capabilities?)` lists agents that are both registered as `online`/`ready` and currently connected through `/agent/ws`.
- `list_active_clients(workspace_id?, thread_id?, include_owned_agents?)` lists clients with active `/client/ws` connections after the socket has been bound to a session/client. Desktop UI, CIL, Feishu, and MeetWeChat clients all send stable Client identity into this path.
- `send_endpoint_message(...)` supports realtime notices and capability calls:
  - `delivery_kind="notice"` sends transient independent messages to endpoints: Client targets receive `message.created`; Agent targets receive `agent.message` and, when the Agent has an online owner Client such as the desktop UI, a mirrored `message.created` notice is also delivered to that owner Client for visible feedback. These notices are not persisted.
  - `delivery_kind="capability_call"` dispatches through existing `capability.call.*` Agent protocol. Client targets are resolved to their owned online Agent, so desktop file, command, and local MCP tools remain inside Desktop Agent/Edge Agent boundaries.
- `emit_short_reply(content)` persists a standalone assistant message with `channel="short_reply"` and only works while the current turn is `thinking` or `tool_calling`. Assistants must call it before potentially time-consuming operations such as web/page reads, research, local file or workspace work, shell/agent capability calls, endpoint messaging, or other slow I/O. `emit_temporary_reply` remains as a compatibility alias.
- `restart_core(password, reason?, delay_seconds?)` validates `MEETYOU_CORE_ADMIN_PASSWORD`, then `core_admin_password`, then default `123456`, and schedules an in-process Core Service restart.

## Boundaries

- Online state is in-memory gateway connection state, not only database status.
- Short replies are persisted for chat history reload, but they are not written to ContextPool and are not appended to model turn history.
- Risky or confirmation-required Agent capabilities require `confirmed=true` before `send_endpoint_message(..., delivery_kind="capability_call")` dispatches them.
- Feishu and MeetWeChat keep the same basic tool surface in their `allowed_tool_bundle`; Client adapters render `message.created` with `channel="short_reply"` or `channel="notice"` as independent outbound messages while suppressing normal user `message.created` echoes.
