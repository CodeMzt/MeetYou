# Client Tool Runtime

## Summary

MeetYou runtime is now `Core + Clients + Tools`.

- Core owns orchestration, policy, persistence, operation/approval, and tool dispatch.
- Client owns identity, workspace membership, connection state, local permissions, and directed tool execution.
- Tool is the first-class executable unit. Local execution is not a separate endpoint category; it is a directed tool executed by a Client.
- The formal realtime endpoint is `GET /client/ws` with `meetyou.client.ws.v1`.
- The old Agent endpoint/runtime surface is intentionally removed.

## Client Identity

`clients` stores the durable endpoint identity:

- `client_id`
- `client_type`
- `display_name`
- `status`
- `capabilities`
- `available_tools`
- `executable_tools`
- `workspace_ids` through client workspace membership
- `transport_profile`
- host and transport metadata
- `last_seen_at`

The same `client_id` may have multiple `/client/ws` connections. Each connection can carry its own subscriptions, session context, and executable tool declaration.

## Tool Lists

Client tool filtering is split by direction:

- `available_tools`: tools the Client may request when it is the source.
- `executable_tools`: directed tools the Client may execute when it is the target.

Permission and governance use abstract `tool_key` values. Concrete provider ids use:

```text
client.<client_id>.<tool_key>
```

Examples:

- `client.desktop-main.file.read`
- `client.desktop-main.shell.exec`
- `client.home-edge.workspace.analyze`

## Tool Types

Undirected tools do not require `target_client_id`:

- web/search
- memory
- summarize
- skill
- server-side MCP or runtime-native Core tools

Directed tools require a target Client:

- `short_reply`
- endpoint notice
- `file.*`
- `shell.*`
- `workspace.*`
- desktop or edge local tools

## Realtime Frames

Client lifecycle:

- `client.hello`
- `client.tools.snapshot`
- `client.ready`
- `client.heartbeat`

Tool call lifecycle:

- `tool.call.request`
- `tool.call.accepted`
- `tool.call.progress`
- `tool.call.result`
- `tool.call.error`

Tool call arguments that cross the Core/Client boundary can be encrypted with the Client tool credential transport purpose.

## Dispatch Rules

`ClientToolDispatchService` is the Core-side dispatch boundary.

Dispatch flow:

1. Resolve `source_client_id`.
2. Verify the source Client may call `tool_key` via `available_tools`.
3. If the tool is directed, resolve `target_client_id`.
4. Verify the target Client is in the workspace and can execute `tool_key` via `executable_tools`.
5. Create/update operation and operation call rows with `target_client_id`, `tool_key`, and `tool_id`.
6. Send `tool.call.request` to the selected Client connection.
7. Record `tool.call.result` or `tool.call.error`.

Default target policy:

- `short_reply` / endpoint notice defaults to `self`.
- `file.*`, `shell.*`, and `workspace.*` default to a workspace-bound desktop Client that can execute the tool.
- Source/self is preferred when it can execute the tool.
- Workspace preferences are applied before fallback ordering.
- If no target is available, dispatch fails with `target_client_unavailable`; Core does not silently fall back to another target.

## Public API Names

Operation fields:

- `target_client_id`
- `tool_key`
- `tool_id`

Execution target values:

- `core_only`
- `specific_client`
- `workspace_any_client`
- `prefer_client_fallback_core`

Workspace/procedure governance fields:

- `preferred_target_client_ids`
- `preferred_target_client_types`
- `tool_target_routing_policy`
- `preferred_tool_key`
- `recommended_tools`

Frontend state names should describe Client tool target state, for example:

- `desktopToolClientId`
- `desktopToolsAvailable`

## Desktop And Edge

`desktop_client` and `edge_client` use the same `/client/ws` protocol.

Desktop-specific behavior:

- exposes local `/desktop/*` and `/desktop/ws` for the Electron UI
- usually executes `file.*`, `shell.*`, local MCP, and workspace local tools
- enforces local `read_roots`, `trusted_write_roots`, and command policy

Edge-specific behavior:

- usually joins one or more configured workspaces
- executes the edge node's declared tools
- uses the same operation/result path as Desktop Client

## Compatibility

The refactor is intentionally breaking:

- no formal Agent WebSocket endpoint
- no Agent registration repository/service
- no workspace Agent membership table
- no Agent capability snapshot table
- no `MEETYOU_AGENT_*` token path

Historical operation metadata may keep old text for audit, but live routing and new public API fields use Client/tool names only.
