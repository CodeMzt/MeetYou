# User Templates

`user/` stores local runtime configuration, caches, and state files. Real runtime files are ignored by Git; the repository keeps only copyable templates.

Common templates:

- `config.example.json` -> `config.json`
- `config.docker.example.json` -> `config.json` for Docker / Compose runtime paths
- `tools.example.json` -> `tools.json`
- `core_mcp_servers.example.json` -> `core_mcp_servers.json`
- `mcp_servers.example.json` -> `mcp_servers.json`
- `cmd_policy.example.json` -> `cmd_policy.json`
- `source_catalog.example.json` -> `source_catalog.json`
- `memory_graph.example.json` -> `memory_graph.json`
- `feishu_chat_ids.example.json` -> `feishu_chat_ids.json`
- `desktop_client.example.json` -> `desktop_client.json`
- `edge_client.example.json` -> `edge_client.json`

Initialization helpers:

- `python scripts/prepare_core_runtime.py --profile host`
- `python scripts/prepare_core_runtime.py --profile docker --output-root deploy/docker/runtime`
- `python scripts/check_core_runtime.py --profile host --env-file .env`
- `python scripts/check_core_runtime.py --profile docker --runtime-root deploy/docker/runtime`

`desktop_client.json` common fields:

- `core_base_url`: Core Service base URL. Runtime connects to `GET /endpoint/ws`.
- `core_access_token`: access token used by the Desktop Endpoint Provider to access Core. It may also come from `MEETYOU_CLIENT_ACCESS_TOKEN` or `MEETYOU_GATEWAY_ACCESS_TOKEN`.
- `gateway_access_token`: token used by the desktop backend when proxying Core HTTP surfaces.
- `provider_id`: stable provider id for the Desktop Endpoint Provider.
- `display_name`: display name.
- `workspace_ids`: workspaces the provider declares membership in.
- `enabled_endpoint_tools`: executable EndpointCapability tool keys declared to Core.
- `read_roots`: local read roots.
- `trusted_write_roots`: trusted local write roots.
- `cmd_policy_path`: local command policy path.
- `mcp_servers_path`: local MCP config path owned by the Desktop Endpoint Provider.
- `transport_profile`: connection profile, default `desktop_wss`.
- `local_bridge_enabled`: enables the loopback `/desktop/*` HTTP / WS API used by Electron UI.
- `local_bridge_host` / `local_bridge_port`: local desktop backend bind address, default `127.0.0.1:38951`.

Local acceptance can temporarily set `MEETYOU_FEISHU_ENABLE=false` and `MEETYOU_MEETWECHAT_ENABLE=false` to keep external endpoints disabled without editing `user/config.json`.

`edge_client.json` common fields:

- `core_base_url`: Core Service base URL. Runtime connects to `GET /endpoint/ws`.
- `core_access_token`: access token used by the Edge Endpoint Provider to access Core.
- `provider_id`: stable provider id for the Edge Endpoint Provider.
- `provider_type`: edge executor provider type, default `edge`.
- `workspace_ids`: allowed workspace memberships.
- `enabled_endpoint_tools`: executable EndpointCapability tool keys declared to Core.
- `heartbeat_interval_seconds`: connection keepalive interval.
- `transport_profile`: connection profile, default `edge_wss`.

Protocol boundary:

- `desktop_client` and `edge_client` connect through `GET /endpoint/ws` with `meetyou.endpoint.ws.v4`.
- Lifecycle frames are `endpoint.hello`, `endpoint.capabilities.snapshot`, `endpoint.ready`, `endpoint.heartbeat`, and `endpoint.goodbye`.
- Tool frames are `tool.call.request`, `tool.call.result`, `tool.call.error`, and `tool.call.cancel`.
- One endpoint provider may open multiple `/endpoint/ws` connections; each connection can declare subscriptions, session context, and endpoint capabilities.
- Electron UI uses the local loopback `/desktop/*` API exposed by `desktop_client`.
- There is no formal `/agent/ws` runtime, and `MEETYOU_AGENT_*` access tokens must not be reintroduced.

MCP file boundary:

- `core_mcp_servers.json`: Core-side safe MCP only, suitable for server-side capabilities that do not depend on local endpoint presence.
- `mcp_servers.json`: Desktop Endpoint Provider local MCP only. It depends on the local machine, local permissions, and endpoint connectivity.
- Missing `core_mcp_servers.json` does not imply the Desktop Endpoint Provider `mcp_servers.json` is missing.
- Core runtime-native tools do not need to be configured in `core_mcp_servers.json`.

Runtime may generate:

- `memory_tasks.json`
- `memory_tasks.json.bak`

Recommended minimum first-run files:

- `config.json`
- `tools.json`
- `cmd_policy.json`
- `source_catalog.json`
- `memory_graph.json`
