# MeetYou

MeetYou 是一个以 LLM 为核心的个人智能体系统，目标形态是“私人服务器本体 + 多客户端 + workspace 驱动的 Agent / 边缘节点治理”。当前最推荐的部署方式是：

- Linux 云服务器运行 Core Service
- Windows PC 运行统一桌面端（Electron UI + `desktop-agent` backend）
- 需要时在额外节点运行 `edge-agent`

这份 README 以“Linux 云服务器部署 + Core / Agent 接入”为主线，面向首轮落地和生产化部署。

当前生效中的设计文档与计划文档统一收口到 `docs/v3/`；V2 历史资料已归档到 `docs/archive/v2/`。

## 部署拓扑

```text
Desktop UI -> Desktop Backend ------> Core Service (Linux / Tencent Cloud)
Feishu Client ----------------------/        |
                                            |
                                     Memory / Tools / MCP / Heart
                                            |
                                  workspace / operation / approval
                                            |
                                    Edge Agents via /agent/ws
```

角色边界：

- `Core Service`：服务端主链，负责会话、路由、记忆、任务、工具调度、Gateway 与运行时状态
- `desktop-agent`：桌面端本地后端，承接本地文件、Shell、本地 MCP、桌面能力以及 UI 使用的 `/desktop/*` API
- `edge-agent`：运行在远端边缘节点上，按 workspace 接入并提供该节点的能力
- `meetyou-ui/`：桌面客户端前端，默认通过本地 desktop backend 与 Core 交互，不建议部署到 Linux 服务器上作为生产主链

关键原则：

- 客户端正式实时入口是 `GET /client/ws`
- Agent 正式实时入口是 `WSS /agent/ws`
- 根路径 `GET /ws` 只保留兼容性错误，不再承载正式聊天流
- 本地文件、Shell、本地 MCP 生命周期属于 Agent 边界，不要重新塞回 Core
- 桌面 UI 默认先连本地 desktop backend `http://127.0.0.1:38951`，而不是直接连 Core

## 适用平台

- Core Service：推荐 `Linux`，也可运行在 `Windows` / `macOS`
- Desktop UI / `desktop-agent`：当前体验明显偏向 `Windows`
- `edge-agent`：适合运行在 Linux 小主机、树莓派、远端工作机等节点

当前仓库仍保留一些 Windows 优先能力，例如 `uiautomation`、PowerShell launcher、`.cmd` 脚本和 Electron 的部分窗口行为；但 `requirements.txt` 中相关依赖已改为按平台条件安装，Linux 部署 Core 时不会再因 `uiautomation`、`pywin32` 被直接阻塞。

当前平台语义再补充两点：

- `platform_layer` 里的 UI 焦点/控件感知属于 Windows 专属能力；Linux / macOS 下显式禁用，不提供替代实现，调用会分别返回 `ui_automation_not_implemented_on_linux` / `ui_automation_not_implemented_on_macos`
- `desktop-agent` 当前暴露的文件读写、Shell 执行、workspace 分析能力仍按跨平台能力处理；也就是说 Linux / macOS 可以继续承接这些 capability，但不应承诺 Windows 那套 UI Automation 级别的桌面感知

## 环境要求

Linux 云服务器至少需要：

- Python `3.10+`
- PostgreSQL `14+` 或兼容版本
- Node.js `18+` 仅在你要构建桌面端或运行某些 Node MCP 时需要
- 可访问的大模型服务与对应 API Key

推荐的腾讯云服务器基础：

- `2C4G` 起步
- Ubuntu `22.04 LTS` 或同等级发行版
- 独立 PostgreSQL 实例或同机安装 PostgreSQL
- 安全组仅开放必须端口，例如 `80`、`443`、必要时内网数据库端口

## 目录结构

```text
core/            核心编排、会话、状态、模式路由、应用生命周期
gateway/         FastAPI HTTP / WebSocket 网关
cil/             基于 gateway 的终端客户端
adapters/        大模型与外部服务适配器
sensors/         输入/输出适配层与系统感知
tools/           工具集合，含 memory、mcp、documents、web_search 等
platform_layer/  Core 运行宿主机感知抽象，不承载终端 shell / 文件能力
prompt/          系统提示词、模式提示词、技能提示词
desktop_agent/   PC 客户端本地后端
edge_agent/      边缘 Agent 运行时
meetyou-ui/      Electron + React 桌面端
docs/            文档入口；当前真源在 docs/v3/，V2 归档在 docs/archive/v2/
tests/           自动化回归测试
user/            本地配置模板与运行态数据目录
```

