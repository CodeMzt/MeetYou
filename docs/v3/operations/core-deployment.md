# Core Deployment

## Unit

Core Service is the server-side deployment unit:

```powershell
python -m service_runtime
```

It owns:

- FastAPI HTTP / WebSocket Gateway
- PostgreSQL migrations
- memory and runtime state
- tool registry and Client tool dispatch
- workspace/procedure/operation/approval governance

Desktop UI, `desktop_client`, and `edge_client` are not deployed into the Core server image as the primary chain.

## Requirements

- Python 3.10+
- PostgreSQL 14+
- network access to configured LLM providers
- `.env`
- `user/config.json`
- `user/tools.json`
- optional `user/core_mcp_servers.json`

Core dependency install:

```powershell
pip install -r requirements-core.txt
```

## Startup

Development:

```powershell
python main.py service
```

Production:

```powershell
python -m service_runtime
```

Health and protocol checks:

```text
GET /health
GET /client/ws
```

## Access Tokens

Recommended environment variables:

```dotenv
MEETYOU_GATEWAY_ACCESS_TOKEN=
MEETYOU_CLIENT_ACCESS_TOKEN=
MEETYOU_CREDENTIAL_SECRET=
```

`MEETYOU_GATEWAY_ACCESS_TOKEN` gates HTTP and WebSocket access when configured. `MEETYOU_CLIENT_ACCESS_TOKEN` is the unified Client/Core access token. Do not use Agent-specific token names in new deployments.

## Upgrade

1. Snapshot PostgreSQL if rollback must be supported.
2. Deploy Core.
3. Let `bootstrap_core_domain()` run Alembic migrations.
4. Confirm `GET /health`.
5. Confirm `/client/ws` accepts a Client hello.
6. Upgrade Desktop Product and Edge Client.

Rollback is only safe when the corresponding PostgreSQL snapshot is available.
