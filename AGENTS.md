# AGENTS

## 运行形态
- 仓库分为两部分：根目录的 Python Core Service / agent runtime，以及 `meetyou-ui/` 下的 Electron + React 前端。
- 当前正式入口是 `python main.py service`、`python main.py cil`、`python main.py desktop-agent`、`python main.py edge-agent`；`python main.py` / `python main.py launcher` 会打开 launcher。
- 不要再使用旧的 `python main.py gateway` 或 launcher `start gateway`；该入口已移除。
- Launcher 命令是 `start service`、`start cil`、`start ui`、`status`、`exit`。
- OpenCode repo-local 配置放在 `.opencode/`；新会话优先用 `/repo-scan` 建立上下文，改完后优先用 `/verify-backend`、`/verify-frontend`、`/verify-fullstack`，不要临时猜验证流程。

## 目录边界
- 运行主链先看 `main.py`、`service_runtime/service.py`、`core/app.py`；`core_service/` 目录存在，但当前启动主链不从这里进入。
- `core/app.py` 是后端主装配点；这里会组装 EventBus、Brain、Heart、Memory、Tools、Session runtime 和 `FastAPIGateway`。
- 前端入口分两层：`meetyou-ui/electron/main.ts` 是 Electron main process，`meetyou-ui/src/main.tsx` 是 renderer 入口。
- `desktop_agent/` 是客户端本地后端实现，负责本地文件、Shell、本地 MCP 和桌面能力；`edge_agent/` 是按 workspace 接入的边缘 Agent 运行时。
- `desktop_agent/` 与 `edge_agent/` 当前统一通过 `WSS /agent/ws` + `meetyou.agent.v1` 接入；差异主要体现在 `agent_type` 与 `transport_profile`，不要再按旧 MQTT 方案假设 edge 主链。
- 不要把本地文件读写、Shell、本地 MCP 生命周期重新塞回 Core；这些能力当前通过 agent dispatch 委派给 Desktop Agent / Edge Agent。

## 接口与连接
- 客户端正式实时入口是 `GET /client/ws`；根路径 `GET /ws` 只返回兼容性错误，不再承载聊天流。
- Agent 正式实时入口是 `WSS /agent/ws`。
- 前端默认服务地址是 `http://127.0.0.1:8000`，定义在 `meetyou-ui/src/hooks/useMeetYou.ts`。
- Gateway 鉴权是可选的；启用后 HTTP / WebSocket 接受 `Authorization: Bearer ...` 或 `X-API-Key`。
- `desktop-agent` 与 `edge-agent` 都会优先读 `MEETYOU_AGENT_ACCESS_TOKEN`；`desktop-agent` / `edge-agent` 也支持各自的专用 env，并可回退到 `MEETYOU_GATEWAY_ACCESS_TOKEN`。

## 配置与状态
- `user/config.json` 不是可选文件；`ConfigManager` 启动时缺失会直接报错。密钥放 `.env`。
- `user/` 是本地运行态目录；Git 只保留 `*.example.json` 模板和 `user/README.md`。
- `user/core_mcp_servers.json` 只给 Core 侧安全 MCP；`user/mcp_servers.json` 只给 Desktop Agent 本地 MCP。缺少前者不代表后者缺失。
- `desktop-agent` 默认读取 `user/desktop_agent.json`；本地能力边界主要看 `read_roots`、`trusted_write_roots`、`cmd_policy_path`、`mcp_servers_path`。
- `edge-agent` 默认读取 `user/edge_agent.json`；边缘能力边界主要看 `workspace_ids`、`agent_type`、`transport_profile`。
- 正式持久化已经切到 PostgreSQL；`bootstrap_core_domain()` 会在 service 启动时跑 Alembic migration。不要再假设 `user/*.json` 是唯一真相源。

## 任务边界
- Backend-only 任务通常只应落在 `core/`、`service_runtime/`、`gateway/`、`adapters/`、`tools/`、`sensors/`、`cil/`。
- Frontend-only 任务通常只应落在 `meetyou-ui/`；不要为了配合 UI 猜测而改后端正式路径或协议名。
- Agent-only 任务落在 `desktop_agent/` 或 `edge_agent/`；不要通过改 Core 绕过 agent dispatch。
- 如果改动涉及 gateway 路由、WebSocket payload、配置加载、附件流、`core/db/*`、`desktop_agent/runtime.py`、`edge_agent/runtime.py` 或 `meetyou-ui/src/hooks/useMeetYou.ts`，按 cross-surface 任务处理。