## Linux 服务器部署

当前仓库为 Core 提供两条官方部署路径：

- Linux 主机 + `venv` / `systemd`
- `Dockerfile` + `deploy/docker/compose.core-postgres.yml`

更完整的 Phase 1 部署说明见 `docs/v3/operations/core-deployment.md`。

### 0. 容器化快速启动（Core + PostgreSQL）

这里的 PostgreSQL 是可选的部署进程，不是第二套数据模型。如果你的 Linux 服务器已经有 PostgreSQL，可以在 `deploy/docker/compose.env` 中把 `MEETYOU_DATABASE_URL` 指向现有数据库，再按需调整 Compose 服务。

```bash
python scripts/prepare_core_runtime.py --profile docker --output-root deploy/docker/runtime
```

这一步会：

- 创建 `deploy/docker/compose.env`
- 在 `deploy/docker/runtime/user/` 下创建独立的 Docker 运行文件
- 在 `deploy/docker/runtime/logs/` 下创建独立日志目录
- 不修改你现有的本机 `user/` 运行态

然后确认：

1. `deploy/docker/compose.env` 中的 `MEETYOU_DATABASE_URL` 与 `POSTGRES_*` 保持一致
2. 根目录 `.env` 中保留你现有的 API Key / Gateway / Agent 密钥

启动前可先自检：

```bash
python scripts/check_core_runtime.py --profile docker --runtime-root deploy/docker/runtime
```

启动命令：

```bash
docker compose --env-file deploy/docker/compose.env -f deploy/docker/compose.core-postgres.yml up -d --build
curl http://127.0.0.1:8000/health
```

补充：

- Docker Core 会先继承根目录 `.env` 的现有密钥，再叠加 `deploy/docker/compose.env` 与 `deploy/docker/runtime/core.env`
- PostgreSQL 会映射到宿主机 `127.0.0.1:55432`
- Core 会使用 `deploy/docker/runtime/user/`，不会碰你当前本机 `user/`
- Windows 下可直接使用一键脚本：`scripts\docker-core-acceptance.cmd prepare|check|start|logs`

如果你更偏向传统 Linux 宿主机部署，再继续看下面的 `venv` / `systemd` 路径。

### 1. 克隆仓库并创建虚拟环境

```bash
git clone <your-repo-url>
cd MeetYou
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-core.txt
```

说明：

- Windows 下激活命令是 `.venv\Scripts\activate`
- 开发态全量安装仍可使用 `pip install -r requirements.txt`
- 只部署 Core 时优先使用 `requirements-core.txt`
- 只部署 `desktop-agent` / `edge-agent` 时分别使用 `requirements-desktop-agent.txt` / `requirements-edge-agent.txt`

### 2. 初始化配置文件

最小初始化可直接执行：

```bash
python scripts/prepare_core_runtime.py --profile host
```

启动前可先自检：

```bash
python scripts/check_core_runtime.py --profile host --env-file .env
```

按需补充：

```bash
cp user/core_mcp_servers.example.json user/core_mcp_servers.json
cp user/edge_agent.example.json user/edge_agent.json
cp user/desktop_agent.example.json user/desktop_agent.json
```

说明：

- `python scripts/prepare_core_runtime.py --profile host` 会复制 `.env.example` 和最小 Core 运行模板；如果你已经有本地配置，脚本不会覆盖，除非加 `--force`
- `user/config.json` 不是可选文件，缺失时启动会直接报错
- `.env` 放敏感密钥，`user/*.json` 放非敏感业务配置
- 真实运行态文件不要提交回仓库

### 3. 配置 `user/config.json`

最小示例：

```json
{
  "api_provider": "openai",
  "api_url": "https://api.openai.com/v1/responses",
  "model": "gpt-5.4",
  "heartbeat_api_provider": "openai",
  "heartbeat_api_url": "https://api.openai.com/v1/responses",
  "heart_model": "gpt-5.4-mini",
  "embedding_api_url": "https://api.openai.com/v1/embeddings",
  "embedding_model": "text-embedding-3-small",
  "thinking_enabled": true,
  "thinking_effort": "medium",
  "tools_schema_path": "user/tools.json",
  "soul_path": "prompt/soul",
  "start_path": "prompt/start",
  "heartbeat_path": "prompt/heartbeat",
  "memory_file_path": "user/memory_graph.json",
  "source_catalog_path": "user/source_catalog.json",
  "gateway_host": "127.0.0.1",
  "gateway_port": 8000,
  "enable_feishu_bot": false
}
```

