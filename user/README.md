# User Templates

`user/` 目录默认用于存放本地配置、运行时数据和缓存，因此真实文件仍然会被 `.gitignore` 忽略。

仓库中保留以下模板文件，供初始化本地环境时复制：

- `config.example.json` -> `config.json`
- `tools.example.json` -> `tools.json`
- `mcp_servers.example.json` -> `mcp_servers.json`
- `cmd_policy.example.json` -> `cmd_policy.json`
- `source_catalog.example.json` -> `source_catalog.json`
- `memory_graph.example.json` -> `memory_graph.json`
- `feishu_chat_ids.example.json` -> `feishu_chat_ids.json`
- `desktop_agent.example.json` -> `desktop_agent.json`
- `edge_agent.example.json` -> `edge_agent.json`
- `core_mcp_servers.example.json` -> `core_mcp_servers.json`

`desktop_agent.json` 常用字段：

- `read_roots`: Agent 允许读取的根目录
- `trusted_write_roots`: Agent 允许写入的可信根目录
- `cmd_policy_path`: 本地命令策略文件路径
- `mcp_servers_path`: Desktop Agent 本地 MCP 配置文件路径

`edge_agent.json` 常用字段：

- `agent_id`: 边缘 Agent 唯一标识
- `workspace_ids`: 允许加入的 workspace 列表
- `heartbeat_interval_seconds`: 心跳间隔
- `transport_profile`: 当前统一 agent websocket transport 下的 profile，默认 `edge_wss`

MCP 文件边界：

- `core_mcp_servers.json`：仅用于 `Core MCP`，承载服务端可安全运行、且不依赖终端在线的 MCP 与非端侧集成能力
- `mcp_servers.json`：仅用于桌面端本地 MCP，由 Desktop Agent 托管并依赖本机环境
- 如果日志提示缺少 `core_mcp_servers.json`，只表示 Core 侧未配置服务端 MCP，不代表 Desktop Agent 的 `mcp_servers.json` 缺失
- 纯进程内轻量工具与 Core 自身状态管理能力仍保留为 runtime-native tool，不需要配置到 `core_mcp_servers.json`
- 模板边界已对齐当前架构：`core_mcp_servers.example.json` 预留 `tavily_web` 与 `browser_automation`，`mcp_servers.example.json` 仅保留本地文件类 MCP 示例

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
