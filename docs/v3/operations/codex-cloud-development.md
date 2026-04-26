# Codex Cloud Development

## Scope

Codex Cloud is suitable for:

- Core Service logic
- Gateway routes and protocol models
- Client tool dispatch policy
- database migrations and repositories
- frontend type-level work
- pure `desktop_client` / `edge_client` runtime logic

It is not sufficient for:

- Windows UIAutomation validation
- real Electron window behavior
- local desktop file/Shell policy acceptance on the user's machine
- packaged installer smoke tests

## Recommended Checks

Backend:

```powershell
python -m compileall core gateway tools desktop_client edge_client client_tool_sdk service_runtime main.py client_tool_protocol.py
python -m unittest tests.test_runtime_entrypoints tests.test_config_manager
```

Frontend:

```powershell
cd meetyou-ui
npm run typecheck
npm run test
```

Runtime entrypoints:

```powershell
python main.py service
python main.py desktop-client
python main.py edge-client
```

## Boundaries

- Do not treat `/ws` as a formal chat path.
- Do not restore an Agent runtime endpoint.
- Do not put user-device file/Shell/MCP execution into Core.
- Use Client/tool names in public API, docs, tests, and UI state.
- Historical docs outside `docs/v3/` can mention older designs, but new work should update V3 docs.