公网部署时建议至少关注这些字段：

- `gateway_host` / `gateway_port`：Gateway 监听地址和端口
- `gateway_access_token`：公网或非本地监听时必须配置
- `assistant_modes` / `mode_router`：模式与工具路由
- `object_store_backend`：附件存储后端，推荐生产环境接入对象存储
- `source_catalog_path`：研究来源目录

重要限制：

- 当 `gateway_host` 不是 `127.0.0.1`、`localhost`、`::1` 时，必须配置 `gateway_access_token`
- 这是当前代码里的安全边界，不建议为了“省事”删除

### 4. 配置 `.env`

常见变量：

```env
MEETYOU_API_KEY=
MEETYOU_HEARTBEAT_API_KEY=
MEETYOU_EMBEDDING_API_KEY=
MEETYOU_GATEWAY_ACCESS_TOKEN=
MEETYOU_AGENT_WS_ACCESS_TOKEN=
MEETYOU_AGENT_ACCESS_TOKEN=
MEETYOU_EDGE_ACCESS_TOKEN=
MEETYOU_DATABASE_URL=postgresql+psycopg://postgres:password@127.0.0.1:5432/meetyou
TAVILY_API_KEY=
NOTION_TOKEN=
MEETYOU_FEISHU_APP_ID=
MEETYOU_FEISHU_APP_SECRET=
```

说明：

- `MEETYOU_GATEWAY_ACCESS_TOKEN`：Gateway / WebSocket 访问令牌
- `MEETYOU_AGENT_WS_ACCESS_TOKEN`：`desktop-agent` 连接 `/agent/ws` 的首选令牌
- `MEETYOU_AGENT_ACCESS_TOKEN`：共享 Agent 访问令牌；`desktop-agent` 与 `edge-agent` 都可回退到它
- `MEETYOU_EDGE_ACCESS_TOKEN`：仅给 `edge-agent` 的专用覆盖令牌
- `MEETYOU_DATABASE_URL`：正式持久化数据库连接串

如果使用 Danxi / WebVPN，建议在 Core Service 所在环境额外配置：

```env
MEETYOU_CREDENTIAL_SECRET=
DANXI_MAIL=
DANXI_PASSWORD=
STUVPN_FUDAN_USER=
STUVPN_FUDAN_PASSWORD=
MEETYOU_DANXI_USE_WEBVPN=false
```

说明：

- `DANXI_MAIL` / `DANXI_PASSWORD` 用于 Core 侧 Danxi 默认会话自动登录。
- `STUVPN_FUDAN_USER` / `STUVPN_FUDAN_PASSWORD` 用于服务端在 WebVPN cookie 失效或校外网络需要代理时自动重建 WebVPN 会话。
- Danxi 前端只保留手动输入与内嵌 WebVPN 登录窗作为备用路径；跨边界凭证传输统一走 `encrypted_credentials`，密钥优先使用 `MEETYOU_CREDENTIAL_SECRET`。

### 5. 准备 PostgreSQL

当前正式持久化已经切到 PostgreSQL。服务启动时会尝试执行 Alembic migration，因此在启动前要确保：

- 数据库已创建
- `MEETYOU_DATABASE_URL` 正确
- 运行用户对目标数据库有建表和迁移权限

建议：

- 生产环境不要继续依赖 `user/*.json` 作为唯一真相源
- 开发环境可先用本机 PostgreSQL，生产环境建议独立实例或云数据库

### 6. 启动 Core Service

Linux 服务器请显式使用：

```bash
python -m service_runtime
```

不要用：

```bash
python main.py
```

原因：

- `python main.py` 会进入 launcher
- launcher 当前偏向 Windows / PowerShell 使用场景
- 服务器部署应该直接运行可分离的 Core 主入口
- 开发环境仍可继续使用 `python main.py service`

启动成功后默认地址通常是：

```text
http://127.0.0.1:8000
```

### 7. 健康检查

```bash
curl http://127.0.0.1:8000/health
```

如果启用了鉴权，也请为其他 HTTP / WebSocket 调用带上：

- `Authorization: Bearer <token>`
- 或 `X-API-Key: <token>`

