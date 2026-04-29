# Core Runtime And Endpoint Architecture

本文记录 V4 当前架构。旧 Client / Agent 术语只作为历史背景，不再是运行时主链。

## 角色

- Core: 拥有 Thread、Message、Run、RunEvent、Scheduler、Heartbeat、Memory、Operation、Delivery。
- Endpoint Provider: Desktop、Edge、Feishu、WeChatBot、webhook 等，只提供连接、订阅、投递接收和 EndpointCapability。
- Actor: 权限主体。
- Workspace: 工作区策略边界。
- ExecutionTarget: 工具执行目标，包含 `core.local` 和 Endpoint 目标。

Core 不是 Client。`core.local` 是进程内 ExecutionTarget。

## 数据主链

1. 输入通过 `/runtime/messages` 或 Endpoint 事件进入 Core。
2. Core 归属 Thread / Message，并创建 Run。
3. Brain 运行期间产生 RunEvent；RunEvent 先写 RunEventLog。
4. Delivery fan-out 将 RunEvent、notice、operation_update、message 投给订阅端点。
5. 最终回复由 MessageService 写入 assistant Message。

非流式外部端点只应在 `message.completed` 后发送最终文本，不能把 `message.delta` 和最终消息拼接后重复发送。

## Endpoint Protocol

唯一实时入口为 `GET /endpoint/ws`，协议名 `meetyou.endpoint.ws.v4`。

Endpoint Provider 必须声明能力快照。工具执行由 ToolRouter 选择 ExecutionTarget 后发起，Endpoint Provider 只执行被路由到自身的 `tool.call.request`。

`endpoint.heartbeat` 是连接保活，不等同于系统心跳。

## Tool Routing

ExecutionTarget 值：

- `core.local`
- `endpoint`
- `workspace_any_endpoint`
- `prefer_endpoint_fallback_core`

旧 `core_only`、`specific_agent`、`workspace_any_agent`、`specific_endpoint` 不再作为运行时枚举使用。

## Scheduler

Scheduler 是唯一系统级调度时钟。`system.heartbeat` 是 Scheduler-owned preset job，不可删除，不能手动创建，只能启停和调整 `interval_seconds`。

普通 Scheduler Job 的执行通过 `scheduled_jobs`、`scheduled_job_runs`、Run、RunEvent 和 Delivery 记录。

## Workflow Surface

公开 mode 收敛为：

- `general`
- `automation`
- `danxi`

Procedure 已删除。可复用工作流由 SKILL 承担，工具声明和 UI 不再暴露 Procedure 入口。
