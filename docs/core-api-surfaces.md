# Core API Surfaces V4

V4 的对外接口按职责分层，不再保留 V3 Client surface。

## 正式入口

- Runtime HTTP facade: `/runtime/*`，面向 UI、Desktop 本地桥、外部 channel adapter 的资源入口。
- Endpoint WebSocket: `GET /endpoint/ws`，协议名 `meetyou.endpoint.ws.v4`，面向 Desktop、Edge、Feishu、WeChatBot、webhook 等 Endpoint Provider。
- Desktop 本地桥: `/desktop/*`，只代理 `/runtime/*`、`/operator/*`、`/developer/*`。
- Operator: `/operator/*`，用于部署、工作区、调度 Job 和受控治理。
- Developer: `/developer/*`，只用于调试和诊断。

`/client/*` 和 `/client/ws` 已移除。若清理期仍保留拒绝路由，只能返回明确的 removed 响应，不得转发或适配到 V4。

## Runtime 资源

Core 拥有以下资源和语义：Thread、Message、Run、RunEvent、Scheduler、Heartbeat、Memory、Operation、Delivery、Attachment、ContextPool。

Runtime HTTP 主要资源：

- `POST /runtime/threads`
- `POST /runtime/sessions`
- `POST /runtime/messages`
- `POST /runtime/operations`
- `GET /runtime/operations/{operation_id}`
- `POST /runtime/approvals/{approval_id}/decision`
- `GET /runtime/workspaces`
- `GET /runtime/workspaces/{workspace_id}/endpoints`
- `GET /runtime/context-pool/query`
- `POST /runtime/attachments/upload-ticket`
- `PUT /runtime/attachments/upload/{ticket_id}`
- `POST /runtime/attachments/{attachment_id}/complete`
- `GET /runtime/threads/{thread_id}/attachments`
- `GET /runtime/attachments/{attachment_id}/download-ticket`
- `GET /runtime/attachments/content/{attachment_id}`

`POST /runtime/messages` accepts `endpoint_message_id` for Endpoint Provider inbound idempotency. For the same thread, endpoint, role, and `endpoint_message_id`, Core returns the existing Message with `idempotent_replay=true` and does not enqueue another assistant run.

Danxi 资源也在 `/runtime/danxi/*` 下。登录和 WebVPN Cookie 更新只接受加密载荷或服务端环境凭据，不接受明文密码、Cookie 或 token。

## Endpoint Protocol

Endpoint Provider 只提供端点和能力，不拥有会话、运行、记忆、调度、投递或权限语义。

V4 WebSocket frame：

- 生命周期：`endpoint.hello`、`endpoint.capabilities.snapshot`、`endpoint.ready`、`endpoint.heartbeat`、`endpoint.goodbye`
- 订阅：`subscription.start`、`subscription.update`、`subscription.stop`
- 投递：`delivery.message`、`delivery.run_event`、`delivery.notice`、`delivery.operation_update`、`delivery.inbox_item`
- 工具：`tool.call.request`、`tool.call.result`、`tool.call.error`、`tool.call.cancel`

`endpoint.heartbeat` 只做连接保活，不触发 `system.heartbeat`。

## Message / Run / Delivery

- 用户输入先进入 Core-owned Thread / Message。
- Run 由 Core 创建，流式事件写入 RunEventLog。
- Delivery 只负责投递 `message`、`run_event`、`notice`、`operation_update`，不生成回复。
- Streaming 必须走 RunEventLog + Delivery fan-out。
- 最终 assistant reply 必须由 MessageService 持久化为 assistant Message。
- `assistant.progress_notice` 是 Runtime Action / RunEvent，不走 ToolRouter，不创建 Operation，不进入最终 assistant message。

## Tool / Execution

工具调用统一走 ToolRouter + ExecutionTarget：

- `core.local`: Core 进程内 ExecutionTarget，不是 Client。
- `endpoint`: 指定 Endpoint 能力。
- `workspace_any_endpoint`: 工作区内可用 Endpoint 选路。
- `prefer_endpoint_fallback_core`: 优先 Endpoint，必要时回落 Core。

权限挂在 Actor / Workspace / RunPolicy；执行能力挂在 EndpointCapability。

## Scheduler / Heartbeat

Scheduler 是唯一系统级调度时钟。持久化资源是 `scheduled_jobs` 和 `scheduled_job_runs`。

- `system.heartbeat` 是 Scheduler 预设系统 Job。
- `system.heartbeat` 不可删除、不可手动创建。
- `system.heartbeat` 只能启停和修改 `interval_seconds`。
- 普通 scheduled job 可 CRUD、启停和手动触发。
- 旧 TaskManager 后台控制流不再执行 scheduled task / scheduled reminder。

## Workflow

Procedure 已删除。可复用工作流统一使用 SKILL：

- `list_skills` 查找可复用工作流指导。
- `load_skill` 注入具体 SKILL。
- `create_skill` 只创建 SKILL，不创建 Procedure。

公开 assistant mode 仅为 `general`、`automation`、`danxi`。旧 `normal`、`auto`、`documents`、`research`、`study` 归一到 `general`，旧 `office` 归一到 `automation`。