## Core 与 Agent 连接

### 正式连接口径

- 客户端实时链路：`GET /client/ws`
- Agent 实时链路：`WSS /agent/ws`
- Agent 协议 schema：`meetyou.agent.v1`

Agent 握手顺序：

```text
agent.hello
agent.hello.ack
agent.capabilities.snapshot
agent.ready
```

需要特别区分两类 heartbeat：

- `Core Heart`：服务端内部时间编排
- `agent heartbeat`：`/agent/ws` 上的在线状态与运行指标上报

二者不是同一件事。

V3 里补齐的空闲心跳（idle poke）属于 `Core Heart` 的一部分，当前口径是：

- 默认启用 1 小时空闲主动触达，可通过配置动态关闭或调整间隔
- 心跳不再回放整段长上下文，而是基于 `conversation_summary`、最近少量非 transient 消息和最近 idle poke 记录生成简短主动消息
- 首次触发 idle poke 且会话尚未压缩时，会顺带执行一次持久化上下文压缩，后续正常会话也复用这份摘要
- 当前配置项包括 `heartbeat_idle_poke_enabled`、`heartbeat_idle_poke_after_seconds`、`heartbeat_idle_poke_cooldown_seconds`、`heartbeat_idle_context_compaction_enabled`
- 运行态可通过 `manage_heartbeat_settings`、`/operator/config`、桌面端设置中心查看或更新

### `desktop-agent` 与 `edge-agent` 的差异

- `desktop-agent`：主要运行在用户设备侧，代表本机能力，并作为桌面 UI 的本地 backend
- `edge-agent`：运行在远端节点侧，代表该边缘节点能力
- 两者都走同一条 `WSS /agent/ws` 主链
- 两者的差异主要由 `agent_type`、`transport_profile`、`workspace_ids` 和本地能力边界决定

不要再按旧 MQTT 方案理解当前 Agent 主链。

### Agent 鉴权优先级

`desktop-agent`：

- 优先读取 `MEETYOU_AGENT_WS_ACCESS_TOKEN`
- 再回退到 `MEETYOU_AGENT_ACCESS_TOKEN`
- 不再回退到 `MEETYOU_GATEWAY_ACCESS_TOKEN`

`edge-agent`：

- 优先读取 `MEETYOU_EDGE_ACCESS_TOKEN`
- 再回退到 `MEETYOU_AGENT_WS_ACCESS_TOKEN`
- 再回退到 `MEETYOU_AGENT_ACCESS_TOKEN`
- 不再回退到 `MEETYOU_GATEWAY_ACCESS_TOKEN`

WebSocket / HTTP 都支持：

- `Authorization: Bearer ...`
- `X-API-Key`

Agent WebSocket 还兼容 `access_token` query。

### 公网部署建议

如果 Core 部署在腾讯云公网服务器：

- `core_base_url` 配成公网 HTTPS 地址，例如 `https://your-domain.example`
- 通过反向代理把外部 `443` 转发到内部 `127.0.0.1:8000`
- Agent 使用 `wss://your-domain.example/agent/ws`
- 客户端使用 `https://your-domain.example` + `GET /client/ws`

### `desktop-agent` 示例

`user/desktop_agent.json`：

```json
{
  "core_base_url": "https://your-domain.example",
  "gateway_access_token": "replace-with-gateway-token",
  "agent_id": "desktop-main-agent",
  "display_name": "Desktop Main Agent",
  "owner_client_id": "desktop-app",
  "owner_client_type": "electron",
  "owner_client_display_name": "Desktop App",
  "workspace_ids": ["personal", "desktop-main", "study"],
  "read_roots": ["."],
  "trusted_write_roots": ["."],
  "cmd_policy_path": "user/cmd_policy.json",
  "mcp_servers_path": "user/mcp_servers.json",
  "heartbeat_interval_seconds": 20,
  "transport_profile": "desktop_wss",
  "local_bridge_enabled": true,
  "local_bridge_host": "127.0.0.1",
  "local_bridge_port": 38951
}
```

说明：

- `desktop-agent` 应部署在用户自己的 Windows 电脑，而不是 Linux Core 服务器上
- `mcp_servers_path` 指向的是本地 MCP 配置，不属于服务端 MCP
- 正常桌面链路下，Electron UI 会优先托管这个 backend；`python -m desktop_agent` 主要保留给 backend-only 调试
- 如果 Core 开启了 Gateway 鉴权，desktop backend 内部访问 Core client/operator/runtime/developer surface 时需要有效的 `gateway_access_token`；建议直接在 `.env` 中配置 `MEETYOU_GATEWAY_ACCESS_TOKEN`

