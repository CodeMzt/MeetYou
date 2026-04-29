# MeetYou

MeetYou 是一个以 LLM 为核心的个人智能体系统。V4 当前架构目标是 **Core-owned Runtime + Endpoint Routing**：

```text
Electron UI -> desktop_client backend ----\
CIL / HTTP / Web endpoints ----------------> Core Service -> Thread / Message / Run
edge endpoint providers ------------------/        |        Scheduler / Heartbeat
external endpoints -----------------------/        v        Memory / Operation / Delivery
                                           ToolRouter -> ExecutionTarget
```

核心原则：

- `Core Service` owns Thread / Message / Run / Scheduler / Heartbeat / Memory / Operation / Delivery。
- `Client` 不再是调度主体，只是 Endpoint Provider；Desktop、Edge、Feishu、WeChatBot 等都通过 Endpoint 暴露输入、输出或执行能力。
- Core is not Client；`core.local` 是 in-process `ExecutionTarget`，不是 Client。
- Scheduler 是唯一系统级调度时钟；`system.heartbeat` 是 Scheduler 内不可删除、可启停、可修改间隔的系统预设 Job。
- `endpoint.heartbeat` 只是连接保活，不触发 `system.heartbeat`。
- `short_reply` 不再作为 directed tool；由 `assistant.progress_notice` RunEvent / Runtime Action 替代。
- Delivery 只负责投递 `message` / `run_event` / `notice` / `operation_update`，不负责生成回复。
- Final assistant reply 必须是 MessageService 持久化的 assistant message。
- Streaming 必须走 RunEventLog + Delivery fan-out。
- Tool 调度必须走 ToolRouter + ExecutionTarget；权限挂在 Actor / Workspace / RunPolicy，执行能力挂在 EndpointCapability。
- V4 HTTP facade 是 `/runtime/*`；桌面本地 `/desktop/*` 只代理到 `/runtime/*`、`/operator/*`、`/developer/*`，不代理旧 `/client/*`。
- V4 不保留 `/client/ws`、`source_client_id`、`target_client_id`、`ClientToolDispatchService` 兼容路径。
- 运行态助手模式只保留 `general` / `automation` / `danxi`；旧 `normal` / `office` 等输入只在边界归一化。
- Procedure 已删除；可复用工作流统一通过 SKILL（`list_skills` / `load_skill` / `create_skill`）和能力注册表暴露，SKILL 查询会按标题、摘要、场景和推荐工具匹配。

当前生效的设计与计划文档在 `docs/v4/`；`docs/v3/` 和 `docs/archive/v2/` 是历史参考。

## 架构边界

### Core Service

Core 是服务端主链：

- FastAPI HTTP / WebSocket Gateway
- Thread / Message / Run runtime
- Scheduler / Heartbeat / Memory / Operation / Delivery
- workspace、approval、RunPolicy、SKILL capability governance
- PostgreSQL 持久化与 Alembic migration
- ToolRouter / ExecutionTarget 调度与权限判断

生产入口：

```bash
python -m service_runtime
```

开发入口：

```bash
python main.py service
```

### Desktop Endpoint Provider

`desktop_client/` 是桌面本地后端，与 Electron UI 一起构成统一桌面端：

- 承载 UI 使用的本地 `/desktop/*` HTTP / WS API
- 通过 `GET /endpoint/ws` 连接 Core
- 声明 endpoint capabilities
- 执行本地文件、Shell、本地 MCP、workspace local 等 endpoint execution capabilities
- 由本地配置限制 `read_roots`、`trusted_write_roots`、`cmd_policy_path`、`mcp_servers_path`

生产入口：

```bash
python -m desktop_client
```

开发入口：

```bash
python main.py desktop-client
```

### Edge Endpoint Provider

`edge_client/` 是按 workspace 接入的边缘运行时：

- 通过 `GET /endpoint/ws` 接入 Core
- 以 `workspace_ids`、`provider_type`、`transport_profile`、endpoint capabilities 描述边缘能力
- 执行被 Core 调度到该 Endpoint 的 execution target tools

生产入口：

```bash
python -m edge_client
```

开发入口：

```bash
python main.py edge-client
```

### Frontend

`meetyou-ui/` 是 Electron + React 桌面 UI：

