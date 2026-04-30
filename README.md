# MeetYou

MeetYou 是一个以 LLM 为核心的个人智能体系统。当前主线是 **V4: Core-owned Runtime + Endpoint Routing**：

```text
Electron UI -> desktop_client backend ----\
CIL / HTTP surfaces -----------------------> Core Service -> Thread / Message / Run
Edge Endpoint Providers ------------------/        |        Scheduler / Heartbeat
External Endpoint Providers --------------/        v        Memory / Operation / Delivery
                                            ToolRouter -> ExecutionTarget
```

Core 统一拥有 Thread、Message、Run、Scheduler、Heartbeat、Memory、Operation 和 Delivery。Desktop、Edge、Feishu、WeChatBot、webhook、email 等只作为 Endpoint Provider 接入，不拥有会话、运行、调度、投递或工具执行语义。V4 的权威实现边界在 [AGENTS.md](./AGENTS.md) 和 [docs/v4/](./docs/v4/)；`docs/v3/`、`docs/archive/` 和历史计划文档只作为留痕资料保留。

## Current Architecture

### Core Service

Core 是服务端主链，负责：

- Thread / Message / Run runtime
- Scheduler / `system.heartbeat` / Memory / Operation / Delivery
- ToolRouter / ExecutionTarget 调度
- Actor / Workspace / RunPolicy 权限判断
- PostgreSQL 持久化与 Alembic migration
- FastAPI `/runtime/*` HTTP facade 和 `GET /endpoint/ws` WebSocket 协议

入口：

```powershell
python main.py service
python -m service_runtime
```

### Endpoint Provider

Endpoint Provider 是 Core 外部的连接与能力运行时。Provider 可以暴露一个或多个 Endpoint，例如 Desktop UI endpoint、Desktop executor endpoint、Edge executor endpoint。Provider 内部的人类可见目的地，例如飞书会话、微信群、微信私聊，必须建模为 `EndpointAddress`，不能再建模为 Client。

主要 Provider：

- `desktop_client/`: 桌面本地后端和本地执行能力，通过 `/endpoint/ws` 连接 Core。
- `edge_client/`: 边缘执行 Provider，按 workspace 暴露 endpoint capabilities。
- `endpoint_providers/`: Feishu、WeChatBot 等外部 Provider。
- `endpoint_tool_sdk/`: Endpoint WebSocket 协议、帧构造和 Provider runtime 基类。

入口：

```powershell
python main.py desktop-client
python main.py edge-client
python -m desktop_client
python -m edge_client
python -m endpoint_providers.feishu
python -m endpoint_providers.meetwechat
```

### Frontend

`meetyou-ui/` 是 Electron + React 桌面 UI。Renderer 默认访问本地 desktop backend；desktop backend 再代理到 Core 的 `/runtime/*`、`/operator/*` 或 `/developer/*`。Frontend 不应自行发明 Core 协议名。

关键文件：

- `meetyou-ui/electron/main.ts`: Electron main process。
- `meetyou-ui/src/main.tsx`: Renderer entry。
- `meetyou-ui/src/hooks/useMeetYou.ts`: UI 访问 Core 的主链 hook。
- `meetyou-ui/src/windowBridge.ts`: Electron bridge。

开发启动：

```powershell
cd meetyou-ui
npm install
npm run dev
```

## Repository Layout

```text
main.py               Development launcher and runtime entrypoints
core/                 Core assembly, lifecycle, domain services, state, modes
gateway/              FastAPI HTTP facade and V4 Endpoint WebSocket surface
service_runtime/      Production Core runtime entrypoint
endpoint_tool_sdk/    Endpoint protocol and Provider runtime SDK
desktop_client/       Desktop Endpoint Provider runtime and local backend
edge_client/          Edge Endpoint Provider runtime
endpoint_providers/   Feishu / WeChatBot external Endpoint Providers
meetyou-ui/           Electron + React desktop UI
tools/                Tool implementations registered through Core capability path
adapters/             LLM and external service adapters
sensors/              Input/output adapters and event sensors
platform_layer/       Host platform abstractions
prompt/               Prompt, assistant mode, and SKILL-facing guidance assets
docs/                 Documentation; V4 source of truth is docs/v4/
tests/                Automated regression tests
user/                 Local config templates and ignored runtime state
```

## Core HTTP Interface

