# Deployment And Platform

## Deployment Units

Current release units:

- `Core Service`: `python -m service_runtime`
- `Desktop Product`: Electron UI + local `desktop_client` backend
- `Edge Client`: `python -m edge_client`

Core Service owns:

- PostgreSQL migration
- protocol negotiation
- Gateway routes
- operation / approval persistence
- Client tool dispatch policy

Desktop Product owns:

- Electron UI
- local loopback `/desktop/*` and `/desktop/ws`
- Desktop Client runtime connected to `GET /client/ws`
- local file, Shell, local MCP, and workspace directed tools

Edge Client owns:

- workspace-bound runtime connection
- edge-local directed tools
- heartbeat and tool result reporting

## Entrypoints And Requirements

Development:

```powershell
python main.py service
python main.py desktop-client
python main.py edge-client
```

Production:

```powershell
python -m service_runtime
python -m desktop_client
python -m edge_client
```

Dependency files:

```text
requirements-core.txt
requirements-desktop-client.txt
requirements-edge-client.txt
```

## Protocol Surface

All live Client runtimes use:

```text
GET /client/ws
meetyou.client.ws.v1
```

The live protocol carries:

- chat/client events
- `client.hello`
- `client.tools.snapshot`
- `client.ready`
- `client.heartbeat`
- `tool.call.*`

No server deployment should expose an old Agent runtime as a supported path.

## Packaging

Desktop backend packaging is wired through:

- `scripts/build-desktop-backend.ps1`
- `packaging/desktop-client/desktop_client.spec`
- `requirements-desktop-client.txt`

Packaged Electron should start the bundled `desktop_client` backend from the application resources. Development mode may fall back to:

```powershell
python main.py desktop-client
```

Runtime template files should use:

- `user/desktop_client.json`
- `.env`
- `MEETYOU_CORE_BASE_URL`
- `MEETYOU_GATEWAY_ACCESS_TOKEN`
- `MEETYOU_CLIENT_ACCESS_TOKEN`

Do not publish packaged artifacts that contain personal access tokens.

## Platform Matrix

| Capability | Windows Desktop | Linux Desktop | macOS Desktop | Core Server |
| --- | --- | --- | --- | --- |
| Core Service | Supported | Supported | Supported | Primary |
| Electron UI | Primary | Development only | Development only | Not a production target |
| Desktop Client file/Shell/workspace tools | Supported | Supported when policy allows | Supported when policy allows | Not owned by Core |
| Windows UIAutomation | Supported | Disabled | Disabled | Disabled |
| Edge Client | Supported | Supported | Supported | Optional runtime |

## Upgrade Order

For schema or protocol changes:

1. Snapshot PostgreSQL if rollback is required.
2. Upgrade Core Service and run Alembic migrations.
3. Confirm `GET /health` and `GET /client/ws`.
4. Upgrade Desktop Product and Edge Client.
5. Confirm Client tool snapshot, heartbeat, and a directed tool call.

Rollback safety:

- Core rollback is only safe when the matching PostgreSQL snapshot is available.
- Desktop/Edge Client rollback is limited to the compatibility window Core still supports.
- Current default compatibility promise is same-version plus adjacent-generation Core/Client releases.
