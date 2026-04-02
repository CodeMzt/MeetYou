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

建议首次初始化时至少准备：

- `config.json`
- `tools.json`
- `cmd_policy.json`
- `source_catalog.json`
- `memory_graph.json`

如果暂时不用 MCP 或飞书，可以先保留对应示例文件不复制。