Formal V4 HTTP facade is `/runtime/*`. Local Desktop may expose `/desktop/*` and proxy to `/runtime/*`, `/operator/*` or `/developer/*`; it must not proxy to old `/client/*`. Gateway auth can use `Authorization: Bearer <token>` or `X-API-Key: <token>` when configured.

Common runtime routes:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Process health probe. |
| `GET` | `/runtime/workspaces` | List visible workspaces and workspace execution policy. |
| `GET` | `/runtime/workspaces/{workspace_id}/endpoints` | List available endpoint capabilities for a workspace. |
| `GET` | `/runtime/threads` | List active threads. |
| `POST` | `/runtime/threads` | Create a thread. Runtime modes are `general`, `automation`, `danxi`. |
| `POST` | `/runtime/threads/default` | Resolve or create a default thread for a workspace/key. |
| `GET` | `/runtime/threads/{thread_id}` | Read thread metadata. |
| `DELETE` | `/runtime/threads/{thread_id}` | Soft delete/archive a thread where allowed. |
| `POST` | `/runtime/endpoint-sessions/resolve` | Resolve an Endpoint conversation into Core thread + session + binding. |
| `POST` | `/runtime/sessions` | Create a runtime session for an endpoint and thread. |
| `PATCH` | `/runtime/sessions/{session_id}/active-workspace` | Switch active workspace for a session. |
| `POST` | `/runtime/messages` | Persist an inbound message and trigger Core reply flow. |
| `GET` | `/runtime/threads/{thread_id}/messages` | List persisted messages for a thread. |
| `POST` | `/runtime/operations` | Create an operation routed through ToolRouter / ExecutionTarget. |
| `GET` | `/runtime/operations/{operation_id}` | Read operation state. |
| `POST` | `/runtime/sessions/{session_id}/confirm-response` | Resolve a confirmation request. |
| `POST` | `/runtime/sessions/{session_id}/human-input-response` | Resolve a human-input request. |
| `POST` | `/runtime/sessions/{session_id}/reply-control` | Send runtime reply-control action such as stop/regenerate guidance. |
| `POST` | `/runtime/approvals/{approval_id}/decision` | Approve or reject a pending operation approval. |
| `POST` | `/runtime/attachments/upload-ticket` | Create an attachment upload ticket. |
| `PUT` | `/runtime/attachments/upload/{ticket_id}` | Upload attachment bytes. |
| `POST` | `/runtime/attachments/{attachment_id}/complete` | Complete attachment metadata after upload. |
| `GET` | `/runtime/attachments/{attachment_id}/download-ticket` | Create a download ticket. |

Minimal Endpoint session flow:

```http
POST /runtime/endpoint-sessions/resolve
Authorization: Bearer <token>
Content-Type: application/json

{
  "endpoint_id": "feishu.main.ui",
  "workspace_id": "personal",
  "provider_type": "feishu",
  "endpoint_type": "feishu_ui",
  "conversation_key": "chat:oc_xxx",
  "address_id": "addr.feishu.group.oc_xxx",
  "thread_strategy": "per_conversation",
  "title": "Feishu group"
}
```

Response returns:

- `thread`: Core Thread; final assistant replies must be persisted here by MessageService.
- `session`: active runtime session bound to the endpoint.
- `binding`: Endpoint conversation to Core Thread binding.

Minimal message flow:

```http
POST /runtime/messages
Authorization: Bearer <token>
Content-Type: application/json

{
  "thread_id": "thr_xxx",
  "session_id": "ses_xxx",
  "endpoint_id": "feishu.main.ui",
  "workspace_id": "personal",
  "role": "user",
  "content": "帮我总结今天的安排",
  "metadata": {
    "source_kind": "feishu",
    "address_id": "addr.feishu.group.oc_xxx"
  }
}
```

Important runtime rules:

- Delivery is responsible for delivering `message`、`run_event`、`notice`、`operation_update`; Delivery must not generate replies.
- Streaming flows through RunEventLog plus Delivery fan-out.
- `assistant.progress_notice` is a RunEvent / Runtime Action. It must not go through ToolRouter, must not create Operation / OperationCall, and must not become final assistant message content.
- Tool dispatch flows through ToolRouter plus ExecutionTarget. Permissions live on Actor / Workspace / RunPolicy; execution ability lives on EndpointCapability.

## Endpoint WebSocket Protocol

The only V4 real-time Provider entrypoint is:

