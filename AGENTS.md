# AGENTS

## 运行形态

- 仓库分为两部分：根目录的 Python Core Service / agent runtime，以及 `meetyou-ui/` 下的 Electron + React 前端。
- 开发态统一入口仍是 `python main.py service`、`python main.py cil`、`python main.py desktop-agent`、`python main.py edge-agent`；`python main.py` / `python main.py launcher` 会打开 launcher。
- 生产可分离入口改为 `python -m service_runtime`、`python -m desktop_agent`、`python -m edge_agent`；对应依赖清单分别是 `requirements-core.txt`、`requirements-desktop-agent.txt`、`requirements-edge-agent.txt`。
- `Core Service`、`desktop-agent`、`edge-agent` 是三个独立发布单元；发布文档、升级说明、部署脚本不要再假设三者必须同包同批次上线。
- 不要再使用旧的 `python main.py gateway` 或 launcher `start gateway`；该入口已移除。
- Launcher 命令是 `start service`、`start cil`、`start ui`、`status`、`exit`。
- OpenCode repo-local 配置放在 `.opencode/`；新会话优先用 `/repo-scan` 建立上下文，改完后优先用 `/verify-backend`、`/verify-frontend`、`/verify-fullstack`，不要临时猜验证流程。

## 目录边界

- 运行主链先看 `main.py`、`service_runtime/service.py`、`core/app.py`、`core/app_lifecycle.py`；`core_service/` 目录存在，但当前启动主链不从这里进入。
- `core/app.py` 仍是后端主装配点，但运行生命周期与客户端线程桥接已分别下沉到 `core/app_lifecycle.py`、`core/client_thread_bridge.py`；不要再把新的运行时职责继续堆回单一 `App` 类。
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
- 公开 mode 现为 `general`、`research`、`documents`、`study`、`automation`、`danxi`；`auto`、`normal`、`office` 只保留内部兼容映射，不再作为公开产品枚举扩散。

## 配置与状态

- `user/config.json` 不是可选文件；`ConfigManager` 启动时缺失会直接报错。密钥放 `.env`。
- `user/` 是本地运行态目录；Git 只保留 `*.example.json` 模板和 `user/README.md`。
- `user/core_mcp_servers.json` 只给 Core 侧安全 MCP；`user/mcp_servers.json` 只给 Desktop Agent 本地 MCP。缺少前者不代表后者缺失。
- `desktop-agent` 默认读取 `user/desktop_agent.json`；本地能力边界主要看 `read_roots`、`trusted_write_roots`、`cmd_policy_path`、`mcp_servers_path`。
- `edge-agent` 默认读取 `user/edge_agent.json`；边缘能力边界主要看 `workspace_ids`、`agent_type`、`transport_profile`。
- 正式持久化已经切到 PostgreSQL；`bootstrap_core_domain()` 会在 service 启动时跑 Alembic migration。不要再假设 `user/*.json` 是唯一真相源。
- Danxi 默认优先直连 `forum.fduhole.com` / `auth.fduhole.com`；校外网络下可按 `docs/MeetYou项目工具接入.pdf` 通过 WebVPN URL 代理访问。当前前端已提供 Electron 内嵌 WebVPN 登录窗，采用“用户手动登录、程序自动提取 cookie”模式；不要在未确认页面参数的情况下硬写高风险 WebVPN 表单自动提交。
- Danxi 二阶段已经补齐会话安全持久化：Danxi JWT / refresh token / WebVPN cookie 会以加密封装形式写入状态后端，并在启动后尝试自动恢复；会话失效、撤销或损坏时应自动清理并提示重新登录。
- Danxi 登录与 WebVPN cookie 更新只接受 `encrypted_credentials` 加密传输；共享密钥优先取 `MEETYOU_CREDENTIAL_SECRET`，缺失时才回退到 `MEETYOU_GATEWAY_ACCESS_TOKEN` 或 `MEETYOU_AGENT_ACCESS_TOKEN`。不要新增或恢复明文凭证跨边界路径。

## 任务边界

- Backend-only 任务通常只应落在 `core/`、`service_runtime/`、`gateway/`、`adapters/`、`tools/`、`sensors/`、`cil/`。
- Frontend-only 任务通常只应落在 `meetyou-ui/`；不要为了配合 UI 猜测而改后端正式路径或协议名。
- Agent-only 任务落在 `desktop_agent/` 或 `edge_agent/`；不要通过改 Core 绕过 agent dispatch。
- 如果改动涉及 gateway 路由、WebSocket payload、配置加载、附件流、`core/db/*`、`desktop_agent/runtime.py`、`edge_agent/runtime.py` 或 `meetyou-ui/src/hooks/useMeetYou.ts`，按 cross-surface 任务处理。
- Danxi 相关任务通常落在 `tools/danxi_tools.py`、`core/public_contract.py`、`core/assistant_modes.py`、`core/credential_transport.py`、`gateway/models.py`、`gateway/routes/client.py`、`gateway/routes/operator.py`、`meetyou-ui/src/`、`meetyou-ui/electron/` 与 `docs/`；不要把 Danxi 论坛访问塞进 Desktop Agent 或临时 MCP。
- Danxi 二阶段 UI 任务优先落在 `meetyou-ui/src/DanxiWindow.tsx`、`meetyou-ui/src/DanxiWindow.module.css`、`meetyou-ui/src/clientApi.ts` 与 `meetyou-ui/electron/main.ts`；不要为了图省事把认证窗口逻辑、cookie 抓取或凭证加密分散到无关页面/组件。

## 高风险区域