- `meetyou-ui/electron/main.ts`：Electron main process
- `meetyou-ui/src/main.tsx`：renderer 入口
- 默认连接本地 desktop backend：`http://127.0.0.1:38951`
- renderer 仍走 `/desktop/*` 和 `/desktop/ws`，由 desktop backend 代理需要访问 Core 的 surface

开发入口：

```bash
cd meetyou-ui
npm install
npm run dev
```

## 协议

唯一正式实时入口：

```text
GET /endpoint/ws
```

协议 schema：

```text
meetyou.endpoint.ws.v4
```

核心帧：

- `endpoint.hello`
- `endpoint.capabilities.snapshot`
- `endpoint.ready`
- `endpoint.heartbeat`
- `endpoint.goodbye`
- `subscription.start`
- `subscription.update`
- `subscription.stop`
- `delivery.message`
- `delivery.run_event`
- `delivery.notice`
- `delivery.operation_update`
- `tool.call.request`
- `tool.call.result`
- `tool.call.error`
- `tool.call.cancel`

同一 endpoint provider 可以有多条 `/endpoint/ws` 连接。每条连接可以分别声明：

- 订阅
- endpoint capabilities
- host / transport metadata

### 外接 Endpoint Provider 协议

外接 Provider 是独立进程，不由 Core 生命周期启动。Core 只负责 `/runtime/*`、`GET /endpoint/ws`、Endpoint/Address 状态、Delivery fan-out、ToolRouter 调度和 Outbox 重试。Provider 崩溃或重启不应阻塞 Core 启动。

认证支持：

- `Authorization: Bearer <MEETYOU_CLIENT_ACCESS_TOKEN>`
- `X-API-Key: <MEETYOU_CLIENT_ACCESS_TOKEN>`

连接顺序：

1. `GET /endpoint/ws` 建立 WebSocket，schema 固定为 `meetyou.endpoint.ws.v4`。
2. 发送 `endpoint.hello`，声明 provider、endpoint、workspace、roles、`supports_markdown`。
3. 发送 `endpoint.capabilities.snapshot`，声明可执行 tool key。
4. 发送 `endpoint.ready`，然后按需发送 `endpoint.heartbeat`。
5. 需要接收线程事件时发送 `subscription.start`；需要暴露 Feishu/WeChat 群聊等 provider 内部目的地时发送 `endpoint.addresses.snapshot` 或 `endpoint.address.upsert`。

`supports_markdown` 默认是 `true`。Feishu、WeChatBot、短信、邮件纯文本模板等不支持 Markdown 的 Provider 必须在 `provider`、`endpoints[]` 或 `address.metadata` 中声明 `supports_markdown=false`；Delivery 在投递 `message`、`notice`、`assistant.progress_notice` 和 final run event 前会降级为纯文本。

最小 hello 示例：

```json
{
  "schema": "meetyou.endpoint.ws.v4",
  "type": "endpoint.hello",
  "message_id": "hello-1",
  "payload": {
    "connection_id": "conn-provider-1",
    "provider": {
      "provider_type": "wechat",
      "provider_id": "wechat-provider",
      "display_name": "WeChat Provider",
      "transport_profile": "external_ws",
      "supports_markdown": false
    },
    "endpoints": [
      {
        "endpoint_id": "wechat.provider.ui",
        "endpoint_type": "wechat_ui",
        "roles": ["input", "output"],
        "workspace_ids": ["personal"],
        "supports_markdown": false
      }
    ]
  }
}
```

最小能力与地址示例：

```json
{
  "schema": "meetyou.endpoint.ws.v4",
  "type": "endpoint.capabilities.snapshot",
  "endpoint_id": "wechat.provider.ui",
  "payload": {
    "endpoint_id": "wechat.provider.ui",
    "capabilities": [
      {
        "tool_key": "send_delivery_message",
        "risk_level": "write",
        "requires_confirmation": false,
        "enabled": true
      }
    ]
  }
}
```

```json
{
  "schema": "meetyou.endpoint.ws.v4",
  "type": "endpoint.address.upsert",
  "endpoint_id": "wechat.provider.ui",
  "payload": {
    "endpoint_id": "wechat.provider.ui",
    "address": {
      "address_id": "addr.wechat.group.example",
      "provider_type": "wechat",
      "address_type": "group",
      "external_ref": "example",
      "display_name": "Example Group",
      "workspace_ids": ["personal"],
      "status": "sendable",
      "supports_markdown": false,
      "metadata": { "supports_markdown": false }
    }
  }
}
```

