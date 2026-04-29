# Runtime Migration Notes V4

V4 是开发期替换，不做 V3 兼容层。

## 已迁移入口

- Runtime HTTP: `/runtime/*`
- Endpoint realtime: `/endpoint/ws`
- Desktop local bridge: `/desktop/*`，只代理 `/runtime/*`、`/operator/*`、`/developer/*`

旧 `/client/*` 和 `/client/ws` 不再承载业务；清理期拒绝路由只能返回 removed 响应。

## 已迁移模型

- Client 概念降级为 Endpoint Provider。
- `source_client_id` / `target_client_id` 替换为 `origin_endpoint_id`、`target_endpoint_id`、`execution_target_id`。
- `core.local` 是 Core 进程内 ExecutionTarget。
- Delivery 只做投递，不生成回复。
- Streaming 走 RunEventLog + Delivery fan-out。
- Scheduler 取代旧 TaskManager 后台调度控制流。
- Procedure 删除，复用工作流改用 SKILL。

## 配置注意

- `user/config.json` 是本地运行配置，secret 放 `.env`。
- 本地真实测试如需避开远程 Core 配置，应使用当前进程环境变量覆盖，不要改真实 `.env`。
- Desktop Provider 使用 `user/desktop_client.json`。
- Edge Provider 使用 `user/edge_client.json`。
- Core-side MCP 与 Desktop local MCP 分别使用 `user/core_mcp_servers.json` 和 `user/mcp_servers.json`。

## 验证

迁移相关改动至少跑：

- backend unittest discovery
- migration / bootstrap tests
- endpoint protocol tests
- scheduler tests
- tool router tests
- delivery tests
- frontend typecheck / test / build
- 本地 Core + Desktop + UI 真实测试
