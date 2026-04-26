# User Templates

`user/` 用于本地运行态配置、缓存和状态文件。真实运行文件默认被 `.gitignore` 忽略；仓库只保留可复制的模板。

常用模板：

- `config.example.json` -> `config.json`
- `config.docker.example.json` -> `config.json`（Core Docker / Compose 路径）
- `tools.example.json` -> `tools.json`
- `core_mcp_servers.example.json` -> `core_mcp_servers.json`
- `mcp_servers.example.json` -> `mcp_servers.json`
- `cmd_policy.example.json` -> `cmd_policy.json`
- `source_catalog.example.json` -> `source_catalog.json`
- `memory_graph.example.json` -> `memory_graph.json`
- `feishu_chat_ids.example.json` -> `feishu_chat_ids.json`
- `desktop_client.example.json` -> `desktop_client.json`
- `edge_client.example.json` -> `edge_client.json`

也可以使用初始化脚本：

- `python scripts/prepare_core_runtime.py --profile host`
- `python scripts/prepare_core_runtime.py --profile docker --output-root deploy/docker/runtime`
- `python scripts/check_core_runtime.py --profile host --env-file .env`
- `python scripts/check_core_runtime.py --profile docker --runtime-root deploy/docker/runtime`

`desktop_client.json` 常用字段：

- `core_base_url`: Core Service 基地址；runtime 会转换为 `GET /client/ws`
- `core_access_token`: Desktop Client 访问 Core 的统一访问令牌；也可由 `MEETYOU_CLIENT_ACCESS_TOKEN` 或 `MEETYOU_GATEWAY_ACCESS_TOKEN` 提供
- `gateway_access_token`: desktop backend 访问 Core HTTP surface 时使用的访问令牌
- `client_id`: Desktop Client 唯一标识
- `display_name`: 显示名称
- `workspace_ids`: 当前 Client 声明加入的 workspace 列表
- `available_tools`: 该 Client 作为调用起点时允许发起的 tool key
- `executable_tools`: 该 Client 作为目标时可承接的 directed tool key
- `read_roots`: 本地文件读取根目录
- `trusted_write_roots`: 本地写入可信根目录
- `cmd_policy_path`: 本地命令策略文件路径
- `mcp_servers_path`: Desktop Client 本地 MCP 配置文件路径
- `transport_profile`: 连接形态，默认 `desktop_wss`
- `local_bridge_enabled`: 是否开启 Electron UI 使用的本地 `/desktop/*` HTTP / WS 入口
- `local_bridge_host` / `local_bridge_port`: 本地 desktop backend 监听地址，默认 `127.0.0.1:38951`

`edge_client.json` 常用字段：

- `core_base_url`: Core Service 基地址；runtime 会转换为 `GET /client/ws`
- `core_access_token`: Edge Client 访问 Core 的统一访问令牌
- `client_id`: Edge Client 唯一标识
- `client_type`: 当前边缘执行器类型，默认 `edge`
- `workspace_ids`: 允许加入的 workspace 列表
- `available_tools`: 该 Client 作为调用起点时允许发起的 tool key
- `executable_tools`: 该 Client 作为目标时可承接的 directed tool key
- `heartbeat_interval_seconds`: 心跳间隔
- `transport_profile`: 连接形态，默认 `edge_wss`

正式连接口径：

- `desktop_client` 与 `edge_client` 都通过 `GET /client/ws` + `meetyou.client.ws.v1` 接入 Core
- 握手帧为 `client.hello`、`client.tools.snapshot`、`client.ready`、`client.heartbeat`
- directed tool 调用使用 `tool.call.request`、`tool.call.result`、`tool.call.error`
- 同一 `client_id` 允许多条 `/client/ws` 连接，每条连接可声明自己的订阅、会话上下文与可执行 tools
- 桌面 UI 默认通过 `desktop_client` 暴露的 loopback `/desktop/*` API 与本地 backend 交互
- 不再存在正式 `/agent/ws` 运行时，也不再使用 `MEETYOU_AGENT_*` 访问令牌

MCP 文件边界：

- `core_mcp_servers.json`: 仅用于 Core 侧安全 MCP，适合服务端可运行且不依赖终端在线的能力
- `mcp_servers.json`: 仅用于 Desktop Client 本地 MCP，依赖本机环境与本地权限边界
- 缺少 `core_mcp_servers.json` 不代表 Desktop Client 的 `mcp_servers.json` 缺失
- Core 自身的轻量运行时工具仍是 runtime-native tool，不需要配置到 `core_mcp_servers.json`

运行时可能自动生成：

- `memory_tasks.json`
- `memory_tasks.json.bak`

首次初始化建议至少准备：

- `config.json`
- `tools.json`
- `cmd_policy.json`
- `source_catalog.json`
- `memory_graph.json`
