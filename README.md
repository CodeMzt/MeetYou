# MeetYou

MeetYou 是一个以 LLM 为核心的个人智能体系统。当前 V4 架构是 **Core-owned Runtime + Endpoint Routing**：Core 统一拥有会话、消息、运行、调度、心跳、记忆、操作和投递；Desktop、Edge、Feishu、WeChatBot 等只作为 Endpoint Provider 接入。

```text
Electron UI -> desktop_client backend ----\
CIL / HTTP surfaces -----------------------> Core Service -> Thread / Message / Run
Edge Endpoint Providers ------------------/        |        Scheduler / Heartbeat
External Endpoint Providers --------------/        v        Memory / Operation / Delivery
                                            ToolRouter -> ExecutionTarget
```

V4 的实现真源是 [AGENTS.md](./AGENTS.md) 和 [docs/v4/](./docs/v4/)。`docs/v3/` 与 `docs/archive/` 只保留为历史参考和计划留痕。

## Architecture

### Core Service

Core 是服务端主链，负责：

- Thread / Message / Run runtime
- Scheduler / Heartbeat / Memory / Operation / Delivery
- ToolRouter / ExecutionTarget 调度
- Actor / Workspace / RunPolicy 权限判断
- PostgreSQL 持久化与 Alembic migration
- FastAPI `/runtime/*` facade 与 `GET /endpoint/ws`

入口：

```powershell
python main.py service
python -m service_runtime
```

### Endpoint Providers

Client 在 V4 中只表示 Endpoint Provider，不拥有会话、运行、调度或投递语义。

- `desktop_client/`：桌面本地后端，承载 `/desktop/*`，并通过 `/endpoint/ws` 连接 Core。
- `edge_client/`：边缘执行 Provider，按 workspace 暴露 endpoint capabilities。
- `endpoint_providers/`：Feishu、WeChatBot 等独立外部 Provider。
- Provider 内部聊天目标必须建模为 `EndpointAddress`，不能建成 Client。

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

`meetyou-ui/` 是 Electron + React 桌面 UI。Renderer 默认访问本地 desktop backend，由 desktop backend 代理到 Core 的 `/runtime/*`、`/operator/*` 或 `/developer/*` surface。

重要入口：

- `meetyou-ui/electron/main.ts`
- `meetyou-ui/src/main.tsx`
- `meetyou-ui/src/hooks/useMeetYou.ts`
- `meetyou-ui/src/windowBridge.ts`

开发启动：

```powershell
cd meetyou-ui
npm install
npm run dev
```

## Protocol Rules

- 正式实时 Provider 入口只有 `GET /endpoint/ws`。
- WebSocket schema 是 `meetyou.endpoint.ws.v4`。
- V4 HTTP facade 是 `/runtime/*`。
- `/client/ws` 已移除；如果清理期仍有拒绝路由，只能返回明确 removed 响应，不能转发或适配到 V4。
- 新运行时代码不得重新引入 `source_client_id`、`target_client_id` 或 `ClientToolDispatchService`。
- `assistant.progress_notice` 是 RunEvent / Runtime Action，不经过 ToolRouter，不创建 Operation，也不能成为最终 assistant message 内容。
- 最终 assistant reply 必须由 MessageService 持久化为 assistant Message。
- Streaming 必须走 RunEventLog + Delivery fan-out。

详细协议见 [docs/v4/meetyou-v4-design.md](./docs/v4/meetyou-v4-design.md)。

## Repository Layout

```text
core/                 Core 编排、领域服务、状态、模式、生命周期
gateway/              FastAPI HTTP / WebSocket gateway
service_runtime/      Core 生产运行入口
endpoint_tool_sdk/    Endpoint protocol / runtime SDK
desktop_client/       桌面本地后端与 endpoint execution runtime
edge_client/          Edge Endpoint Provider runtime
endpoint_providers/   Feishu / WeChatBot 等外部 Endpoint Provider
meetyou-ui/           Electron + React 桌面端
tools/                Core tool 集合
adapters/             LLM 与外部服务适配
sensors/              输入/输出适配与系统感知
platform_layer/       宿主平台抽象
prompt/               系统、模式与技能提示词
docs/                 文档；当前真源在 docs/v4/
tests/                自动化回归测试
user/                 本地配置模板与运行态数据目录
```

## Install

