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
- 正式客户端入口仍是 `POST /client/messages` 与 `GET /client/ws`
- 根路径兼容 surface 仅保留迁移错误或过渡性只读能力，后续会继续收缩

## Core 启动职责

- `core/app.py` 的 `App.setup()` 在 Core 完成依赖装配、网关启动并进入 idle 后，会主动向 `EventBus.inbound_queue` 注入一次 `system:boot` 启动消息
- 这条启动消息使用 `start` prompt 构造，目标为 broadcast，并标记为 transient boot event，用于触发 Core 启动后的首轮唤醒
- Launcher、service 入口与外部客户端只负责拉起 Core；boot 消息注入的责任明确归属 Core 启动阶段本身