非 Windows 说明：

- `desktop-agent` 的文件、Shell、workspace 能力可以在 Linux / macOS 下继续工作
- 但当前仓库没有为 Linux / macOS 提供和 Windows 等价的桌面 UI Automation / 焦点感知实现
- 因此 Linux / macOS 只能作为“无 UI Automation 的降级桌面后端”，不要把它当成与 Windows 等价的桌面自动化节点

启动命令：

```bash
python -m desktop_agent
```

### `edge-agent` 示例

`user/edge_agent.json`：

```json
{
  "core_base_url": "https://your-domain.example",
  "agent_id": "edge-home-lab-agent",
  "display_name": "Home Lab Edge Agent",
  "agent_type": "edge",
  "workspace_ids": ["home-lab"],
  "heartbeat_interval_seconds": 20,
  "transport_profile": "edge_wss"
}
```

启动命令：

```bash
python -m edge_agent
```

## MCP 配置边界

- `user/core_mcp_servers.json`：只给 Core Service 使用
- `user/mcp_servers.json`：只给 `desktop-agent` 本地 MCP 使用
- 缺少 `core_mcp_servers.json` 不代表 `desktop-agent` 本地 MCP 缺失
- 服务端 MCP 应优先选择可在 Linux 服务器稳定运行、且不依赖桌面环境的能力

`user/core_mcp_servers.example.json` 已改成跨平台基线示例，不再默认写死：

- `npx.cmd`
- `msedge`
- Windows 盘符路径

Core 在服务端拉起 `npx` 型 MCP 时会默认复用工作目录下的 `.npm-cache` 作为可写缓存；如部署环境需要自定义缓存位置，可设置 `MEETYOU_MCP_NPM_CACHE_DIR`。

如果你想保留 Windows 浏览器体验，再在本机额外补 `msedge`、profile、缓存目录等参数。

## 常用接口

正式主接口：

- `GET /health`
- `POST /client/messages`
- `GET /client/ws`
- `GET /client/workspaces`
- `GET /client/workspaces/{workspace_id}/agents`
- `GET /operator/config`
- `GET /operator/memory`
- `GET /runtime/state`
- `GET /runtime/usage`
- `GET /developer/runtime/debug`
- `WSS /agent/ws`

桌面端本地接口：

- `GET /desktop/status`
- `GET /desktop/health`
- `POST /desktop/messages`
- `GET /desktop/ws`
- `GET /desktop/workspaces`
- `GET /desktop/runtime/usage`
- `GET /desktop/runtime/debug`

WeChat Bot 已切换为官方 iLink 路径：启用 `enable_wechat_bot` 后通过二维码登录获取 `bot_token`，使用 `POST /ilink/bot/getupdates` 长轮询接收入站消息，并用 `POST /ilink/bot/sendmessage` 携带 `context_token` 回发文本回复。当前已落地最小文本闭环骨架，真实扫码验收记录见 `docs/v3/design/bot-integration.md`。

兼容说明：

- `GET /ws` 只返回兼容性错误，不再承载聊天流
- 旧 `POST /inputs`、`POST /controls`、根路径 `session/messages` 不再是正式主链

## 生产建议

腾讯云 / Linux 部署至少建议补齐这几项：

- 反向代理：使用 Nginx / Caddy 暴露 `443`，转发到 `127.0.0.1:8000`
- TLS：为 `client/ws` 与 `agent/ws` 提供 `wss://`
- 进程守护：使用 `systemd`、Supervisor 或容器编排保证 `python -m service_runtime` 常驻
- 数据库：使用 PostgreSQL，不要依赖本地临时状态文件充当正式持久化
- 密钥管理：`.env` 放服务器本地，避免把真实 token 和密码写进仓库
- 防火墙：只开放必要端口，数据库优先内网访问
- 日志与监控：至少监控 `/health`、数据库连通性和 Agent 在线状态

一个最小 `systemd` 思路：

- `WorkingDirectory` 指向仓库根目录
- `ExecStart` 使用 `.venv` 中的 Python 执行 `python -m service_runtime`
- `EnvironmentFile` 指向 `.env`
- `Restart=always`

仓库内已提供可直接改造的模板：