```http
GET /endpoint/ws
Authorization: Bearer <token>
```

Envelope schema is `meetyou.endpoint.ws.v4`. Every frame is a JSON object:

```json
{
  "schema": "meetyou.endpoint.ws.v4",
  "type": "endpoint.hello",
  "message_id": "msg_...",
  "sent_at": "2026-04-30T00:00:00Z",
  "endpoint_id": "desktop.main.executor",
  "correlation_id": "",
  "payload": {}
}
```

### Lifecycle

Provider handshake order:

1. Provider sends `endpoint.hello`.
2. Core replies `endpoint.hello.ack`.
3. Provider sends `endpoint.capabilities.snapshot` when Core requests `requires_capabilities_snapshot`.
4. Core replies `endpoint.ready`.
5. Provider sends periodic `endpoint.heartbeat`.
6. Provider sends `endpoint.goodbye` before intentional disconnect.

`endpoint.hello` must include a V4 protocol offer. Missing protocol offers are rejected; Core no longer keeps legacy WebSocket compatibility handlers.

```json
{
  "type": "endpoint.hello",
  "payload": {
    "provider": {
      "provider_type": "desktop",
      "provider_id": "desktop-main",
      "display_name": "Desktop Main",
      "transport_profile": "desktop_wss",
      "supports_markdown": true
    },
    "endpoints": [
      {
        "endpoint_id": "desktop.desktop-main.ui",
        "endpoint_type": "desktop_ui",
        "roles": ["input", "output"],
        "workspace_ids": ["personal"],
        "supports_markdown": true
      },
      {
        "endpoint_id": "desktop.desktop-main.executor",
        "endpoint_type": "desktop_executor",
        "roles": ["execution"],
        "workspace_ids": ["personal"],
        "supports_markdown": true
      }
    ],
    "protocol": {
      "schema": "meetyou.endpoint.ws.v4",
      "version": 4,
      "supported_schemas": ["meetyou.endpoint.ws.v4"],
      "supported_versions": [4],
      "features": [
        "tool_snapshot_optional",
        "connection_prompt",
        "feature_negotiation",
        "heartbeat_interval_negotiation",
        "hello_reject_reason"
      ],
      "required_features": []
    }
  }
}
```

Successful `endpoint.hello.ack`:

```json
{
  "type": "endpoint.hello.ack",
  "payload": {
    "accepted": true,
    "protocol": {
      "selected_schema": "meetyou.endpoint.ws.v4",
      "selected_version": 4,
      "enabled_features": ["tool_snapshot_optional", "connection_prompt"],
      "disabled_features": [],
      "compatibility_mode": "negotiated"
    },
    "connection_id": "conn_xxx",
    "requires_capabilities_snapshot": true,
    "heartbeat_interval_seconds": 20,
    "registered_endpoints": ["desktop.desktop-main.ui", "desktop.desktop-main.executor"]
  }
}
```

Rejected handshake uses `accepted=false` and `reject_reason.code`, for example `endpoint_protocol_required`, `unsupported_endpoint_protocol`, or `unsupported_endpoint_features`.

### Capabilities

Capabilities are endpoint execution abilities. They are not Client permissions.

```json
{
  "type": "endpoint.capabilities.snapshot",
  "endpoint_id": "desktop.desktop-main.executor",
  "payload": {
    "endpoint_id": "desktop.desktop-main.executor",
    "revision": 1,
    "capabilities": [
      {
        "capability_id": "endpoint.desktop.desktop-main.executor.shell.exec",
        "tool_id": "endpoint.desktop.desktop-main.executor.shell.exec",
        "tool_key": "shell.exec",
        "display_name": "Shell Exec",
        "enabled": true,
        "risk_level": "write",
        "input_schema": {"type": "object"}
      }
    ]
  }
}
```

Core stores the snapshot on EndpointCapability and invalidates ToolRouter cache. Tool routing decisions should use abstract `tool_key` plus policy, then target an `execution_target_id` / endpoint capability.

### EndpointAddress

Provider-internal destinations are `EndpointAddress` records. Use these frames when the Provider discovers or changes human-visible delivery targets:

- `endpoint.addresses.snapshot`
- `endpoint.address.upsert`
- `endpoint.address.delete`

Address payload fields:

