# MeetYou

MeetYou 是一个以 LLM 为核心的个人智能体系统，当前目标形态是“私人服务器本体 + 多客户端（部分客户端内含本地后端）+ workspace 驱动的边缘节点治理”。它围绕统一事件协议组织 `Brain`、`Heart`、`Memory`、`Tools`、`Speaker` 等模块，支持：

- `FastAPI` 服务端本体
- `CIL` 终端客户端
- `Electron + React` 桌面客户端
- 可选 `Feishu Bot`
- 记忆图谱、运行态快照、配置热更新、工具链调用与确认机制

## 当前形态

项目当前默认形态是：

```text
PC Client(UI + Local Backend) ----\
Feishu Client ---------------------> Core Service
Mobile Client(UI + Local Backend)-/      |
                                         |
                                  Memory / Tools / MCP / Heart
                                         |
                                  workspace / operation / approval
                                         |
                           Edge / Bridge Nodes via workspace
```

核心能力包括：

- 统一输入输出协议，便于同时接入 UI、CLI、Bot 与未来移动端
- 多模型适配，当前代码中已接入 OpenAI、Anthropic、Gemini、Ollama
- 长时记忆与记忆图谱查询接口
- 会话级运行状态、推理摘要、token/context 使用量透出
- Assistant Modes 路由机制，支持不同场景下的工具束与策略切换
- 配置中心与热更新接口
- 定时任务、后台心跳、运行宿主机感知能力
- 客户端本地后端 / 边缘节点承接本地文件、Shell、本地 MCP 与设备能力
- Core 仅保留运行所需的平台识别、时间、系统生命体征与少量上下文感知

## 目录结构

```text
core/            核心编排、会话、状态、模式路由、应用生命周期
gateway/         FastAPI HTTP / WebSocket 网关
cil/             基于 gateway 的终端客户端
adapters/        大模型与外部服务适配器
sensors/         输入/输出适配层与系统感知
tools/           工具集合，含 memory、mcp、documents、web_search 等
platform_layer/  Core 运行宿主机感知抽象，不承载终端 shell / 文件能力
prompt/          系统提示词、模式提示词、技能提示词（统一位于 prompt/SKILL）
meetyou-ui/      Electron + React 桌面端
docs/            协议与补充文档
tests/           自动化回归测试
user/            本地配置、工具 schema、记忆数据、MCP 配置等
```

## 环境要求

- Python `3.10+`
- Node.js `18+`（桌面端开发/构建）
- 可用的大模型服务与 API Key
- Windows 优先

说明：

- 当前仓库包含 `uiautomation`、PowerShell launcher、`.cmd` 脚本，以及 Electron Windows 窗口特性，整体体验明显偏向 Windows。
- 后端代码保留了 `platform_layer/linux.py`、`platform_layer/macos.py`，但如果要在非 Windows 环境完整跑通，需要自行验证系统工具链与依赖。
- `platform_layer/` 现在只服务于 Core 运行宿主机感知；本地文件、Shell、本地 MCP 生命周期等终端能力必须通过客户端内本地后端承接。

## 安装

### 1. 安装 Python 依赖

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 安装桌面端依赖

```bash
cd meetyou-ui
npm install
```

## 配置

配置分两层：

- `user/config.json`：非敏感业务配置
- `.env`：密钥与敏感令牌

`user/` 下常用模板已随仓库提供，可参考 [user/README.md](user/README.md) 复制初始化：

- `user/config.example.json` -> `user/config.json`
- `user/tools.example.json` -> `user/tools.json`
- `user/mcp_servers.example.json` -> `user/mcp_servers.json`
- `user/core_mcp_servers.example.json` -> `user/core_mcp_servers.json`
- `user/cmd_policy.example.json` -> `user/cmd_policy.json`
- `user/source_catalog.example.json` -> `user/source_catalog.json`
- `user/memory_graph.example.json` -> `user/memory_graph.json`
- `user/feishu_chat_ids.example.json` -> `user/feishu_chat_ids.json`
- `user/desktop_agent.example.json` -> `user/desktop_agent.json`
- `user/edge_agent.example.json` -> `user/edge_agent.json`

