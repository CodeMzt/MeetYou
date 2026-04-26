# AGENTS

## 运行形态

- 当前架构收束为 `Core + Clients + Tools`：Core 负责编排、记忆、会话、权限、持久化与 tool 调度；周围统一都是 Client。
- Agent 不再作为 endpoint/product 概念存在；本地文件、Shell、本地 MCP、workspace local、短回复等本地能力都按 tool 处理。
- 工具分为无向 tools 与 directed tools。无向 tools 不需要目标 Client；directed tools 需要解析 `target_client_id`，并检查目标 Client 的 `executable_tools`。
- 仓库仍分为 Python runtime 与 `meetyou-ui/` 前端两层；桌面交付形态是 Electron UI + `desktop_client` backend 一体化产品。
- 开发态入口：`python main.py service`、`python main.py cil`、`python main.py desktop-client`、`python main.py edge-client`；`python main.py` / `python main.py launcher` 打开 launcher。
- 生产入口：`python -m service_runtime`、`python -m desktop_client`、`python -m edge_client`。
- 依赖清单：`requirements-core.txt`、`requirements-desktop-client.txt`、`requirements-edge-client.txt`。
- Launcher 命令：`start service`、`start cil`、`start ui`、`status`、`exit`。
- 当前生效设计与计划文档放在 `docs/v3/`；V2 历史资料归档在 `docs/archive/v2/`。新迭代默认更新 `docs/v3/`。
- OpenCode repo-local 配置放在 `.opencode/`；新会话优先用 `/repo-scan` 建立上下文，改完后优先用 `/verify-backend`、`/verify-frontend`、`/verify-fullstack`。

## 目录边界

- 运行主链先看 `main.py`、`service_runtime/service.py`、`core/app.py`、`core/app_lifecycle.py`。
- `core/app.py` 是后端主装配点；运行生命周期与客户端线程桥接分别在 `core/app_lifecycle.py`、`core/client_thread_bridge.py`。
- 前端入口：`meetyou-ui/electron/main.ts` 是 Electron main process，`meetyou-ui/src/main.tsx` 是 renderer 入口。
- `desktop_client/` 是桌面本地后端，负责本地文件、Shell、本地 MCP、桌面能力，以及 UI 使用的 `/desktop/*` 本地 API；本地 API 主链看 `desktop_client/desktop_api.py`，访问 Core 的 HTTP 主链看 `desktop_client/core_client.py`。
- `edge_client/` 是按 workspace 接入的边缘 Client 运行时。
- `client_tool_sdk/` 是 Client tool 协议 SDK；根兼容导出在 `client_tool_protocol.py`。
- `desktop_client/` 与 `edge_client/` 统一通过 `GET /client/ws` + `meetyou.client.ws.v1` 接入；差异主要体现在 `client_type`、`transport_profile`、`workspace_ids` 与 tool 声明。
- 不要把本地文件读写、Shell、本地 MCP 生命周期塞回 Core；这些能力通过 directed tool 委派给可执行的 Client。

## 接口与协议

- 唯一正式实时入口是 `GET /client/ws`。
- 根路径 `GET /ws` 只保留兼容性错误，不承载正式聊天流。
- 不保留正式 `/agent/*` 运行时兼容；旧 Agent 在线态与能力快照允许清空。
- Client WebSocket 帧使用 `client.hello`、`client.tools.snapshot`、`client.ready`、`client.heartbeat`、`tool.call.request`、`tool.call.result`、`tool.call.error`。
- 同一 `client_id` 允许多条 `/client/ws` 连接；每条连接可分别声明订阅、会话上下文和可执行 tools。
- Client 有两张工具过滤清单：`available_tools` 表示作为起点允许调用的 tool key，`executable_tools` 表示作为目标可承接的 directed tool key。
- `Operation.target_client_id` / `OperationCall.target_client_id` 是 directed tool 目标字段；不要再新增 `target_agent_id`。
- `execution_target` 公开枚举为 `core_only`、`specific_client`、`workspace_any_client`、`prefer_client_fallback_core`。
- capability/provider 统一为 Client tool：具体 provider id 形如 `client.<client_id>.<tool_key>`，权限清单以抽象 `tool_key` 为准。
- 桌面前端默认服务地址是本地 desktop backend `http://127.0.0.1:38951`，定义在 `meetyou-ui/src/windowBridge.ts`。
- Gateway 鉴权可选；启用后 HTTP / WebSocket 接受 `Authorization: Bearer ...` 或 `X-API-Key`。