禁止事项：

- 不要连接或恢复 `/client/ws`。
- 不要发送 `source_client_id` / `target_client_id`。
- 不要把 provider 内部聊天对象建成 Client；它们必须是 `EndpointAddress`。

## Tool 模型

所有工具调用都先经 ToolRouter 解析 ExecutionTarget，再由对应 executor 执行：

- `CoreToolExecutor`：`core.local` in-process execution target。
- `EndpointToolExecutor`：Desktop / Edge execution endpoint。
- `ExternalToolExecutor`：Feishu / WeChatBot / webhook / email 等 external endpoint 或 adapter。

权限与能力拆分：

- Actor / Workspace / RunPolicy 决定允许调用哪些抽象 tool key。
- EndpointCapability 描述哪个 endpoint 能执行哪些 tool key。
- `assistant.progress_notice` 是 Runtime Action / RunEvent，不是 tool，不创建 Operation。

Operation 公共字段：

- `tool_key`
- `tool_id`
- `execution_target_id`
- `target_endpoint_id`
- `requested_by_actor_id`
- `requested_by_run_id`

Workspace / RunPolicy governance 公共字段：

- `preferred_execution_target_ids`
- `preferred_endpoint_types`
- `tool_target_routing_policy`

## 目录结构

```text
core/                 Core 编排、会话、状态、模式路由、应用生命周期
gateway/              FastAPI HTTP / WebSocket Gateway
service_runtime/      Core 生产运行入口
endpoint_tool_sdk/    Endpoint protocol / runtime SDK 正式入口
desktop_client/       桌面本地后端与 Endpoint tool runtime
edge_client/          边缘 Endpoint Provider runtime
endpoint_providers/  Feishu / WeChatBot 等独立外部 Endpoint Provider runtime
meetyou-ui/           Electron + React 桌面端
tools/                Core tool 集合
adapters/             LLM 与外部服务适配器
sensors/              输入/输出适配层与系统感知
platform_layer/       Core 宿主机感知抽象
prompt/               系统、模式与技能提示词
docs/                 文档入口；当前真源在 docs/v4/
tests/                自动化回归测试
user/                 本地配置模板与运行态数据目录
```

## 安装

开发全量安装：

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

生产分层安装：

```powershell
pip install -r requirements-core.txt
pip install -r requirements-desktop-client.txt
pip install -r requirements-edge-client.txt
```

前端：

```powershell
cd meetyou-ui
npm install
```

## 配置

复制模板：

```powershell
copy user\config.example.json user\config.json
copy user\tools.example.json user\tools.json
copy user\cmd_policy.example.json user\cmd_policy.json
copy user\source_catalog.example.json user\source_catalog.json
copy user\memory_graph.example.json user\memory_graph.json
copy user\desktop_client.example.json user\desktop_client.json
copy user\edge_client.example.json user\edge_client.json
```

关键环境变量：

```dotenv
MEETYOU_DATABASE_URL=
MEETYOU_GATEWAY_ACCESS_TOKEN=
MEETYOU_CLIENT_ACCESS_TOKEN=
MEETYOU_CORE_BASE_URL=http://127.0.0.1:8000
MEETYOU_FEISHU_ENABLE=false
MEETYOU_MEETWECHAT_ENABLE=false
MEETYOU_DESKTOP_PROVIDER_ID=desktop-main-provider
MEETYOU_DESKTOP_PROVIDER_DISPLAY_NAME=Desktop Endpoint Provider
MEETYOU_DESKTOP_PROVIDER_WORKSPACES=desktop-main
MEETYOU_CREDENTIAL_SECRET=
```

说明：

- `MEETYOU_GATEWAY_ACCESS_TOKEN` 用于 Gateway HTTP / WebSocket 鉴权。
- `MEETYOU_CLIENT_ACCESS_TOKEN` 是 Endpoint Provider 访问 Core 的统一访问令牌（变量名暂沿用，语义已是 Endpoint）。
- 不要新增或恢复 `MEETYOU_AGENT_*`。
- `user/config.json` 是必需文件；密钥放 `.env`。
- `user/core_mcp_servers.json` 只给 Core 侧安全 MCP。
- `user/mcp_servers.json` 只给 Desktop Endpoint Provider 本地 MCP。

## 启动

开发态：

