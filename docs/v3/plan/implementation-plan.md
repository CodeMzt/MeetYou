# V3 Implementation Plan

## Current Phase: Core + Client + Tools

The current implementation line removes endpoint-level Agent runtime concepts and converges the system on:

```text
Core + Clients + Tools
```

## Completed Direction

- `tool` is the executable abstraction.
- Local execution is a directed tool, not a separate runtime category.
- `Client` owns identity, workspace membership, connection state, and tool declarations.
- Core owns orchestration, policy, persistence, operation/approval, and dispatch.
- `desktop_client` and `edge_client` use the same `/client/ws` protocol.
- Desktop delivery is one product: Electron UI + `desktop_client` backend.

## Required Code Shape

Data:

- Remove live Agent repositories/services/tables from head schema.
- Extend Client metadata with `available_tools`, `executable_tools`, host metadata, `transport_profile`, and `last_seen_at`.
- Use `target_client_id` on operations and operation calls.
- Use `origin_client_id` / `source_client_id` where origin/source ownership is still needed.
- Match policy on abstract `tool_key`; concrete providers use `client.<client_id>.<tool_key>`.

Protocol:

- Use `GET /client/ws` as the single realtime endpoint.
- Use `meetyou.client.ws.v1`.
- Use `client.hello`, `client.tools.snapshot`, `client.ready`, `client.heartbeat`, and `tool.call.*`.

Dispatch:

- `ClientToolDispatchService` resolves source Client first.
- Source Client must allow `tool_key` via `available_tools`.
- Directed target Client must allow `tool_key` via `executable_tools`.
- Workspace membership is checked before dispatch.
- Target unavailable fails with `target_client_unavailable`; no silent fallback.

Naming:

- `client_tool_sdk/`
- `desktop_client/`
- `edge_client/`
- `requirements-desktop-client.txt`
- `requirements-edge-client.txt`
- `python main.py desktop-client`
- `python main.py edge-client`
- `python -m desktop_client`
- `python -m edge_client`

## Validation Plan

Backend minimum:

```powershell
python -m compileall core gateway tools desktop_client edge_client client_tool_sdk service_runtime main.py client_tool_protocol.py
python -m unittest tests.test_runtime_entrypoints tests.test_config_manager
```

Database/protocol work should additionally cover:

- bootstrap/migration head schema
- Client websocket hello/tool snapshot/heartbeat
- directed tool call result/error
- operation creation with `target_client_id`, `tool_key`, `tool_id`

Frontend:

```powershell
cd meetyou-ui
npm run typecheck
npm run test
```

Desktop chain:

```powershell
scripts\manual-acceptance.cmd check
```

## Documentation Scope

Keep these documents current for V3 work:

- `README.md`
- `AGENTS.md`
- `user/README.md`
- `.env.example`
- `docs/v3/design/architecture-baseline.md`
- `docs/v3/design/client-tools.md`
- `docs/v3/design/desktop-unified-client.md`
- `docs/v3/design/deployment-and-platform.md`
- `docs/v3/operations/core-deployment.md`
- `docs/v3/operations/desktop-client-acceptance.md`

Historical references outside `docs/v3/` are not the active design source.
