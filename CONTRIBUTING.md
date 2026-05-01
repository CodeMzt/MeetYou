# Contributing

Thanks for taking the time to improve MeetYou.

MeetYou is in active V4 development. Contributions should preserve the Core-owned Runtime + Endpoint Routing boundary described in [AGENTS.md](./AGENTS.md) and [docs/v4/](./docs/v4/).

## Development Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

cd meetyou-ui
npm install
```

Copy local templates before running the service:

```powershell
Copy-Item .env.example .env
Copy-Item user\config.example.json user\config.json
```

Do not commit real `.env`, `user/*.json`, logs, screenshots, packaged binaries, databases, or runtime state.

## Architecture Rules

- Keep Core responsible for Thread, Message, Run, Scheduler, Heartbeat, Memory, Operation, and Delivery.
- Keep providers as Endpoint Providers. Do not reintroduce Client-owned conversations, permissions, scheduler state, delivery semantics, or executable capabilities.
- Use `/runtime/*` for formal runtime HTTP and `GET /endpoint/ws` for the V4 provider WebSocket.
- Do not add `/client/*`, `/client/ws`, `source_client_id`, `target_client_id`, or `ClientToolDispatchService`.
- Route executable endpoint capabilities through ToolRouter and ExecutionTarget.
- Use SKILL as the reusable workflow guidance layer; do not recreate V3 Procedure APIs.

## Testing

Run the smallest relevant tests first, then broaden when the change crosses runtime boundaries.

Backend:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Frontend:

```powershell
cd meetyou-ui
npm run typecheck
npm run test
npm run build:ui
```

For Windows desktop installer packaging, run `npm run build` from `meetyou-ui/`.

Manual V4 acceptance:

```powershell
scripts\manual-acceptance.cmd check
```

For UI behavior changes, include a real browser or Electron visual check and keep generated artifacts in ignored local directories.

## Pull Requests

Before opening a PR:

- Explain the problem and the chosen fix.
- Keep changes scoped to the relevant boundary.
- Add or update tests for changed behavior.
- Update docs when startup modes, protocol contracts, configuration, validation flows, or public behavior change.
- Confirm no secrets, personal paths, private hostnames, tokens, cookies, or local runtime state are included.

## Commit Hygiene

Use clear commit messages and avoid mixing unrelated refactors with functional changes. This repository keeps historical docs for traceability, so do not delete old docs only because they describe V2/V3 history.