```json
{
  "address_id": "addr.feishu.group.oc_xxx",
  "endpoint_id": "feishu.main.ui",
  "provider_type": "feishu",
  "address_type": "group",
  "external_ref": "oc_xxx",
  "display_name": "Project Group",
  "workspace_scope": ["personal"],
  "status": "sendable",
  "capabilities": ["receive_message"],
  "metadata": {"supports_markdown": false}
}
```

Address-targeted `delivery.message` and `delivery.notice` payloads include:

- `target_address_id`
- `target_provider_type`
- `target_address_type`
- `target_external_ref`

### Subscriptions

Provider can subscribe to Core events:

- `subscription.start`
- `subscription.update`
- `subscription.stop`

Common subscription payload:

```json
{
  "subscription_id": "sub-thread-1",
  "target_type": "thread",
  "target_id": "thr_xxx",
  "last_seen_event_seq": 0
}
```

Core replies with `subscription.ack` and fans out matching `delivery.run_event`, `delivery.message`, `delivery.notice`, and `delivery.operation_update` frames.

### Delivery Frames

Core-to-Provider delivery frame types:

- `delivery.message`: human-visible message delivery.
- `delivery.run_event`: streaming chunks, progress notices, durable run state.
- `delivery.notice`: non-message notice.
- `delivery.operation_update`: operation/tool execution state.
- `delivery.inbox_item`: inbox item delivery where supported.

Delivery must not generate assistant replies. Final assistant replies are persisted as assistant Messages first, then delivered.

### Tool Frames

Core requests endpoint execution with `tool.call.request`:

```json
{
  "type": "tool.call.request",
  "endpoint_id": "desktop.desktop-main.executor",
  "payload": {
    "operation_id": "op_xxx",
    "call_id": "call_xxx",
    "workspace_id": "personal",
    "tool_id": "endpoint.desktop.desktop-main.executor.shell.exec",
    "tool_key": "shell.exec",
    "arguments": {"cmd": "echo ok"},
    "encrypted_arguments": {}
  }
}
```

Provider responses:

- `tool.call.accepted`: optional accepted signal.
- `tool.call.progress`: optional progress signal.
- `tool.call.result`: final success result.
- `tool.call.error`: final failure result.
- `tool.call.cancel`: cancellation signal where implemented.

Danxi credentials and WebVPN cookies must use encrypted transport. Never log plaintext email, password, cookie, token, encrypted payload plaintext, or credential snapshots.

## Develop A New Endpoint Provider

1. Add a provider config with `provider_id`, `provider_type`, `workspace_ids`, Core base URL, and `core_access_token`.
2. Connect to `GET /endpoint/ws` with `Authorization: Bearer <core_access_token>` or `X-API-Key`.
3. Send `endpoint.hello` with provider metadata, endpoint rows, and V4 protocol offer.
4. Send `endpoint.capabilities.snapshot` for execution endpoints.
5. Send `endpoint.addresses.snapshot` if the provider has human-visible destinations.
6. For inbound human messages, call `/runtime/endpoint-sessions/resolve`, then `/runtime/messages`.
7. Subscribe to the bound thread if the provider needs streaming/delivery fan-out.
8. Execute `tool.call.request` only inside the Provider runtime and return `tool.call.result` / `tool.call.error`.

Do not add `/client/ws`, `source_client_id`, `target_client_id`, Client-owned permissions, Client-owned executable capabilities, or `ClientToolDispatchService`. The old root-level `endpoint_tool_protocol.py` shim is removed; import protocol helpers from `endpoint_tool_sdk.protocol`.

## Install