- `deploy/systemd/meetyou-core.service.template`
- `deploy/systemd/meetyou-desktop-agent.service.template`
- `deploy/systemd/meetyou-edge-agent.service.template`
- `deploy/systemd/*.env.example`
- `scripts/linux/install-core-systemd.sh`
- `scripts/linux/install-desktop-agent-systemd.sh`
- `scripts/linux/install-edge-agent-systemd.sh`

## 发布与升级策略

MeetYou 当前按三个独立发布单元组织：

- `Core Service`：服务端主链，负责 Gateway、数据库 migration、协议协商与权威状态
- `desktop-agent`：用户设备侧本地能力运行时，单独使用 `requirements-desktop-agent.txt` 与 `python -m desktop_agent`
- `edge-agent`：远端节点运行时，单独使用 `requirements-edge-agent.txt` 与 `python -m edge_agent`

这三个发布单元可以独立打包、独立升级，不要求始终同批次上线；但协议兼容窗口只有有限范围，发布时要按下面顺序推进。

### 推荐升级顺序

1. 升级前先备份 PostgreSQL，并保留上一版 Core / Agent 可执行环境或安装包。
2. 先升级 `Core Service`，确认 Alembic migration、`GET /health`、`GET /operator/agents` 与 `WSS /agent/ws` 正常。
3. 先灰度一小批 `desktop-agent`，确认本机能力、握手协商与附件回传正常。
4. 再灰度一小批 `edge-agent` 或单个 workspace 节点，确认远端节点 capability 调用稳定。
5. 最后再扩大 Agent 覆盖范围；若有 UI 随版本更新，再单独推进 UI。

这样做的原因是：Core 持有协议协商、Gateway 和数据库主链，先升级 Core 可以尽早暴露不兼容问题，并把 Agent 灰度范围控制在最小集合。

### 兼容窗口

当前文档与测试只明确承诺以下窗口：

- `Core N` + `Agent N`：首选组合，`agent.hello.ack.payload.protocol.compatibility_mode` 应为 `negotiated`
- `Core N` + `Agent N-1`：允许，通过 legacy/default 协商降级继续运行
- `Core N-1` + `Agent N`：允许，Agent 需要接受旧 Core 返回的 legacy ack 并回退到兼容路径

不承诺跨两个及以上发布代差的长期兼容，也不要把 `legacy_defaults` 当成常态运行方式。只要灰度确认完成，就应尽快把 Core、`desktop-agent`、`edge-agent` 收敛到同一发布代。

### 灰度建议

- Core 灰度：先在预发或单实例环境验证 `python -m service_runtime`、`/health`、`/client/ws`、`/agent/ws`
- `desktop-agent` 灰度：优先选择一台内部 Windows 设备，检查 `agent.hello -> agent.ready`、一次 capability 调用、一次附件上传/下载
- `edge-agent` 灰度：优先选择一个低风险 workspace 或单个边缘节点，检查 `transport_profile=edge_wss`、heartbeat 与低风险 capability
- 观测重点：`accepted` 是否为 `true`、`compatibility_mode` 是否符合预期、是否出现 `reject_reason`、Agent 在线状态是否持续刷新

如果灰度阶段已经出现 `compatibility_mode=rejected`、大面积 `legacy_defaults`、能力快照缺失或附件回传异常，就不要继续扩大范围。

### 回滚说明

- Agent 回滚优先：如果问题只出现在 `desktop-agent` 或 `edge-agent`，先回滚对应 Agent 包，不必立即回滚 Core
- Core 回滚谨慎：Core 升级前必须先做 PostgreSQL 快照或备份；若 Core 版本需要回退，应连同上一版服务环境和对应数据快照一起恢复
- 停止扩散：一旦灰度出现握手拒绝、持续掉线、能力调用失败或 migration 异常，立即停止后续批次
- 回滚后复核：重新检查 `GET /health`、`GET /operator/agents`、一次 `capability.call.request -> result` 主链，再决定是否重启灰度

如果 Core 已经引入新的数据库 schema 或状态写入口，不要只回滚代码而忽略数据快照；否则会把回滚变成未验证的混搭状态。

## 开发与桌面端补充

### CIL

先确保 service 已启动：

```bash
python main.py cil
```

### 桌面端开发

```bash
cd meetyou-ui
npm install
npm run dev
```

说明：

