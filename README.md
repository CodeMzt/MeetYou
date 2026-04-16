# MeetYou

MeetYou 是一个以 LLM 为核心的个人智能体系统，目标形态是“私人服务器本体 + 多客户端 + workspace 驱动的 Agent / 边缘节点治理”。当前最推荐的部署方式是：

- Linux 云服务器运行 Core Service
- Windows PC 运行桌面客户端与 `desktop-agent`
- 需要时在额外节点运行 `edge-agent`

这份 README 以“Linux 云服务器部署 + Core / Agent 接入”为主线，面向首轮落地和生产化部署。

## 部署拓扑

```text
Desktop UI --------------\
Desktop Agent ------------> Core Service (Linux / Tencent Cloud)
Feishu Client ------------/        |
                                   |
                            Memory / Tools / MCP / Heart
                                   |
                         workspace / operation / approval
                                   |
                           Edge Agents via /agent/ws
```

角色边界：

- `Core Service`：服务端主链，负责会话、路由、记忆、任务、工具调度、Gateway 与运行时状态
- `desktop-agent`：运行在用户自己的设备上，承接本地文件、Shell、本地 MCP 与桌面能力
- `edge-agent`：运行在远端边缘节点上，按 workspace 接入并提供该节点的能力
- `meetyou-ui/`：桌面客户端前端，不建议部署到 Linux 服务器上作为生产主链

关键原则：

- 客户端正式实时入口是 `GET /client/ws`
- Agent 正式实时入口是 `WSS /agent/ws`
- 根路径 `GET /ws` 只保留兼容性错误，不再承载正式聊天流
- 本地文件、Shell、本地 MCP 生命周期属于 Agent 边界，不要重新塞回 Core

## 适用平台

- Core Service：推荐 `Linux`，也可运行在 `Windows` / `macOS`
- Desktop UI / `desktop-agent`：当前体验明显偏向 `Windows`
- `edge-agent`：适合运行在 Linux 小主机、树莓派、远端工作机等节点

当前仓库仍保留一些 Windows 优先能力，例如 `uiautomation`、PowerShell launcher、`.cmd` 脚本和 Electron 的部分窗口行为；但 `requirements.txt` 中相关依赖已改为按平台条件安装，Linux 部署 Core 时不会再因 `uiautomation`、`pywin32` 被直接阻塞。

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
docs/            协议与补充文档
tests/           自动化回归测试
user/            本地配置模板与运行态数据目录
```

## Linux 服务器部署

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

复制模板：

```bash
cp .env.example .env
cp user/config.example.json user/config.json
cp user/tools.example.json user/tools.json
cp user/cmd_policy.example.json user/cmd_policy.json
cp user/source_catalog.example.json user/source_catalog.json
cp user/memory_graph.example.json user/memory_graph.json
```

按需复制：

```bash
cp user/core_mcp_servers.example.json user/core_mcp_servers.json
cp user/edge_agent.example.json user/edge_agent.json
cp user/desktop_agent.example.json user/desktop_agent.json
```

说明：

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
- `MEETYOU_AGENT_ACCESS_TOKEN`：共享 Agent 访问令牌；`desktop-agent` 与 `edge-agent` 都可回退到它
- `MEETYOU_EDGE_ACCESS_TOKEN`：仅给 `edge-agent` 的专用覆盖令牌
- `MEETYOU_DATABASE_URL`：正式持久化数据库连接串

如果使用 Danxi / WebVPN 凭证加密链路，还建议单独配置：

```env
MEETYOU_CREDENTIAL_SECRET=
```

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

### `desktop-agent` 与 `edge-agent` 的差异

- `desktop-agent`：主要运行在用户设备侧，代表本机能力
- `edge-agent`：运行在远端节点侧，代表该边缘节点能力
- 两者都走同一条 `WSS /agent/ws` 主链
- 两者的差异主要由 `agent_type`、`transport_profile`、`workspace_ids` 和本地能力边界决定

不要再按旧 MQTT 方案理解当前 Agent 主链。

### Agent 鉴权优先级

`desktop-agent`：

- 优先读取 `MEETYOU_AGENT_ACCESS_TOKEN`
- 可回退到 `MEETYOU_GATEWAY_ACCESS_TOKEN`

`edge-agent`：

- 优先读取 `MEETYOU_EDGE_ACCESS_TOKEN`
- 再回退到 `MEETYOU_AGENT_ACCESS_TOKEN`
- 最后回退到 `MEETYOU_GATEWAY_ACCESS_TOKEN`

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
  "agent_access_token": "replace-with-agent-token",
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
  "transport_profile": "desktop_wss"
}
```

说明：

- `desktop-agent` 应部署在用户自己的 Windows 电脑，而不是 Linux Core 服务器上
- `mcp_servers_path` 指向的是本地 MCP 配置，不属于服务端 MCP

启动命令：

```bash
python -m desktop_agent
```

### `edge-agent` 示例

`user/edge_agent.json`：

```json
{
  "core_base_url": "https://your-domain.example",
  "agent_access_token": "replace-with-edge-token",
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

### 桌面端构建

```bash
cd meetyou-ui
npm run build
```

说明：

- 当前桌面端整体仍偏 Windows
- Linux 服务器部署的核心目标应是 Core Service，而不是 Electron UI

## 验证建议

Linux 服务器首轮验收建议按这个顺序：

1. `pip install -r requirements.txt`
2. `python -m service_runtime`
3. `curl /health`
4. 确认数据库 migration 成功
5. 用一个客户端验证 `POST /client/messages` + `GET /client/ws`
6. 启动一个 `python -m edge_agent` 或 `python -m desktop_agent`
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
python -m unittest tests.test_gateway_agent_api
python -m unittest tests.test_edge_agent_protocol tests.test_edge_agent_runtime
```

如果你在 Windows 上做桌面端联调，再补：

```bash
cd meetyou-ui
npm run typecheck
npm run test
```

说明：

- 当前仓库没有现成的 Linux / 腾讯云一键验收脚本
- `scripts/manual-acceptance.cmd` 和 PowerShell 路径主要服务 Windows 桌面链路
- 本次仓库内验证主要覆盖文档/模板一致性与本地自动化测试，仍建议在真实 Linux 云服务器上完成一次 `service -> client/ws -> agent/ws` 联机验收

## 相关文档

- [docs/core-client-agent-architecture.md](docs/core-client-agent-architecture.md)
- [docs/workspace-capability-model.md](docs/workspace-capability-model.md)
- [docs/core-api-surfaces.md](docs/core-api-surfaces.md)
- [docs/agent-protocol-v1.md](docs/agent-protocol-v1.md)
- [docs/manual-startup-acceptance.md](docs/manual-startup-acceptance.md)
- [docs/runtime-migration.md](docs/runtime-migration.md)
- [docs/playwright-mcp.md](docs/playwright-mcp.md)
- [user/README.md](user/README.md)

## License

MIT. See [LICENSE](LICENSE).
