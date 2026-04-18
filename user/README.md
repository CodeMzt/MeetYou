# User Templates

`user/` 目录默认用于存放本地配置、运行时数据和缓存，因此真实文件仍然会被 `.gitignore` 忽略。

仓库中保留以下模板文件，供初始化本地环境时复制：

- `config.example.json` -> `config.json`
- `config.docker.example.json` -> `config.json`（Core Docker / Compose 路径）
- `tools.example.json` -> `tools.json`
- `mcp_servers.example.json` -> `mcp_servers.json`
- `cmd_policy.example.json` -> `cmd_policy.json`
- `source_catalog.example.json` -> `source_catalog.json`
- `memory_graph.example.json` -> `memory_graph.json`
- `feishu_chat_ids.example.json` -> `feishu_chat_ids.json`
- `desktop_agent.example.json` -> `desktop_agent.json`
- `edge_agent.example.json` -> `edge_agent.json`
- `core_mcp_servers.example.json` -> `core_mcp_servers.json`

也可以直接使用初始化脚本：

- `python scripts/prepare_core_runtime.py --profile host`：复制 `.env.example`、`config.example.json` 与最小 Core 运行模板
- `python scripts/prepare_core_runtime.py --profile docker --output-root deploy/docker/runtime`：在 `deploy/docker/runtime/` 下生成隔离的 Docker 运行模板
- `python scripts/check_core_runtime.py --profile host --env-file .env`：在启动前检查 host 路径是否齐备
- `python scripts/check_core_runtime.py --profile docker --runtime-root deploy/docker/runtime`：在启动前检查隔离 Docker 路径是否齐备

`desktop_agent.json` 常用字段：

- `core_base_url`: Core Service 基地址；runtime 会把它转换为正式入口 `WSS /agent/ws`
- `agent_access_token`: Agent 专用访问令牌；留空时仍可由环境变量注入
- `gateway_access_token`: desktop backend 内部访问 Core 的 `client/*`、`operator/*`、`developer/*`、`runtime/*` 时使用的 Gateway 访问令牌；缺失时回退到 `MEETYOU_GATEWAY_ACCESS_TOKEN` 或 `agent_access_token`
- `agent_id`: Desktop Agent 唯一标识
- `workspace_ids`: 当前 Agent 声明加入的 workspace 列表
- `owner_client_id`: 该 Desktop Agent 归属的 Client 标识，默认 `desktop-app`
- `owner_client_type`: 归属 Client 类型，默认 `electron`
- `owner_client_display_name`: 归属 Client 显示名
- `read_roots`: Agent 允许读取的根目录
- `trusted_write_roots`: Agent 允许写入的可信根目录
- `cmd_policy_path`: 本地命令策略文件路径
- `mcp_servers_path`: Desktop Agent 本地 MCP 配置文件路径
- `transport_profile`: 当前统一 agent websocket transport 下的 profile，默认 `desktop_wss`
- `local_bridge_enabled`: 是否开启桌面 UI 使用的本地 desktop backend HTTP / WS 入口
- `local_bridge_host` / `local_bridge_port`: 本地 desktop backend 监听地址，默认 `127.0.0.1:38951`

`edge_agent.json` 常用字段：

- `core_base_url`: Core Service 基地址；runtime 会把它转换为正式入口 `WSS /agent/ws`
- `agent_access_token`: Agent 专用访问令牌；也支持由环境变量注入
- `agent_id`: 边缘 Agent 唯一标识
- `agent_type`: 当前边缘执行器类型，默认 `edge`
- `workspace_ids`: 允许加入的 workspace 列表
- `heartbeat_interval_seconds`: 心跳间隔
- `transport_profile`: 当前统一 agent websocket transport 下的 profile，默认 `edge_wss`

正式连接口径：

- `desktop-agent` 与 `edge-agent` 都通过同一条 `WSS /agent/ws` + `meetyou.agent.v1` 主链接入 Core
- 两者都先发送 `agent.hello`，再完成 `agent.capabilities.snapshot` 与 `agent.ready` 握手，不存在独立 `POST /agent/register` 正式入口
- `desktop-agent` 额外通过 `owner_client_*` 字段声明它归属于哪个桌面 Client；`edge-agent` 通常不带这组字段，而主要依赖 `workspace_ids`
- 桌面 UI 默认不再直接访问 Core，而是通过 `desktop-agent` 暴露的 loopback `/desktop/*` API 与后端交互
- 二者的差异主要由 `agent_type`、`transport_profile` 与本地能力边界决定，而不是走两套不同协议
- Agent 鉴权优先读各自专用 env，再回退到共享 `MEETYOU_AGENT_ACCESS_TOKEN` 或 `MEETYOU_GATEWAY_ACCESS_TOKEN`

MCP 文件边界：

- `core_mcp_servers.json`：仅用于 `Core MCP`，承载服务端可安全运行、且不依赖终端在线的 MCP 与非端侧集成能力
- `mcp_servers.json`：仅用于桌面端本地 MCP，由 Desktop Agent 托管并依赖本机环境
- 如果日志提示缺少 `core_mcp_servers.json`，只表示 Core 侧未配置服务端 MCP，不代表 Desktop Agent 的 `mcp_servers.json` 缺失
- 纯进程内轻量工具与 Core 自身状态管理能力仍保留为 runtime-native tool，不需要配置到 `core_mcp_servers.json`
- 模板边界已对齐当前架构：`core_mcp_servers.example.json` 提供跨平台服务端基线示例，`mcp_servers.example.json` 仍保留偏 Windows 客户端的本地文件类 MCP 示例

运行时会自动在 `user/` 下生成任务存储文件：

- `memory_tasks.json`
- `memory_tasks.json.bak`

建议首次初始化时至少准备：

- `config.json`
- `tools.json`
- `cmd_policy.json`
- `source_catalog.json`
- `memory_graph.json`

如果暂时不用 MCP 或飞书，可以先保留对应示例文件不复制。