- `core/app.py`、`core/app_lifecycle.py`、`core/client_thread_bridge.py`：后端主装配与运行桥接核心区，改动容易影响 service、gateway、memory、tools、session runtime。
- `gateway/routes/client.py`、`gateway/routes/agent.py`：客户端与 agent 协议面，最容易产生前后端不兼容。
- `tools/danxi_tools.py`：论坛直连 / WebVPN 代理 / JWT 会话逻辑集中区，误改容易导致登录态、论坛写操作、自动恢复或校外访问链路失效。
- `core/credential_transport.py`：Danxi/WebVPN 凭证加密封装、purpose 和密钥派生逻辑集中区，误改容易导致前后端无法互通或把密文/明文边界打乱。
- `meetyou-ui/electron/main.ts`：Danxi WebVPN 登录窗、cookie 提取与 Electron 侧加密入口集中区，误改容易泄露凭证、破坏自动登录或引入平台行为差异。
- `core/db/*`、`alembic/versions/*`：正式持久化与迁移面，误改会破坏启动和数据。
- `desktop_agent/runtime.py`、`edge_agent/runtime.py`：本地/边缘执行链路，改动常带权限与协议副作用。
- `meetyou-ui/src/hooks/useMeetYou.ts`：前端默认地址、WebSocket 与 API 主链入口。

## 允许与禁止

- 允许：小步修复、局部重构、补对应测试、在接口或启动方式变更时同步更新文档。
- 禁止：重新引入 `python main.py gateway`、把 `/ws` 当成正式聊天路径、把本地终端能力塞回 Core。
- 非明确需求不要修改真实运行态文件：`.env`、`user/*.json`、`user/*.db`、`logs/`、`.venv/`、`.git/`。
- 非明确依赖升级任务不要修改锁文件；本仓库默认只会碰 `meetyou-ui/package-lock.json`。
- 非明确 schema 任务不要新建或重写 Alembic migration。
- Danxi 联调或验收禁止做高并发测试、批量删改、管理员接口调用或其他高风险论坛操作；只允许低频、顺序化、符合正常用户行为的验证。
- Danxi 相关改动禁止在日志、错误对象、调试输出、测试快照或文档示例中暴露明文 email、password、cookie、token；需要跨边界传输时优先使用 `encrypted_credentials`。

## 常用命令

- 开发全量安装：`python -m venv .venv`，`.venv\Scripts\activate`，`pip install -r requirements.txt`
- Core 生产安装：`pip install -r requirements-core.txt`
- Desktop Agent 生产安装：`pip install -r requirements-desktop-agent.txt`
- Edge Agent 生产安装：`pip install -r requirements-edge-agent.txt`
- 后端启动：`python main.py service` 或 `python -m service_runtime`
- Launcher：`python main.py`
- CIL：`python main.py cil`
- Desktop Agent：`python main.py desktop-agent` 或 `python -m desktop_agent`
- Edge Agent：`python main.py edge-agent` 或 `python -m edge_agent`
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
- 如果改动涉及发布单元、升级顺序、兼容窗口、灰度或回滚口径，文档只能承诺已被代码或测试覆盖的范围；当前默认只承诺 `Core/Agent` 同版与相邻一代发布的兼容窗口。
- 发布/回滚文档必须明确 `Core Service` 持有数据库 migration 与协议协商主导权；只有在保留对应 PostgreSQL 快照时才允许宣称可安全回滚 Core。
- 如果变更会影响行为，但仓库里没有覆盖测试，说明里要明确测试缺口。
- Danxi 二阶段相关改动完成前，至少确认四件事：1）独立窗口布局未退化；2）自动恢复/失效清理逻辑仍成立；3）凭证仍按加密口径跨边界；4）验收记录明确本次走直连还是 WebVPN。

## 验证顺序

- 后端改动：先跑最小相关 `unittest` 模块；只有跨目录或跨子系统时再跑 `discover`。
- 前端改动：先 `npm run typecheck`，再 `npm run test`；只有碰 Electron/Vite/build 链路时再跑 `npm run build`。当有实质功能需要测试，需要进行真实的功能测试，不能仅停留在编译测试。
- Cross-surface 改动：先 backend，再 frontend；涉及 API/协议或 service 主链时，再补 `python smoke_check.py`。
- 文档改动如果直接涉及 Agent 协议兼容、发布/回滚流程或部署主链，至少跑 `tests/test_agent_release_compatibility.py`；若同时改了 service 主链口径，再补 `python smoke_check.py`。
- 桌面主链改动：在需要真实链路时跑 `scripts\manual-acceptance.cmd check`；要完整拉起 service + desktop-agent + UI 时用 `scripts\manual-acceptance.cmd start`。
- 仓库里没有已配置好的 lint、pre-commit 或 CI workflow，不要在说明里假设这些检查存在。
- Danxi 改动：先跑 `tests/test_danxi_tools.py`、`tests/test_assistant_modes.py`、`tests/test_gateway_surface_routes.py` 最小相关后端用例，再跑前端 `npm run typecheck` 和 `npm run test`；若做真链路，只执行少量顺序化浏览/搜索/发帖或回帖验证，并记录是否走 WebVPN。
- Danxi 二阶段真链路验收至少覆盖：Danxi 窗口紧凑布局、自动恢复登录或失效清理、用户信息展示、回复/编辑回复/删除回复、AI 摘要，以及 WebVPN 登录窗提取 cookie 是否成功；不要只停留在编译通过。

## 平台注意事项

- 项目整体偏 Windows：README、launcher、`.cmd` 脚本、PowerShell 拉起方式、`uiautomation`、Electron 窗口行为都默认按 Windows 使用。
- `launcher.py` 会先探测 `GET /health`，确认 service 可用后再拉起 CIL 或 UI；复现桌面链路时也按 `service -> desktop-agent/UI` 顺序处理。