```powershell
python main.py service
python main.py cil
python main.py desktop-client
python main.py edge-client
python -m endpoint_providers.feishu
python -m endpoint_providers.meetwechat
```

Launcher：

```powershell
python main.py
```

Launcher 命令：

```text
start service
start cil
start ui
status
exit
```

生产态：

```powershell
python -m service_runtime
python -m desktop_client
python -m edge_client
python -m endpoint_providers.feishu
python -m endpoint_providers.meetwechat
```

Linux systemd deployment:

```bash
sudo bash scripts/linux/install-core-systemd.sh
sudo bash scripts/linux/install-feishu-provider-systemd.sh
sudo bash scripts/linux/install-meetwechat-provider-systemd.sh
sudo systemctl enable --now meetyou-core.service
sudo systemctl enable --now meetyou-feishu-provider.service
sudo systemctl enable --now meetyou-meetwechat-provider.service
```

Feishu and WeChatBot are V4 Endpoint Provider processes. They may run on the same host as Core and use `MEETYOU_CORE_BASE_URL=http://127.0.0.1:8000`, or connect to a remote Core by setting `MEETYOU_CORE_BASE_URL=https://...`. Core deploy attempts to restart these optional provider services when present, but provider failure must not block Core deployment.

桌面主链默认顺序：

```text
service -> UI -> desktop backend(由 UI 托管) -> desktop provider session -> /endpoint/ws runtime
```

## 验证

后端最小验证：

```powershell
python -m compileall core gateway tools desktop_client edge_client endpoint_tool_sdk service_runtime main.py endpoint_tool_protocol.py
python -m compileall endpoint_providers
python -m unittest tests.test_runtime_entrypoints tests.test_config_manager
```

前端验证：

```powershell
cd meetyou-ui
npm run typecheck
npm run test
```

桌面主链人工验收：

```powershell
scripts\manual-acceptance.cmd check
scripts\manual-acceptance.cmd start
```

## 发布与回滚

- Core Service 持有数据库 migration 与协议协商主导权。
- 发布涉及数据库 schema 时，先升级 Core，再升级 Desktop / Edge Endpoint Provider / UI。
- 只有保留对应 PostgreSQL 快照时，才可以宣称 Core 可安全回滚。
- 当前默认只承诺 Core / Endpoint Provider 同版与相邻一代发布的兼容窗口。

## 参考文档

- `docs/v3/design/architecture-baseline.md`
- `docs/v3/design/client-tools.md`
- `docs/v3/design/deployment-and-platform.md`
- `docs/v3/operations/core-deployment.md`
- `docs/v3/design/desktop-unified-client.md`
- `docs/v3/operations/desktop-client-acceptance.md`
- `user/README.md`

## V4 Scheduled Workflow / EndpointAddress

- Endpoint represents Provider runtime health; Feishu/WeChat chats and groups are `EndpointAddress` destinations.
- User-facing recurring work uses `create_scheduled_workflow` / `manage_scheduled_workflows`; delivery is an optional output policy.
- User-facing recurring delivery uses `create_scheduled_delivery` / `manage_scheduled_deliveries` as a convenience wrapper over Scheduled Workflow.
- Actor alias `me` resolves through explicit `ActorDeliveryPreference` bindings.
- Version line: `kind=scheduled_workflow` + `core.workflow.scheduled_workflow` is the generic scheduling protocol; timed message delivery is one `output_policy.delivery_targets` output, not the Scheduler core model. Scheduled assistant output always persists a final assistant Message; `persist_message=false` is invalid.

## 版本迭代线

- V4 当前线：Core-owned Runtime + Endpoint Routing；`/endpoint/ws`、RunEvent + Delivery fan-out、ToolRouter + ExecutionTarget、Scheduler-owned `system.heartbeat`、SKILL-first workflows；运行态模式收敛为 `general` / `automation` / `danxi`，Procedure 与 V3 Client 兼容路径下线。
- V4 调度线：`App.scheduler_processor()` 是唯一系统级调度入口；Heart 只执行 Scheduler 调起的单次 `system.heartbeat`，不再拥有重复调度/心跳时钟。真实验收脚本可用 `--desktop-tool-endpoint` 验证本地 Desktop Provider 工具链路。
- V4 Endpoint 线：Gateway 必须在 Uvicorn ready 后才允许外部 Provider 自连；Feishu / WeChat Provider 是独立 Endpoint Provider 进程，Core 不再硬编码启动或监督外部渠道。