可以先复制环境变量模板：

```bash
copy .env.example .env
```

### 最小 `user/config.json` 示例

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
  "gateway_cors_origins": ["http://127.0.0.1:5173"],
  "gateway_host": "127.0.0.1",
  "gateway_port": 8000,
  "enable_feishu_bot": false
}
```

### `.env` 中常见变量

```env
MEETYOU_API_KEY=
MEETYOU_HEARTBEAT_API_KEY=
MEETYOU_EMBEDDING_API_KEY=
MEETYOU_GATEWAY_ACCESS_TOKEN=
TAVILY_API_KEY=
NOTION_TOKEN=
MEETYOU_FEISHU_APP_ID=
MEETYOU_FEISHU_APP_SECRET=
```

### 常用配置项

- `api_provider` / `api_url` / `model`：主对话模型
- `heartbeat_api_provider` / `heartbeat_api_url` / `heart_model`：后台心跳模型
- `embedding_api_url` / `embedding_model`：向量化与记忆能力
- `thinking_enabled` / `thinking_effort` / `thinking_budget_tokens`：默认推理参数
- `assistant_modes` / `mode_router`：模式路由与工具策略
- `tools_schema_path`：工具 schema
- `source_catalog_path`：研究来源目录
- `enable_feishu_bot`：是否启用飞书
- `gateway_host` / `gateway_port`：网关监听地址
- `gateway_cors_origins`：额外允许的浏览器来源
- `gateway_access_token` / `MEETYOU_GATEWAY_ACCESS_TOKEN`：Gateway / WebSocket 访问令牌

### MCP 配置边界

- `user/core_mcp_servers.json`：仅供 Core 侧安全级、非终端依赖的服务端 MCP 使用
- `user/mcp_servers.json`：仅供 PC 客户端本地后端使用，由 `desktop_agent/` 托管
- 缺少 `core_mcp_servers.json` 只表示 Core 没有启用服务端 MCP，不代表 Desktop Agent 本地 MCP 配置缺失
- `user/desktop_agent.json` 中的 `mcp_servers_path` 用来指向客户端本地 MCP 配置文件

## 启动方式

### 1. 默认启动 Launcher

```bash
python main.py
```

等价于：

```bash
python main.py launcher
```

Launcher 当前支持：

- `start service`
- `start cil`
- `start ui`
- `status`
- `exit`

迁移旧脚本时，请同步将 `start gateway` / `python main.py gateway` 替换为新的 service 入口，详见 [docs/runtime-migration.md](docs/runtime-migration.md)。

### 2. 只启动服务运行时

```bash
python main.py service
```

启动后默认监听：

```text
http://127.0.0.1:8000
```

### 3. 启动终端客户端 CIL

先确保 service 已启动：

```bash
python main.py cil
```

支持的内置命令：

- `/help`
- `/config list`
- `/config get <key>`
- `/config set <key> <value>`

### 4. 启动桌面端 UI

先确保 service 已启动，再在 `meetyou-ui/` 下运行：

```bash
npm run dev
```

如果你从 launcher 执行 `start ui`，会自动尝试拉起 service，再打开 Electron 开发窗口。

## 服务端接口

当前正式主接口按 surface 划分：

- `GET /health`：健康检查
- `POST /client/messages`：客户端提交聊天消息
- `GET /client/ws`：订阅 thread 级实时事件
- `GET /client/workspaces`：列出客户端可用 workspace
- `GET /client/workspaces/{workspace_id}/agents`：列出该 workspace 下在线可用 Agent
- `GET /operator/config`、`GET /operator/memory`：运维 / 观察面接口
- `GET /runtime/state`、`GET /runtime/usage`、`GET /developer/runtime/debug`：运行态与开发诊断接口
- `GET /ws`：旧主聊天路径，现仅返回兼容性错误并提示迁移到 `/client/ws`
- `GET /config`、`GET /memory` 等根路径接口：迁移期兼容入口，不再是默认产品面

正式目标架构见 [docs/core-client-agent-architecture.md](docs/core-client-agent-architecture.md)，workspace 模型见 [docs/workspace-capability-model.md](docs/workspace-capability-model.md)，API 面设计见 [docs/core-api-surfaces.md](docs/core-api-surfaces.md)，当前基线与缺口见 [docs/server-centric-migration-baseline.md](docs/server-centric-migration-baseline.md)。

### `POST /client/messages` 示例

```json
{
  "thread_id": "thread-personal-001",
  "workspace_id": "personal",
  "client_id": "desktop-app",
  "content": "帮我总结今天的任务"
}
```

### WebSocket 连接示例

```text
ws://127.0.0.1:8000/client/ws?thread_id=thread-personal-001
```

客户端会先收到 `connection` 帧，随后按 thread 推送统一 envelope：

- `event`
- `runtime`
- `ack`
- `error`

如果旧客户端仍连接根路径 `/ws`，服务端会返回 `legacy_websocket_path_removed` 错误并关闭连接。

## PC 客户端说明

`meetyou-ui/` 是 PC 客户端前端；`desktop_agent/` 则是 PC 客户端内本地后端的当前实现。两者共同构成 PC 客户端。

`edge_agent/` 是按 workspace 接入的边缘 Agent 运行时。它和 `desktop_agent/` 当前都通过统一的 `WSS /agent/ws` + `meetyou.agent.v1` transport 接入 Core，只是 `transport_profile` 分别标记为 `desktop_wss` 与 `edge_wss`。

- 聊天界面
- 推理摘要展示
- 工具活动展示
- 运行状态条
- token/context 统计面板
- 设置页
- 记忆图谱页

开发命令：

```bash
cd meetyou-ui
npm run dev
```

构建命令：

```bash
npm run build
```

## Edge Agent

启动边缘 Agent：

```bash
python main.py edge-agent
```

默认读取 `user/edge_agent.json`，并通过 `ws://127.0.0.1:8000/agent/ws` 接入服务端 Gateway。