## 配置与状态

- `user/config.json` 不是可选文件；`ConfigManager` 启动时缺失会直接报错。密钥放 `.env`。
- `user/` 是本地运行态目录；Git 只保留 `*.example.json` 模板和 `user/README.md`。
- `user/core_mcp_servers.json` 只给 Core 侧安全 MCP；`user/mcp_servers.json` 只给 Desktop Client 本地 MCP。
- Desktop Client 默认读取 `user/desktop_client.json`；本地能力边界主要看 `read_roots`、`trusted_write_roots`、`cmd_policy_path`、`mcp_servers_path`，桌面一体化边界还要看 `local_bridge_*` 配置。
- Edge Client 默认读取 `user/edge_client.json`；边缘边界主要看 `workspace_ids`、`client_type`、`transport_profile`、`available_tools`、`executable_tools`。
- Core / Client 统一使用 `MEETYOU_CLIENT_ACCESS_TOKEN` 或 Gateway/Core 访问令牌；不要新增或恢复 `MEETYOU_AGENT_*`。
- 正式持久化已经切到 PostgreSQL；`bootstrap_core_domain()` 会在 service 启动时跑 Alembic migration。不要假设 `user/*.json` 是唯一真相源。
- Danxi 登录与 WebVPN cookie 更新只接受 `encrypted_credentials` 加密传输；共享密钥优先取 `MEETYOU_CREDENTIAL_SECRET`，缺失时才回退到 `MEETYOU_GATEWAY_ACCESS_TOKEN` 或 `MEETYOU_CLIENT_ACCESS_TOKEN`。

## 任务边界

- Backend-only 任务通常落在 `core/`、`service_runtime/`、`gateway/`、`adapters/`、`tools/`、`sensors/`、`cil/`。
- Frontend-only 任务通常落在 `meetyou-ui/`；不要为了配合 UI 猜测后端正式路径或协议名。
- Client runtime 任务落在 `desktop_client/` 或 `edge_client/`；不要通过改 Core 绕过 directed tool dispatch。
- 如果改动涉及 gateway 路由、WebSocket payload、配置加载、附件流、`core/db/*`、`desktop_client/runtime.py`、`edge_client/runtime.py` 或 `meetyou-ui/src/hooks/useMeetYou.ts`，按 cross-surface 任务处理。
- Danxi 相关任务通常落在 `tools/danxi_tools.py`、`core/public_contract.py`、`core/assistant_modes.py`、`core/credential_transport.py`、`gateway/models.py`、`gateway/routes/client.py`、`gateway/routes/operator.py`、`meetyou-ui/src/`、`meetyou-ui/electron/` 与 `docs/`；不要把 Danxi 论坛访问塞进 Desktop Client 或临时 MCP。

## 高风险区域

- `core/app.py`、`core/app_lifecycle.py`、`core/client_thread_bridge.py`：后端主装配与运行桥接核心区。
- `gateway/routes/client.py`、`gateway/client_ws.py`：Client 协议面与实时链路。
- `core/services/client_tool_dispatch_service.py`：directed tool 调度、权限、目标解析与结果回传。
- `core/db/*`、`alembic/versions/*`：正式持久化与迁移面。
- `desktop_client/runtime.py`、`edge_client/runtime.py`：本地/边缘执行链路，改动常带权限与协议副作用。
- `meetyou-ui/src/hooks/useMeetYou.ts`：前端默认地址、WebSocket 与 API 主链入口。
- `tools/danxi_tools.py`、`core/credential_transport.py`、`meetyou-ui/electron/main.ts`：Danxi/WebVPN 登录态与凭证加密边界。

## 允许与禁止

