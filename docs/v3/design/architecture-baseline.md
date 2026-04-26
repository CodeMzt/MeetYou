# Architecture Baseline

## Current Shape

MeetYou V3 is `Core + Clients + Tools`.

- `Core Service`: server-side orchestration, Gateway, memory, tools, Heart, workspace governance, operations, approvals, and PostgreSQL persistence.
- `Desktop Client`: Electron UI plus `desktop_client` backend on the user device.
- `Edge Client`: workspace-bound runtime on remote or local edge nodes.
- `Tool`: the executable unit. Core-native tools run in Core; local capabilities run as directed tools on a target Client.

There is no separate endpoint/product Agent concept in the current runtime.

## Runtime Entrypoints

Development:

- `python main.py service`
- `python main.py cil`
- `python main.py desktop-client`
- `python main.py edge-client`
- `python main.py` / `python main.py launcher`

Production:

- `python -m service_runtime`
- `python -m desktop_client`
- `python -m edge_client`

Dependency sets:

- `requirements-core.txt`
- `requirements-desktop-client.txt`
- `requirements-edge-client.txt`

## Protocol

The formal realtime endpoint is:

```text
GET /client/ws
```

Protocol schema:

```text
meetyou.client.ws.v1
```

Lifecycle frames:

- `client.hello`
- `client.tools.snapshot`
- `client.ready`
- `client.heartbeat`

Tool call frames:

- `tool.call.request`
- `tool.call.accepted`
- `tool.call.progress`
- `tool.call.result`
- `tool.call.error`

The root `GET /ws` path only returns a compatibility error.

## Client And Tool Model

Client records hold identity and runtime declarations:

- `client_id`
- `client_type`
- `display_name`
- `status`
- `capabilities`
- `available_tools`
- `executable_tools`
- host metadata
- `transport_profile`
- `last_seen_at`

Tool routing rules:

- Source Client must be allowed by `available_tools`.
- Directed target Client must be allowed by `executable_tools`.
- Workspace membership is checked before dispatch.
- Target unavailability fails as `target_client_unavailable`; Core does not silently fall back.

Concrete provider ids use `client.<client_id>.<tool_key>`, while policy and governance match on abstract `tool_key`.

## Data Model Boundary

Live Agent tables and fields are removed from the head schema:

- no `agents`
- no `workspace_agent_memberships`
- no `agent_capability_snapshots`
- no `target_agent_id`
- no attachment/context Agent origin/source fields

Current operation fields:

- `target_client_id`
- `tool_key`
- `tool_id`

Current execution targets:

- `core_only`
- `specific_client`
- `workspace_any_client`
- `prefer_client_fallback_core`

## Platform Notes

- Core is intended for Linux server deployment, but can run on Windows/macOS for development.
- Desktop Client is Windows-first because Electron window behavior, `.cmd` scripts, PowerShell paths, and UIAutomation are Windows-oriented.
- File, Shell, local MCP, and workspace directed tools may still run cross-platform when their local policy allows it.
- Windows-only UI sensing stays behind `platform_layer`; it is not a Core responsibility.