## 飞书 Bot

启用飞书前至少需要：

- `enable_feishu_bot = true`
- `.env` 中配置 `MEETYOU_FEISHU_APP_ID`
- `.env` 中配置 `MEETYOU_FEISHU_APP_SECRET`

相关持久化文件：

- `user/feishu_chat_ids.json`

- Feishu 输入会通过 `GatewayConversationClient` 进入 `POST /client/messages`
- Feishu 输出、审批、补充输入和 operation 更新都通过 `GET /client/ws` 事件回推
- `FeishuInputAdapter` 的旧 event bus 直连分支仅保留兼容用途，不再是正式主链

## 测试

仓库当前包含较多后端测试，集中在 `tests/` 目录，例如：

- 运行态与 usage
- gateway 配置与记忆接口
- assistant modes
- memory / task scheduler
- scenario tools / document tools

如果本地已安装测试依赖，可执行：

```bash
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

## 相关文档

- [docs/core-client-agent-architecture.md](docs/core-client-agent-architecture.md)：目标拓扑与职责分层
- [docs/workspace-capability-model.md](docs/workspace-capability-model.md)：Workspace、Capability 与作用域模型
- [docs/core-api-surfaces.md](docs/core-api-surfaces.md)：Client / Agent / Operator / Developer API 面
- [docs/server-centric-migration-baseline.md](docs/server-centric-migration-baseline.md)：当前基线、缺口与后续收口顺序
- [docs/manual-startup-acceptance.md](docs/manual-startup-acceptance.md)：人工启动验收与排障手册
- [docs/runtime-migration.md](docs/runtime-migration.md)：运行时破坏性迁移说明
- [docs/playwright-mcp.md](docs/playwright-mcp.md)：Playwright MCP 说明

## License

MIT. See [LICENSE](LICENSE).
