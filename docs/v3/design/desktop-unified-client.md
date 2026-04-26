# Desktop Unified Client

## Goal

The desktop product is one unit:

```text
Electron UI + desktop_client backend
```

The renderer talks to the local backend. The local backend talks to Core and executes local directed tools.

## Process Layout

```text
Electron main
  |- starts / monitors desktop_client backend
  |- injects local backend URL and local access token
  |- owns native windows and secure credential helpers

Renderer
  |- uses /desktop/* HTTP APIs
  |- uses /desktop/ws for realtime desktop bridge
  |- does not directly own Core protocol details

desktop_client backend
  |- exposes loopback /desktop/* and /desktop/ws
  |- creates desktop session
  |- connects to Core through GET /client/ws
  |- sends client.hello, client.tools.snapshot, client.ready, client.heartbeat
  |- executes tool.call.request and returns tool.call.result/error
```

## Local Tools

Desktop-local capabilities are directed tools:

- `file.read`
- `file.write`
- `shell.exec`
- `workspace.analyze`
- local MCP-backed tools
- short desktop notices/replies when targeted at the desktop session

The local backend enforces:

- `read_roots`
- `trusted_write_roots`
- command policy
- local MCP server lifecycle
- desktop bridge authentication

Core must not directly execute host file or Shell actions on behalf of the user device.

## Configuration

Default config path:

```text
user/desktop_client.json
```

Important fields:

- `client_id`
- `display_name`
- `workspace_ids`
- `core_base_url`
- `core_access_token`
- `gateway_access_token`
- `available_tools`
- `executable_tools`
- `read_roots`
- `trusted_write_roots`
- `cmd_policy_path`
- `mcp_servers_path`
- `transport_profile`
- `local_bridge_enabled`
- `local_bridge_host`
- `local_bridge_port`

Environment variables:

- `MEETYOU_DESKTOP_CLIENT_CONFIG`
- `MEETYOU_CORE_BASE_URL`
- `MEETYOU_CLIENT_ACCESS_TOKEN`
- `MEETYOU_GATEWAY_ACCESS_TOKEN`
- `MEETYOU_CREDENTIAL_SECRET`

## Startup Order

Default desktop startup:

1. Electron main starts.
2. Electron main starts the local `desktop_client` backend.
3. Renderer connects to local `/desktop/*`.
4. Renderer creates or resumes a desktop session.
5. `desktop_client` opens `/client/ws` and declares tool state.
6. Core can dispatch directed tools to the Desktop Client.

Backend-only debugging is still supported with:

```powershell
python -m desktop_client
```

## Acceptance

Minimum acceptance for desktop changes:

- local `/desktop/health` responds
- renderer can connect through the local bridge
- `/client/ws` receives `client.hello` and `client.tools.snapshot`
- Desktop Client becomes visible through Client/tool target queries
- at least one harmless directed tool call completes
- local write/Shell actions respect policy
