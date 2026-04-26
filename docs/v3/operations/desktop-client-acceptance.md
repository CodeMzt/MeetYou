# Desktop Client Acceptance

## Purpose

Validate the unified desktop product:

```text
Electron UI + desktop_client backend + /client/ws runtime
```

## Automated Checks

Backend slice:

```powershell
python -m compileall desktop_client client_tool_sdk gateway core
python -m unittest tests.test_runtime_entrypoints tests.test_config_manager
```

Frontend:

```powershell
cd meetyou-ui
npm run typecheck
npm run test
```

## Manual Chain

Use the repository acceptance script when a real desktop chain is required:

```powershell
scripts\manual-acceptance.cmd check
scripts\manual-acceptance.cmd start
```

Expected chain:

1. Core responds to `GET /health`.
2. Electron starts the local `desktop_client` backend.
3. Renderer connects to `/desktop/*` and `/desktop/ws`.
4. A desktop session is created or resumed.
5. `desktop_client` connects to `GET /client/ws`.
6. Core records Client heartbeat and tool snapshot.
7. Workspace Client query shows the Desktop Client as a directed tool target.
8. A harmless directed tool call completes and returns `tool.call.result`.

## Target Queries

Use Client/tool target surfaces, not legacy endpoint names:

- `/client/workspaces/{workspace_id}/clients?include_tools=true`
- `/operator/clients`

Healthy Desktop Client state should include:

- `client_id`
- `client_type`
- `transport_profile`
- `available_tools`
- `executable_tools`
- `last_seen_at`
- active connection count when reported by the gateway surface

## Local Policy

Before accepting file or Shell behavior, confirm:

- `read_roots` limits local reads
- `trusted_write_roots` limits writes
- command policy blocks denied commands
- local MCP servers are started only from `user/mcp_servers.json`
- Core does not bypass the Client and execute host actions directly

## Non-Windows

On Linux/macOS, validate only cross-platform Desktop Client behavior:

- local bridge startup
- `/client/ws` handshake
- file/Shell/workspace tools when policy allows

Windows UIAutomation behavior is Windows-only and should not be treated as available on other platforms.