Full development environment:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cd meetyou-ui
npm install
```

Production dependency layers:

```powershell
pip install -r requirements-core.txt
pip install -r requirements-desktop-client.txt
pip install -r requirements-edge-client.txt
```

## Configure

`user/config.json` is required. Copy templates before first startup. Secrets belong in `.env`.

```powershell
copy user\config.example.json user\config.json
copy user\tools.example.json user\tools.json
copy user\cmd_policy.example.json user\cmd_policy.json
copy user\source_catalog.example.json user\source_catalog.json
copy user\memory_graph.example.json user\memory_graph.json
copy user\desktop_client.example.json user\desktop_client.json
copy user\edge_client.example.json user\edge_client.json
```

Common environment variables:

```dotenv
MEETYOU_DATABASE_URL=
MEETYOU_GATEWAY_ACCESS_TOKEN=
MEETYOU_CLIENT_ACCESS_TOKEN=
MEETYOU_CORE_BASE_URL=http://127.0.0.1:8000
MEETYOU_FEISHU_ENABLE=false
MEETYOU_MEETWECHAT_ENABLE=false
MEETYOU_CREDENTIAL_SECRET=
```

Notes:

- `MEETYOU_CLIENT_ACCESS_TOKEN` is still the deployed variable name for Endpoint Provider access to Core. Do not introduce `MEETYOU_AGENT_*`.
- `user/core_mcp_servers.json` is for Core-side safe MCP only.
- `user/mcp_servers.json` is for Desktop Provider local MCP only.
- `user/` runtime state is ignored; Git keeps only examples and `user/README.md`.

## Start

Launcher:

```powershell
python main.py
```

Development entrypoints:

```powershell
python main.py service
python main.py cil
python main.py desktop-client
python main.py edge-client
```

Production entrypoints:

```powershell
python -m service_runtime
python -m desktop_client
python -m edge_client
```

Desktop chain should be verified as:

```text
service -> UI -> desktop backend managed by UI -> desktop provider session -> /endpoint/ws runtime
```

Linux systemd deployment helpers:

```bash
sudo bash scripts/linux/install-core-systemd.sh
sudo bash scripts/linux/install-feishu-provider-systemd.sh
sudo bash scripts/linux/install-meetwechat-provider-systemd.sh
```

## Verify

Backend focused checks:

```powershell
python -m compileall core gateway tools desktop_client edge_client endpoint_tool_sdk service_runtime main.py
python -m compileall endpoint_providers
python -m unittest tests.test_gateway_runtime_api tests.test_gateway_surface_routes tests.test_endpoint_tool_protocol tests.test_endpoint_provider_protocols
```

Frontend checks:

```powershell
cd meetyou-ui
npm run typecheck
npm run test
npm run build
```

Frontend acceptance cannot stop at typecheck/unit tests. Any UI behavior or layout change must run a real browser or Electron session and save screenshots under an ignored local artifact directory such as `meetyou-ui/visual-artifacts/`; the completion note must include the screenshot path.

Cross-surface or release-level verification:

```powershell
scripts\manual-acceptance.cmd start
scripts\manual-acceptance.cmd check
```

V4 release-grade verification should cover Python tests, frontend typecheck/build/test, migration tests, endpoint protocol tests, scheduler tests, tool router tests, delivery tests, local Core + Desktop + UI, remote Core health/version, and real Feishu/WeChatBot messages with human confirmation. Record results in [docs/v4/test-report.md](./docs/v4/test-report.md).

## Publish

- `main` is the publish branch. Completed work must be committed, pushed, and merged back to `main`.
- Desktop Release artifacts are published to GitHub Releases when a tag matching `desktop-v*` is pushed, or when the workflow is manually dispatched with a tag. The workflow stages only non-empty top-level installer assets from `meetyou-ui/release/` into `meetyou-ui/release-assets/`, then uploads those staged assets. It does not upload `win-unpacked/` internals, bundled Python package metadata, DLLs, or Electron language packs as individual Release assets.
- Release artifacts, packaged runtime templates, screenshots, caches, logs, local `.env`, real `user/*.json`, and runtime databases must not be committed.
- Core Service owns database migration and protocol negotiation. Only claim safe Core rollback when the matching PostgreSQL snapshot is retained.
- External Provider failure must not block Core deployment; providers can reconnect to `/endpoint/ws` after Core is healthy.

## Documentation

- [AGENTS.md](./AGENTS.md): repository rules, boundaries, verification order, publish requirements.
- [docs/v4/meetyou-v4-design.md](./docs/v4/meetyou-v4-design.md): V4 architecture design.
- [docs/v4/meetyou-v4-plan.md](./docs/v4/meetyou-v4-plan.md): V4 implementation plan.
- [docs/v4/meetyou-v4-scheduled-workflows.md](./docs/v4/meetyou-v4-scheduled-workflows.md): Scheduled Workflow.
- [docs/v4/meetyou-v4-endpoint-address-scheduled-delivery.md](./docs/v4/meetyou-v4-endpoint-address-scheduled-delivery.md): EndpointAddress scheduled delivery.
- [docs/v4/test-report.md](./docs/v4/test-report.md): V4 verification report.
- [user/README.md](./user/README.md): local config directory rules.