完整开发环境：

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cd meetyou-ui
npm install
```

生产依赖按层安装：

```powershell
pip install -r requirements-core.txt
pip install -r requirements-desktop-client.txt
pip install -r requirements-edge-client.txt
```

## Configure

`user/config.json` 不是可选文件。首次启动前复制模板，密钥放在 `.env`：

```powershell
copy user\config.example.json user\config.json
copy user\tools.example.json user\tools.json
copy user\cmd_policy.example.json user\cmd_policy.json
copy user\source_catalog.example.json user\source_catalog.json
copy user\memory_graph.example.json user\memory_graph.json
copy user\desktop_client.example.json user\desktop_client.json
copy user\edge_client.example.json user\edge_client.json
```

常用环境变量：

```dotenv
MEETYOU_DATABASE_URL=
MEETYOU_GATEWAY_ACCESS_TOKEN=
MEETYOU_CLIENT_ACCESS_TOKEN=
MEETYOU_CORE_BASE_URL=http://127.0.0.1:8000
MEETYOU_FEISHU_ENABLE=false
MEETYOU_MEETWECHAT_ENABLE=false
MEETYOU_CREDENTIAL_SECRET=
```

说明：

- `MEETYOU_CLIENT_ACCESS_TOKEN` 当前仍沿用变量名，但语义是 Endpoint Provider 访问 Core 的令牌。
- 不要新增或恢复 `MEETYOU_AGENT_*`。
- `user/core_mcp_servers.json` 只给 Core 侧安全 MCP。
- `user/mcp_servers.json` 只给 Desktop Endpoint Provider 本地 MCP。
- Danxi / WebVPN 凭据只能通过加密传输更新，不得写入日志、测试快照或文档示例。

## Start

Launcher：

```powershell
python main.py
```

开发主链：

```powershell
python main.py service
python main.py cil
python main.py desktop-client
python main.py edge-client
```

生产主链：

```powershell
python -m service_runtime
python -m desktop_client
python -m edge_client
```

桌面链路应按以下顺序验证：

```text
service -> UI -> desktop backend managed by UI -> desktop provider session -> /endpoint/ws runtime
```

Linux systemd 部署入口：

```bash
sudo bash scripts/linux/install-core-systemd.sh
sudo bash scripts/linux/install-feishu-provider-systemd.sh
sudo bash scripts/linux/install-meetwechat-provider-systemd.sh
```

## Verify

后端最小验证：

```powershell
python -m compileall core gateway tools desktop_client edge_client endpoint_tool_sdk service_runtime main.py endpoint_tool_protocol.py
python -m compileall endpoint_providers
python -m unittest tests.test_runtime_entrypoints tests.test_config_manager
```

前端基础验证：

```powershell
cd meetyou-ui
npm run typecheck
npm run test
```

前端验收不能只停在 typecheck / unit test；涉及 UI 行为或布局时必须真实启动浏览器或 Electron，并保存截图验收结果。截图应放在已忽略的本地 artifact 目录，并在验收记录中写明路径。

跨面或主链验证：

```powershell
scripts\manual-acceptance.cmd check
scripts\manual-acceptance.cmd start
```

V4 发布级验证还需要覆盖 Python tests、frontend typecheck/build/test、migration、endpoint protocol、scheduler、tool router、delivery、本地 Core + Desktop + UI、远端 Core health/version、Feishu/WeChatBot 真实消息和人工确认。结果写入 [docs/v4/test-report.md](./docs/v4/test-report.md)。

## Publish

- `main` 是发布分支。完成的任务必须提交、推送并合并回 `main`。
- 发布前确认工作树不包含缓存、日志、构建产物、Electron release、打包 runtime-template、真实 `.env` 或 `user/*.json` 运行态文件。
- Core Service 拥有数据库 migration 和协议协商主导权。
- 涉及 schema 的发布先升级 Core，再升级 Desktop / Edge / 外部 Provider / UI。
- 只有保留对应 PostgreSQL 快照时，才可以声明 Core 可安全回滚。
- 外部 Provider 失败不能阻塞 Core 部署；Provider 可以在 Core 就绪后自连 `/endpoint/ws`。

## Documentation

- [AGENTS.md](./AGENTS.md)：仓库规则、边界、验证顺序、发布要求。
- [docs/v4/meetyou-v4-design.md](./docs/v4/meetyou-v4-design.md)：V4 架构设计。
- [docs/v4/meetyou-v4-plan.md](./docs/v4/meetyou-v4-plan.md)：V4 实施计划。
- [docs/v4/meetyou-v4-scheduled-workflows.md](./docs/v4/meetyou-v4-scheduled-workflows.md)：Scheduled Workflow。
- [docs/v4/meetyou-v4-endpoint-address-scheduled-delivery.md](./docs/v4/meetyou-v4-endpoint-address-scheduled-delivery.md)：EndpointAddress 与计划投递。
- [docs/v4/test-report.md](./docs/v4/test-report.md)：V4 验证报告。
- [user/README.md](./user/README.md)：本地配置目录说明。
