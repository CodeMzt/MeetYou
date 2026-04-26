# MeetYou

MeetYou 是一个以 LLM 为核心的个人智能体系统。当前架构已经收束为：

```text
Electron UI -> desktop_client backend ----\
CIL / HTTP / Web clients -----------------> Core Service -> memory / tools / MCP / Heart
edge_client runtimes ---------------------/        |
                                                   v
                                           workspaces / operations / approvals
```

核心原则：

- `Core Service` 是唯一编排中心，负责会话、记忆、权限、持久化、Gateway、operation、approval 与 tool 调度。
- 周围统一都是 `Client`，包括桌面端、边缘节点、CIL、WebSocket 会话和未来的其他入口。
- `tool` 是一等概念。Core 负责编排调用；Client 只作为身份、workspace、权限、连接和 directed tool 目标边界。
- 本地文件、Shell、本地 MCP、workspace local、短回复等本地执行能力都按 directed tool 处理。
- 不再保留正式 `/agent/ws` 运行时兼容；正式实时入口统一为 `GET /client/ws`。

当前生效的设计与计划文档在 `docs/v3/`；历史 V2 资料在 `docs/archive/v2/`。

## 架构边界

### Core Service

Core 是服务端主链：

- FastAPI HTTP / WebSocket Gateway
- thread / message / session runtime
- memory、tools、MCP、Heart
- workspace、procedure、operation、approval
- PostgreSQL 持久化与 Alembic migration
- Client tool 调度与权限判断

生产入口：

```bash
python -m service_runtime
```

开发入口：

```bash
python main.py service
```

### Desktop Client

`desktop_client/` 是桌面本地后端，与 Electron UI 一起构成统一桌面端：

- 承载 UI 使用的本地 `/desktop/*` HTTP / WS API
- 通过 `GET /client/ws` 连接 Core
- 声明 `available_tools` 与 `executable_tools`
- 执行本地文件、Shell、本地 MCP、workspace local 等 directed tools
- 由本地配置限制 `read_roots`、`trusted_write_roots`、`cmd_policy_path`、`mcp_servers_path`

生产入口：

```bash
python -m desktop_client
```

开发入口：

```bash
python main.py desktop-client
```

### Edge Client

`edge_client/` 是按 workspace 接入的边缘运行时：

- 通过 `GET /client/ws` 接入 Core
- 以 `workspace_ids`、`client_type`、`transport_profile`、tool 声明描述边缘能力
- 执行被 Core 调度到该 Client 的 directed tools

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
GET /client/ws
```

协议 schema：

```text
meetyou.client.ws.v1
```

核心帧：

- `client.hello`
- `client.tools.snapshot`
- `client.ready`
- `client.heartbeat`
- `tool.call.request`
- `tool.call.result`
- `tool.call.error`

同一 `client_id` 可以有多条 `/client/ws` 连接。每条连接可以分别声明：

- 订阅
- 当前会话上下文
- `available_tools`
- `executable_tools`
- host / transport metadata

## Tool 模型

工具分为两类：

- 无向 tools：不需要 `target_client_id`，例如 web/search、memory、skill、summarize。
- directed tools：需要解析 `target_client_id`，例如 `file.*`、`shell.*`、`workspace.*`、`short_reply`。

Client 有两张过滤清单：

- `available_tools`：该 Client 作为调用起点时允许调用的 tool key。
- `executable_tools`：该 Client 作为目标时可承接的 directed tool key。

默认目标策略：

- `short_reply` / endpoint notice：默认 `self`。
- `file.*`、`shell.*`、`workspace.*`：默认 workspace 内可执行该 tool 的 desktop Client，优先 source/self，再按 workspace 偏好排序。
- 目标不可用时直接失败为 `target_client_unavailable`，不自动 fallback。

Operation 公共字段：

- `target_client_id`
- `tool_key`
- `tool_id`
- `execution_target`: `core_only`、`specific_client`、`workspace_any_client`、`prefer_client_fallback_core`

Workspace / procedure governance 公共字段：

- `preferred_target_client_ids`
- `preferred_target_client_types`
- `tool_target_routing_policy`

## 目录结构

```text
core/                 Core 编排、会话、状态、模式路由、应用生命周期
gateway/              FastAPI HTTP / WebSocket Gateway
service_runtime/      Core 生产运行入口
client_tool_sdk/      Client tool 协议 SDK
desktop_client/       桌面本地后端与 directed tool runtime
edge_client/          边缘 Client runtime
meetyou-ui/           Electron + React 桌面端
tools/                Core tool 集合
adapters/             LLM 与外部服务适配器
sensors/              输入/输出适配层与系统感知
platform_layer/       Core 宿主机感知抽象
prompt/               系统、模式与技能提示词
docs/                 文档入口；当前真源在 docs/v3/
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
MEETYOU_CLIENT_ID=desktop-main
MEETYOU_CLIENT_DISPLAY_NAME=Desktop Client
MEETYOU_CLIENT_WORKSPACES=desktop-main
MEETYOU_CREDENTIAL_SECRET=
```

说明：

- `MEETYOU_GATEWAY_ACCESS_TOKEN` 用于 Gateway HTTP / WebSocket 鉴权。
- `MEETYOU_CLIENT_ACCESS_TOKEN` 是 Client 访问 Core 的统一访问令牌。
- 不要新增或恢复 `MEETYOU_AGENT_*`。
- `user/config.json` 是必需文件；密钥放 `.env`。
- `user/core_mcp_servers.json` 只给 Core 侧安全 MCP。
- `user/mcp_servers.json` 只给 Desktop Client 本地 MCP。

## 启动

开发态：

```powershell
python main.py service
python main.py cil
python main.py desktop-client
python main.py edge-client
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
```

桌面主链默认顺序：

```text
service -> UI -> desktop backend(由 UI 托管) -> desktop session -> /client/ws runtime
```

## 验证

后端最小验证：

```powershell
python -m compileall core gateway tools desktop_client edge_client client_tool_sdk service_runtime main.py client_tool_protocol.py
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
- 发布涉及数据库 schema 时，先升级 Core，再升级 Desktop Client / Edge Client / UI。
- 只有保留对应 PostgreSQL 快照时，才可以宣称 Core 可安全回滚。
- 当前默认只承诺 Core / Client 同版与相邻一代发布的兼容窗口。

## 参考文档

- `docs/v3/design/architecture-baseline.md`
- `docs/v3/design/client-tools.md`
- `docs/v3/design/deployment-and-platform.md`
- `docs/v3/operations/core-deployment.md`
- `docs/v3/design/desktop-unified-client.md`
- `docs/v3/operations/desktop-client-acceptance.md`
- `user/README.md`