## 高风险区域
- `core/app.py`：后端主装配点，改动容易影响 service、gateway、memory、tools、session runtime。
- `gateway/routes/client.py`、`gateway/routes/agent.py`：客户端与 agent 协议面，最容易产生前后端不兼容。
- `core/db/*`、`alembic/versions/*`：正式持久化与迁移面，误改会破坏启动和数据。
- `desktop_agent/runtime.py`、`edge_agent/runtime.py`：本地/边缘执行链路，改动常带权限与协议副作用。
- `meetyou-ui/src/hooks/useMeetYou.ts`：前端默认地址、WebSocket 与 API 主链入口。

## 允许与禁止
- 允许：小步修复、局部重构、补对应测试、在接口或启动方式变更时同步更新文档。
- 禁止：重新引入 `python main.py gateway`、把 `/ws` 当成正式聊天路径、把本地终端能力塞回 Core。
- 非明确需求不要修改真实运行态文件：`.env`、`user/*.json`、`user/*.db`、`logs/`、`.venv/`、`.git/`。
- 非明确依赖升级任务不要修改锁文件；本仓库默认只会碰 `meetyou-ui/package-lock.json`。
- 非明确 schema 任务不要新建或重写 Alembic migration。

## 常用命令
- 后端安装：`python -m venv .venv`，`.venv\Scripts\activate`，`pip install -r requirements.txt`
- 后端启动：`python main.py service`
- Launcher：`python main.py`
- CIL：`python main.py cil`
- Desktop Agent：`python main.py desktop-agent`
- Edge Agent：`python main.py edge-agent`
- 前端开发：在 `meetyou-ui/` 下执行 `npm install`、`npm run dev`（会拉起 Electron 开发窗口）
- 前端校验：在 `meetyou-ui/` 下执行 `npm run typecheck`、`npm run test`
- 前端构建：在 `meetyou-ui/` 下执行 `npm run build`（实际脚本是 `tsc && vite build && electron-builder`）
- 后端单测按模块跑：`.venv\Scripts\python.exe -m unittest tests.test_service_runtime`
- 后端全量测试：`.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`
- 冒烟检查：`python smoke_check.py`
- 人工拉起/检查主链：`scripts\manual-acceptance.cmd start`、`scripts\manual-acceptance.cmd check`

## 完成边界
- 任务完成前至少确认：改动落在正确边界内，没有重新引入旧入口名或旧路径契约。
- 改动命中协议、配置、持久化或跨端交互时，必须补最小相关验证，而不是只做静态阅读。
- 接口、启动方式、配置项或验证流程有变化时，同步更新 `AGENTS.md`、`README.md` 或相关 docs。
- 如果变更会影响行为，但仓库里没有覆盖测试，说明里要明确测试缺口。

## 验证顺序
- 后端改动：先跑最小相关 `unittest` 模块；只有跨目录或跨子系统时再跑 `discover`。
- 前端改动：先 `npm run typecheck`，再 `npm run test`；只有碰 Electron/Vite/build 链路时再跑 `npm run build`。
- Cross-surface 改动：先 backend，再 frontend；涉及 API/协议或 service 主链时，再补 `python smoke_check.py`。
- 桌面主链改动：在需要真实链路时跑 `scripts\manual-acceptance.cmd check`；要完整拉起 service + desktop-agent + UI 时用 `scripts\manual-acceptance.cmd start`。
- 仓库里没有已配置好的 lint、pre-commit 或 CI workflow，不要在说明里假设这些检查存在。

## 平台注意事项
- 项目整体偏 Windows：README、launcher、`.cmd` 脚本、PowerShell 拉起方式、`uiautomation`、Electron 窗口行为都默认按 Windows 使用。
- `launcher.py` 会先探测 `GET /health`，确认 service 可用后再拉起 CIL 或 UI；复现桌面链路时也按 `service -> desktop-agent/UI` 顺序处理。