- 允许：小步修复、局部重构、补对应测试、在接口或启动方式变更时同步更新文档。
- 禁止：重新引入 `python main.py gateway`、把 `/ws` 当成正式聊天路径、恢复正式 `/agent/ws`、把本地终端能力塞回 Core。
- 非明确需求不要修改真实运行态文件：`.env`、`user/*.json`、`user/*.db`、`logs/`、`.venv/`、`.git/`。
- 非明确依赖升级任务不要修改锁文件；本仓库默认只会碰 `meetyou-ui/package-lock.json`。
- 非明确 schema 任务不要新建或重写 Alembic migration。
- Danxi 改动禁止在日志、错误对象、调试输出、测试快照或文档示例中暴露明文 email、password、cookie、token。

## 常用命令

- 开发全量安装：`python -m venv .venv`，`.venv\Scripts\activate`，`pip install -r requirements.txt`
- Core 生产安装：`pip install -r requirements-core.txt`
- Desktop Client 生产安装：`pip install -r requirements-desktop-client.txt`
- Edge Client 生产安装：`pip install -r requirements-edge-client.txt`
- 后端启动：`python main.py service` 或 `python -m service_runtime`
- Launcher：`python main.py`
- CIL：`python main.py cil`
- Desktop Client：`python main.py desktop-client` 或 `python -m desktop_client`
- Edge Client：`python main.py edge-client` 或 `python -m edge_client`
- 前端开发：在 `meetyou-ui/` 下执行 `npm install`、`npm run dev`
- 前端校验：在 `meetyou-ui/` 下执行 `npm run typecheck`、`npm run test`
- 前端构建：在 `meetyou-ui/` 下执行 `npm run build`
- 后端单测按模块跑：`.venv\Scripts\python.exe -m unittest tests.test_service_runtime`
- 后端全量测试：`.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`
- 人工拉起/检查主链：`scripts\manual-acceptance.cmd start`、`scripts\manual-acceptance.cmd check`

## 完成边界

- 任务完成前至少确认：改动落在正确边界内，没有重新引入旧入口名或旧路径契约。
- 改动命中协议、配置、持久化或跨端交互时，必须补最小相关验证。
- 接口、启动方式、配置项或验证流程有变化时，同步更新 `AGENTS.md`、`README.md` 或相关 docs。
- V3 迭代涉及设计、计划、部署、兼容窗口或跨端边界时，优先更新 `docs/v3/`。
- 每个 Phase 完成后要主动提交一次 commit，避免阶段性文档与代码变更长期滞留在未提交状态。
- 发布/回滚文档必须明确 Core Service 持有数据库 migration 与协议协商主导权；只有保留对应 PostgreSQL 快照时才允许宣称可安全回滚 Core。
- 如果变更会影响行为，但仓库里没有覆盖测试，说明里要明确测试缺口。

## 验证顺序

- 后端改动：先跑最小相关 `unittest` 模块；跨目录或跨子系统时再跑 `discover`。
- 前端改动：先 `npm run typecheck`，再 `npm run test`；有实质功能时补真实功能测试。
- Cross-surface 改动：先 backend，再 frontend；涉及 API/协议或 service 主链时，补 runtime/gateway 最小相关 unittest 或 `scripts\manual-acceptance.cmd check`。
- 文档改动如果直接涉及 Client tool 协议兼容、发布/回滚流程或部署主链，至少跑相关 Client tool / runtime 兼容测试。
- 桌面主链真链路验收用 `scripts\manual-acceptance.cmd check`；完整拉起 service + UI 用 `scripts\manual-acceptance.cmd start`。
- 仓库里没有已配置好的 lint、pre-commit 或 CI workflow 之外的统一检查，不要假设这些检查存在。

## 平台注意事项

- 项目整体偏 Windows：README、launcher、`.cmd` 脚本、PowerShell 拉起方式、`uiautomation`、Electron 窗口行为都默认按 Windows 使用。
- `launcher.py` 会先探测 `GET /health`，确认 service 可用后再拉起 CIL 或 UI；复现桌面链路时默认按 `service -> UI -> desktop backend(由 UI 托管) -> desktop session -> /client/ws runtime` 顺序处理。
