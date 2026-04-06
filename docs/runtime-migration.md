# Service Runtime Migration

## 破坏性变更

- 运行入口统一为 `python main.py service`
- Launcher 命令改为 `start service`
- `enable_gateway` 已删除，服务运行时始终托管 HTTP / WebSocket 网关
- `source_profiles` 已删除，研究来源只从 `source_catalog_path` 指向的目录文件读取
- 任务系统不再从 `memory_graph.json` 导入 legacy `task` 记录，旧任务记录会在记忆层初始化时清理
- 主路径工具错误统一为结构化 `ToolCallResult.error`，不再依赖 `"Error: ..."` 字符串契约

## 升级步骤

1. 将所有启动脚本里的 `python main.py gateway` 改为 `python main.py service`
2. 将 Launcher 自动化脚本里的 `start gateway` 改为 `start service`
3. 从 `user/config.json` 和环境模板中删除 `enable_gateway`
4. 将旧的 `source_profiles` 配置迁移到 `user/source_catalog.json` 的 `default_source_profiles`
5. 如果有自定义客户端直接解析工具返回值里的 `"Error: ..."`, 改为读取结构化错误对象里的 `code`、`category`、`message`

## 兼容性说明

- `gateway_host`、`gateway_port`、`gateway_access_token` 继续保留，它们描述的是服务内置网关适配层的监听与鉴权配置
- `docs/interface.md` 描述的 HTTP / WebSocket 协议保持有效