- `npm run dev` 会拉起 Electron 开发窗口
- Electron main 会优先尝试启动本地 desktop backend
- renderer 默认通过 `http://127.0.0.1:38951` 与本地 backend 交互
- desktop backend 会在本地 desktop session 建立后再启动 `/agent/ws` runtime，避免重复连接注入消息

### 桌面端构建

```bash
cd meetyou-ui
npm run build
```

说明：

- 当前脚本会执行 `tsc && vite build && electron-builder`
- `electron-builder` 当前仅显式声明 Windows `nsis` 目标，产物输出目录是 `meetyou-ui/release/`
- V3 当前的 Windows 打包口径是“Electron UI + PyInstaller one-dir `desktop_agent` backend + runtime template”一起进入安装包
- 打包前先执行 `scripts\\build-desktop-backend.ps1`，生成 `desktop_agent.exe` 和 `meetyou-ui/resources/runtime-template/`
- packaged mode 下，Electron main 会优先从 `process.resourcesPath` 启动内置 desktop backend；开发态才回退到工作区里的 `python main.py desktop-agent`
- 安装包首次运行会把 runtime template 复制到 `app.getPath('userData')/meetyou-runtime`，并在这里维护可写的 `desktop_agent.json`、`mcp_servers.json`、`cmd_policy.json` 与 `.env`
- `.env` 中的 Core 地址、Gateway token、Agent token、Danxi/WebVPN 相关密钥应由 runtime template 或用户运行目录提供；不要依赖安装包外的仓库路径
- 当前桌面端整体仍偏 Windows；Linux 服务器部署的核心目标应是 Core Service，而不是 Electron UI

## 验证建议

Linux 服务器首轮验收建议按这个顺序：

1. `pip install -r requirements.txt`
2. `python -m service_runtime`
3. `curl /health`
4. 确认数据库 migration 成功
5. 用一个桌面 UI 或其他客户端验证 `POST /client/messages` + `GET /client/ws`
6. 启动一个 `python -m edge_agent`，或启动桌面 UI 以自动托管 desktop backend
7. 检查 `GET /client/workspaces/{workspace_id}/agents` 是否能看到在线 Agent

如果你只做最小 Agent 验证，建议关注：

- `agent.hello`
- `agent.hello.ack`
- `agent.capabilities.snapshot`
- `agent.ready`
- `agent.heartbeat`

## 测试

后端最小相关测试：

```bash
python -m unittest tests.test_config_manager
python -m unittest tests.test_gateway_surface_routes
python -m unittest tests.test_danxi_tools
python -m unittest tests.test_desktop_agent_runtime tests.test_edge_agent_protocol tests.test_edge_agent_runtime
```

如果你在 Windows 上做桌面端联调，再补：

```bash
cd meetyou-ui
npm run typecheck
npm run test
npm run build
```

如果你要验证当前 Windows 安装包链路，推荐顺序是：

```bash
scripts\build-desktop-backend.ps1
cd meetyou-ui
npm run build
scripts\manual-acceptance.cmd check
```

说明：

- `scripts/manual-acceptance.cmd` 和 PowerShell 路径主要服务 Windows 桌面链路
- Linux / 腾讯云侧仍建议至少做一次真实 `service -> client/ws -> agent/ws` 联机验收
- Windows 打包验证应重点确认：图标正确、desktop backend 能拉起、设置中心能加载、远端 Core 可连通、Danxi 会话可自动恢复或自动使用 Core 环境变量建会话

## 相关文档

- [docs/README.md](docs/README.md)
- [docs/v3/README.md](docs/v3/README.md)
- [docs/v3/operations/core-deployment.md](docs/v3/operations/core-deployment.md)
- [docs/v3/design/architecture-baseline.md](docs/v3/design/architecture-baseline.md)
- [docs/v3/design/desktop-unified-agent.md](docs/v3/design/desktop-unified-agent.md)
- [docs/v3/design/deployment-and-platform.md](docs/v3/design/deployment-and-platform.md)
- [docs/v3/operations/desktop-unified-acceptance.md](docs/v3/operations/desktop-unified-acceptance.md)
- [docs/v3/design/bot-integration.md](docs/v3/design/bot-integration.md)
- [docs/v3/plan/implementation-plan.md](docs/v3/plan/implementation-plan.md)
- [docs/archive/v2/README.md](docs/archive/v2/README.md)
- [user/README.md](user/README.md)

## License

MIT. See [LICENSE](LICENSE).
