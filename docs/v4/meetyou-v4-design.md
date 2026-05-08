# MeetYou V4 设计方案

> 目标：把 MeetYou 从 V3 的 **Core + Clients + Tools** 调度模型，重构为 V4 的 **Core-owned Runtime + Endpoint Routing** 模型。V4 中，Core 拥有 Thread、Message、Run、Scheduler、Heartbeat、Memory、Operation 和 Delivery；Desktop / Edge / Feishu / WeChatBot 等都只是 Endpoint Provider。Client 不再拥有对话、任务或心跳。

---

## V4 不可违反原则

1. Core owns Thread / Message / Run / Scheduler / Heartbeat / Memory / Operation / Delivery。
2. Client is only Endpoint Provider。
3. Core is not Client；`core.local` 是 in-process `ExecutionTarget`，不是 Client。
4. Scheduler 是唯一系统级调度时钟。
5. `system.heartbeat` 是 Scheduler 内不可删除、可启停、可修改间隔的系统预设 Job。
6. `endpoint.heartbeat` 只是连接保活，不触发 `system.heartbeat`。
7. `short_reply` 不再作为 directed tool；替换为 `assistant.progress_notice` RunEvent / Runtime Action。
8. Delivery 负责投递 `message` / `run_event` / `notice` / `operation_update`，不负责生成回复。
9. Final assistant reply 必须是 MessageService 持久化的 assistant message。
10. Streaming 必须走 RunEventLog + Delivery fan-out。
11. Tool 调度必须走 ToolRouter + ExecutionTarget。
12. 权限挂在 Actor / Workspace / RunPolicy；执行能力挂在 EndpointCapability。
13. `exec_core_cmd` 是显式 Core-host shell 例外，只能在 Core Service 主机执行，受 Core 白名单策略约束；`exec_sys_cmd` 仍代表 Endpoint shell。
14. 不保留 `/client/ws`、`source_client_id`、`target_client_id`、`ClientToolDispatchService` 兼容路径。

---

## 0. 设计结论

V4 采用以下架构原则：

1. **Core 不是 Client。** Core 是控制面和运行时；Core 可以在路由表中注册 `core.local`、`core.scheduler`、`core.inbox` 等 in-process endpoint / execution target，但这些不是 Client。
2. **Client 降级为 Endpoint Provider。** Desktop、Edge、Feishu、WeChatBot、Email、Webhook 都通过 Endpoint 暴露输入、输出或执行能力。
3. **Thread / Message / Run 全部归 Core。** Client 下线、重连、换设备，不影响 Thread 延续。
4. **Scheduler 是系统级调度时钟。** Heartbeat 不再是独立系统，而是 Scheduler 中一条不可删除、可启停、可改间隔的系统预设 Job。
5. **Client keepalive 和 system heartbeat 是两件事。** `endpoint.heartbeat` 只表示连接保活；`system.heartbeat` 表示 Core 自主定时任务。
6. **Tool 调度基于 ExecutionTarget。** 所有工具调用先解析为 `core.local` / `desktop.home.executor` / `edge.xxx.executor` / `external.feishu` 等执行目标，再由对应 executor 执行。
7. **Core-host shell 是显式例外。** `exec_core_cmd` 只在 Core Service 主机执行，固定 Core 进程工作目录并受 Core 白名单策略约束；本地文件、Workspace I/O、general shell 和 local MCP 仍走 Endpoint。
8. **Delivery 负责所有 Core -> Endpoint 的消息、事件、通知投递。** 它不负责生成回复；回复由 Run 产生，MessageService 持久化，DeliveryService 投递。
9. **`short_reply` 不再作为 directed tool。** 它被替换为 `assistant.progress_notice` 运行时事件，不进入 ToolRouter，不生成 Operation，不代表最终回复。
10. **开发期直接大换血。** 不保留 `/client/ws`、`source_client_id`、`target_client_id`、`ClientToolDispatchService` 等 V3 兼容路径。
11. **测试必须从本地基础测试推进到真实远程 Core、真实 Desktop、真实通知渠道。** 单元测试通过不是终点。

---

## 1. V3 痛点

V3 的主要问题不是“Client 不能执行工具”，而是 **Client 承担了过多语义**：

- `source_client_id` 同时承担输入来源、权限主体、回复目标。
- `target_client_id` 同时承担执行目标和连接目标。
- `available_tools` 挂在 Client 上，使“谁允许调用工具”被误绑定到某个端。
- `executable_tools` 挂在 Client 上，使“哪里能执行工具”被误绑定到 Client 实例。
- Thread 虽然在 Core 管理，但对话链路和工具链路仍然过度依赖 Client。
- Heartbeat 如果表示 AI 自主运行，则不应该依赖任何 Client 在线。
- 定时任务如果需要 `source_client_id`，就无法成为真正的 Core 后台任务。
- `short_reply` 作为 directed tool 容易被误认为模型回复链路，影响 Streaming、历史消息、多端同步和后台任务。

V4 的设计核心就是把这些语义拆开：

```text
Actor        = 谁发起 / 谁负责 / 谁拥有权限
Endpoint     = 从哪里输入 / 到哪里输出 / 可寻址目标
Run          = Core 管理的一次执行
Thread       = Core 管理的对话容器
Delivery     = Core 到 Endpoint 的消息和事件投递
ToolRouter   = 工具调用到 ExecutionTarget 的路由
Scheduler    = 系统级调度时钟
Heartbeat    = Scheduler 内置系统任务
```

---

## 2. V4 总体架构

```text
                                    ┌─────────────────────────────┐
                                    │            Core              │
                                    │─────────────────────────────│
                                    │ ActorService                 │
                                    │ EndpointRegistryService      │
                                    │ EndpointConnectionService    │
                                    │ ThreadService                │
                                    │ MessageService               │
                                    │ RunService                   │
                                    │ RunEventService              │
                                    │ DeliveryService              │
                                    │ ToolRouterService            │
                                    │ ExecutionTargetResolver      │
                                    │ OperationService             │
                                    │ SchedulerService             │
                                    │ HeartbeatWorkflow            │
                                    │ Memory / Context / Approval  │
                                    └──────────────┬──────────────┘
                                                   │
              ┌────────────────────────────────────┼────────────────────────────────────┐
              │                                    │                                    │
    ┌─────────▼─────────┐                ┌─────────▼─────────┐                ┌─────────▼─────────┐
    │ Core Endpoints     │                │ Desktop Provider   │                │ Edge Provider      │
    │───────────────────│                │───────────────────│                │───────────────────│
    │ core.local         │                │ desktop.ui         │                │ edge.executor      │
    │ core.scheduler     │                │ desktop.executor   │                │ edge.notifier      │
    │ core.inbox         │                │ desktop.notifier   │                │                   │
    └───────────────────┘                └───────────────────┘                └───────────────────┘
                                                   │
                                ┌──────────────────┴──────────────────┐
                                │                                     │
                      ┌─────────▼─────────┐                 ┌─────────▼─────────┐
                      │ External Provider  │                 │ Webhook Provider   │
                      │───────────────────│                 │───────────────────│
                      │ feishu.bot         │                 │ github.webhook     │
                      │ wechatbot.personal │                 │ http.callback      │
                      │ email.primary      │                 │                   │
                      └───────────────────┘                 └───────────────────┘
```

---

## 3. 核心概念

### 3.1 Actor

Actor 表示“谁发起 / 谁负责 / 谁拥有权限”。

推荐类型：

```text
user
system.scheduler
system.heartbeat
system.maintenance
automation
external.webhook
service_account
```

Actor 是权限主体，不是 Endpoint。一个用户可以从多个 Endpoint 进入；一个 Endpoint 也可能代表某个外部服务。

示例：

```json
{
  "actor_id": "user:mzt",
  "actor_type": "user",
  "owner_user_id": "mzt",
  "permission_profile_id": "profile.default_user"
}
```

```json
{
  "actor_id": "system.heartbeat",
  "actor_type": "system_heartbeat",
  "permission_profile_id": "profile.system_heartbeat"
}
```

### 3.2 Endpoint

Endpoint 是 Core 路由系统中的可寻址目标。Endpoint 不等于 Client，不等于 WebSocket，也不一定在线。

Operator 工作区拓扑是管理视图，不是 Endpoint 表的原始 dump。默认只展示在线 Provider 管理节点；Core 内部目标、断开的历史 Provider、Desktop/Edge 的 UI 角色，以及 retired/archived 隐藏节点不进入默认拓扑。诊断场景可以显式开启 `include_offline=true`、`include_system=true` 或 `include_archived=true`。

Endpoint 可以承担以下角色：

```text
input        用户或外部系统从这里进入 Core
output       Core 把消息、事件、通知投递到这里
execution    工具或动作在这里执行
database     持久化收件箱，例如 core.inbox
inproc       Core 内部执行目标，例如 core.local
```

推荐 Endpoint 示例：

```text
core.local
core.scheduler
core.inbox
core.notification

desktop.home.ui
desktop.home.executor
desktop.home.notifier

edge.server01.executor
edge.server01.notifier

feishu.personal_bot
wechatbot.personal
email.primary
webhook.github
```

Endpoint 关键字段：

```text
endpoint_id
endpoint_type
provider_type: core | desktop | edge | external | webhook
transport_type: inproc | websocket | http | adapter | database
owner_actor_id
workspace_ids
status
labels
priority
capabilities
```

### 3.3 ExecutionTarget

ExecutionTarget 是工具调用的最终执行目标。它可以是 Endpoint，也可以是内部 executor。

关键原则：**所有 tool call 都先解析成 ExecutionTarget。**

```text
ToolCall
  -> CapabilityResolver
  -> ExecutionTargetResolver
  -> Executor
```

Executor 类型：

```text
CoreToolExecutor       target = core.local, transport = inproc
EndpointToolExecutor   target = desktop/edge executor, transport = websocket
ExternalToolExecutor   target = feishu/email/http adapter, transport = adapter/http
```

这样就能解释 `core.local`：它不是 Client，而是 in-process execution target，用于统一策略、审计和 Operation 记录。

### 3.4 Thread

Thread 是 Core 中的对话容器，不依赖 Client。

```text
thread_id
workspace_id
owner_actor_id
title
mode
status
default_delivery_policy_id
created_at
updated_at
```

Client 下线重连后能继续 Thread，因为 Thread 和 Message 都在 Core 持久化。

### 3.5 Message

Message 是 Thread 中的持久化消息。

```text
message_id
thread_id
role: user | assistant | system | tool | notice
content
created_by_actor_id
origin_endpoint_id nullable
run_id nullable
status
created_at
```

最终 assistant 回复必须是 Message，不是 `short_reply`。

### 3.6 Run

Run 是 Core 管理的一次执行，可能由用户消息、定时任务、heartbeat、webhook 或手动重试触发。

```text
run_id
workspace_id
thread_id nullable
trigger_type: user_message | scheduled_job | system_heartbeat | webhook | manual | retry
origin_actor_id
origin_endpoint_id nullable
status: queued | running | waiting_for_approval | waiting_for_endpoint | succeeded | failed | cancelled
input
output
execution_policy
delivery_policy
created_at
started_at
finished_at
```

### 3.7 RunEvent

RunEvent 是 Run 执行过程中的事件流。它服务于 Streaming、进度、工具状态、多端同步和断线恢复。

常见类型：

```text
run.created
run.started
message.delta
message.completed
assistant.progress_notice
tool.call.created
tool.call.dispatched
tool.call.completed
tool.call.failed
approval.required
endpoint.waiting
delivery.sent
run.completed
run.failed
```

事件字段：

```text
event_id
run_id
thread_id nullable
seq
type
payload
durable: bool
created_at
```

### 3.8 Delivery

Delivery 是 Core -> Endpoint 的投递层。Delivery 不生成回复，只投递已经产生的 Message、RunEvent、Notice。

Delivery 适用范围：

```text
对话消息
模型 streaming delta
Run 状态更新
Tool / Operation 进度更新
通知 / 提醒
assistant.progress_notice
```

Delivery 不负责：

```text
LLM 生成
Tool 执行
Memory 写入
领域服务内部同步
```

### 3.9 Scheduler 与 Heartbeat

Scheduler 是系统级调度时钟。Heartbeat 是 Scheduler 中一条系统内置 Job。

```text
scheduled_jobs
- system.heartbeat     不可删除，可启停，可调间隔
- user.created.xxx     可创建、编辑、删除
- workflow.xxx         工作流定时触发
- maintenance.xxx      系统维护任务
```

Heartbeat 不再有独立调度器。

---

## 4. short_reply 的 V4 处理方式

### 4.1 最终决定

`short_reply` 在 V4 中不再作为 directed tool 存在。

替换为：

```text
assistant.progress_notice
```

这是 RunEvent 类型，不是 ToolCall，不经过 ToolRouter，不创建 OperationCall，不需要 target endpoint，不代表最终回复。

### 4.2 使用场景

适合：

```text
“我正在检查本地文件。”
“我需要调用桌面执行器。”
“我已经找到问题，正在生成修复方案。”
“这个操作需要你确认。”
```

不适合：

```text
最终 assistant 回复
Thread 历史消息
需要长期保存的结论
工具结果
```

### 4.3 事件格式

```json
{
  "type": "assistant.progress_notice",
  "durable": false,
  "payload": {
    "text": "我正在检查本地文件。",
    "severity": "info",
    "ttl_seconds": 60
  }
}
```

如果某些进度提示需要恢复或审计，可设置：

```json
{
  "durable": true,
  "retention": "short"
}
```

### 4.4 对模型的暴露方式

如果模型需要主动发进度提示，不要把它做成普通工具。推荐实现为 Runtime Action：

```text
emit_progress_notice(text: str, severity: str = "info")
```

Runtime Action 的处理逻辑：

```text
LLM runtime action
  -> RunEventService.append(type="assistant.progress_notice")
  -> DeliveryService.publish(event)
```

禁止：

```text
emit_progress_notice
  -> ToolRouter
  -> Operation
  -> Endpoint tool call
```

### 4.5 测试要求

必须有测试证明：

1. `short_reply` 不再出现在 directed tool registry。
2. `short_reply` 不再出现在 endpoint capabilities。
3. `emit_progress_notice` 不创建 Operation / OperationCall。
4. `assistant.progress_notice` 能被在线 UI 收到。
5. 最终 assistant 回复仍通过 Message 持久化。
6. Streaming delta 和 progress notice 可以交错出现，但最终消息内容不包含 progress notice 文本。

---

## 5. Scheduler + Heartbeat 统一设计

### 5.1 Scheduler 是唯一调度时钟

Scheduler 负责：

```text
cron trigger
interval trigger
manual trigger
retry trigger
event trigger 后续可扩展
misfire 处理
concurrency 控制
job run 创建
run 创建
```

### 5.2 system.heartbeat 是不可删除的系统 Job

```json
{
  "job_id": "system.heartbeat",
  "kind": "system_heartbeat",
  "singleton_key": "core.system.heartbeat",
  "enabled": true,
  "deletable": false,
  "editable_fields": [
    "enabled",
    "trigger_config.interval_seconds",
    "execution_policy.limits",
    "delivery_policy"
  ],
  "trigger_config": {
    "type": "interval",
    "every_seconds": 600
  },
  "action_ref": "core.workflow.heartbeat"
}
```

### 5.3 逻辑唯一，不等于执行实例唯一

推荐：

```text
system.heartbeat 定义全局唯一
每次 tick 可按 workspace / user scope fan-out
每个 scope 产生自己的 Heartbeat Run
```

避免把所有 workspace 混成一个巨型 heartbeat 上下文。

### 5.4 Heartbeat Run 流程

```text
Scheduler tick
  -> due job: system.heartbeat
  -> create JobRun
  -> create Run(trigger_type=system_heartbeat, actor=system.heartbeat)
  -> HeartbeatWorkflow inspect:
       pending runs
       waiting operations
       reminders
       memory signals
       schedule health
       endpoint status
  -> maybe create Message / Notice / Operation
  -> DeliveryService deliver
  -> mark Run / JobRun completed
```

---

## 6. Endpoint 协议

### 6.1 WebSocket 入口

V4 使用：

```text
GET /endpoint/ws
protocol = meetyou.endpoint.ws.v4
```

V3 的 `/client/ws` 删除，不做兼容。

### 6.2 连接生命周期帧

```text
endpoint.hello
endpoint.capabilities.snapshot
endpoint.ready
endpoint.heartbeat
endpoint.goodbye
```

`endpoint.heartbeat` 只表示连接保活，不触发系统 heartbeat。

### 6.3 订阅帧

```text
subscription.start
subscription.update
subscription.stop
```

订阅对象：

```text
thread
run
workspace inbox
operation
endpoint personal stream
```

### 6.4 Delivery 帧

```text
delivery.message
delivery.run_event
delivery.notice
delivery.operation_update
delivery.inbox_item
```

### 6.5 Tool 帧

```text
tool.call.request
tool.call.result
tool.call.error
tool.call.cancel
```

`tool.call.request` 发送给 execution endpoint；`delivery.*` 发送给 UI / notifier endpoint。两者不要混用。

---

## 7. ToolRouter 设计

### 7.1 新主链

```text
Run step wants tool_key
  -> Policy check: Actor + Workspace + RunPolicy
  -> CapabilityResolver resolves abstract tool_key
  -> ExecutionTargetResolver chooses target
  -> ApprovalService if needed
  -> OperationService creates Operation / OperationCall
  -> Executor dispatches:
       core.local       -> CoreToolExecutor
       desktop/edge     -> EndpointToolExecutor via websocket
       external service -> ExternalAdapter
  -> result returns
  -> RunEvent + OperationCall update
  -> Run continues
```

### 7.2 权限与能力拆分

V3：

```text
Client.available_tools
Client.executable_tools
```

V4：

```text
Actor / Workspace / RunPolicy.allowed_tools
EndpointCapability.executable_tools
```

### 7.3 target selector

支持固定 endpoint：

```json
{
  "endpoint_id": "desktop.home.executor"
}
```

支持 selector：

```json
{
  "selector": {
    "workspace_id": "personal",
    "capability": "file.write",
    "endpoint_type": "desktop_executor",
    "labels": ["trusted"],
    "online_required": true,
    "priority": ["desktop.home.executor", "edge.server01.executor"]
  }
}
```

### 7.4 离线策略

支持：

```text
fail_fast
queue_until_online
store_in_outbox
fallback_to_core
manual_retry
```

后台任务遇到执行 endpoint 离线时，不一定失败，可以进入：

```text
waiting_for_endpoint
```

---

## 8. Delivery 与 Streaming

### 8.1 非流式消息

```text
Run final output
  -> MessageService.create(role=assistant)
  -> RunEventService.append(message.completed)
  -> DeliveryService.deliver(delivery.message)
```

### 8.2 流式响应

```text
LLMAdapter stream token
  -> RunService receives delta
  -> RunEventService.append(type=message.delta, seq=n)
  -> DeliveryService fan-out to subscribed endpoints
  -> MessageService persists final assistant message at completion
```

### 8.3 断线恢复

Endpoint 重连时发送：

```json
{
  "type": "subscription.start",
  "thread_id": "thread_xxx",
  "last_seen_event_seq": 42
}
```

Core：

```text
如果 durable events 存在，补发 seq > 42
否则返回 thread final messages + current run status
```

### 8.4 Delivery Policy

示例：

```json
{
  "targets": [
    {"selector": "origin_endpoint", "when": "exists"},
    {"selector": "user.primary_endpoint"},
    {"endpoint_id": "core.inbox", "required": true}
  ],
  "offline_policy": "store_and_retry"
}
```

定时任务没有用户输入 origin endpoint 时，不能把消息发给 `core.scheduler`，而应按 policy 发给 `core.inbox`、用户主 endpoint 或外部通知渠道。

---

## 9. 数据模型建议

### 9.1 actors

```text
id
actor_id
actor_type
owner_user_id nullable
display_name
permission_profile_id
metadata
created_at
updated_at
```

### 9.2 endpoints

```text
id
endpoint_id
endpoint_type
provider_type
transport_type
owner_actor_id nullable
workspace_scope
status
labels
priority
metadata
created_at
updated_at
```

### 9.3 endpoint_connections

```text
id
connection_id
endpoint_id
transport
protocol_version
status
last_seen_at
remote_addr
subscriptions
capability_snapshot
created_at
updated_at
```

### 9.4 endpoint_capabilities

```text
id
endpoint_id
capability_id
tool_key
schema
risk_level
requires_confirmation
enabled
constraints
created_at
updated_at
```

### 9.5 threads

```text
id
thread_id
workspace_id
owner_actor_id
title
mode
status
default_delivery_policy_id
metadata
created_at
updated_at
```

### 9.6 messages

```text
id
message_id
thread_id
run_id nullable
role
content
content_type
created_by_actor_id nullable
origin_endpoint_id nullable
status
metadata
created_at
updated_at
```

### 9.7 runs

```text
id
run_id
workspace_id
thread_id nullable
trigger_type
origin_actor_id
origin_endpoint_id nullable
status
input
output
execution_policy
delivery_policy
metadata
created_at
started_at
finished_at
```

### 9.8 run_events

```text
id
event_id
run_id
thread_id nullable
seq
type
payload
durable
created_at
```

### 9.9 scheduled_jobs

```text
id
job_id
workspace_id nullable
kind
singleton_key nullable
name
enabled
deletable
editable_fields
trigger_type
trigger_config
timezone
action_ref
run_template
execution_policy
delivery_policy
concurrency_policy
misfire_policy
created_at
updated_at
```

### 9.10 scheduled_job_runs

```text
id
job_run_id
job_id
run_id nullable
scheduled_at
started_at
finished_at
status
error
metadata
created_at
updated_at
```

### 9.11 operations / operation_calls

Operation 继续存在，但 target 字段改为 endpoint / execution target：

```text
operation.execution_target_type
operation.execution_target_id
operation.requested_by_actor_id
operation.requested_by_run_id
```

OperationCall：

```text
call_id
operation_id
capability_id
target_endpoint_id nullable
execution_target_id
status
arguments
result
error
created_at
updated_at
```

### 9.12 endpoint_outbox

```text
id
outbox_id
target_endpoint_id
message_type
payload
status
available_at
attempt_count
last_error
created_at
updated_at
```

---

## 10. 典型流程

### 10.1 用户从 Desktop 发起对话

```text
desktop.home.ui -> /endpoint/ws
  -> endpoint.hello / ready
  -> user sends message
  -> MessageService creates user message
  -> RunService creates Run(trigger=user_message, actor=user:mzt, origin_endpoint=desktop.home.ui)
  -> LLM stream
  -> message.delta events delivered to desktop.home.ui
  -> tool needed: file.read
  -> ToolRouter selects desktop.home.executor
  -> OperationCall dispatched
  -> result returns
  -> assistant final Message persisted
  -> DeliveryService sends delivery.message
```

### 10.2 Client 下线重连继续 Thread

```text
Desktop disconnects
  -> EndpointConnection status offline
  -> Thread remains in Core
  -> Run may continue if not dependent on offline endpoint
  -> events are durable / final message persisted
Desktop reconnects
  -> endpoint.hello
  -> list threads
  -> subscription.start(thread_id, last_seen_event_seq)
  -> Core replay / snapshot
```

### 10.3 system.heartbeat

```text
Scheduler tick
  -> due: system.heartbeat
  -> JobRun
  -> Run(trigger=system_heartbeat, actor=system.heartbeat, origin_endpoint=core.scheduler)
  -> HeartbeatWorkflow inspects system state
  -> no-op or create Message / Notice / Operation
  -> Delivery to core.inbox / user primary endpoint / external notifier
```

### 10.4 用户定时任务

```text
Scheduler tick
  -> due: user job
  -> JobRun
  -> Run(trigger=scheduled_job, actor=system.scheduler)
  -> execute workflow
  -> tools via core.local or endpoint selector
  -> final message saved to configured thread
  -> Delivery policy sends results
```

---

## 11. 权限设计

权限检查顺序：

```text
1. Actor 是否允许发起该 Run / Tool
2. Workspace policy 是否允许该 tool_key
3. RunPolicy 是否允许当前步骤
4. Capability 是否存在且 enabled
5. ExecutionTarget 是否满足 workspace / label / owner / online 策略
6. Risk policy 是否需要 approval
7. Credential policy 是否允许传输敏感参数
```

禁止把权限继续挂在 source Client 上。

---

## 12. V4 不保留兼容的删除清单

需要删除或替换：

```text
/client/ws
meetyou.client.ws.v1
client.hello
client.ready
client.heartbeat 作为协议名
client.tools.snapshot
source_client_id
target_client_id
available_tools on Client as permission subject
executable_tools on Client as execution subject
ClientToolDispatchService
short_reply directed tool
endpoint notice routed to source client 的默认策略
```

替换为：

```text
/endpoint/ws
meetyou.endpoint.ws.v4
endpoint.hello
endpoint.ready
endpoint.heartbeat
endpoint.capabilities.snapshot
origin_endpoint_id
target_endpoint_id / execution_target_id
Actor / Workspace / RunPolicy allowed_tools
EndpointCapabilities
ToolRouterService
assistant.progress_notice RunEvent
DeliveryPolicy
```

---

## 13. 文档与 AGENT.md 对齐要求

V4 实现前必须更新：

```text
AGENT.md / AGENTS.md
README.md
docs/v4/meetyou-v4-design.md
docs/v4/meetyou-v4-scheduled-workflows.md
docs/v4/endpoint-provider-template.md
user/*.example.json
```

AGENT.md 必须写入 V4 不可违反原则：

```text
Core owns Thread / Run / Scheduler / Heartbeat.
Client is only Endpoint Provider.
No /client/ws compatibility.
No source_client_id / target_client_id in new code.
short_reply is replaced by assistant.progress_notice.
Scheduler owns system.heartbeat as non-deletable job.
Delivery handles message/event/notice transport, not generation.
Tests must progress from local base tests to remote real tests.
Feishu and WeChatBot tests are last and require human feedback through question tool.
Do not stop after base tests.
```

---

## 14. 成功标准

V4 完成时必须满足：

1. 本地 Core 使用 `/endpoint/ws` 接受 Desktop / Edge 连接。
2. Thread 在 Core 持久化，Desktop 下线重连可继续原 Thread。
3. Run 可由用户消息、Scheduler、system.heartbeat、manual trigger 创建。
4. system.heartbeat 是不可删除、可启停、可调间隔的 scheduled job。
5. 用户定时任务可创建、启停、编辑、删除。
6. Core tools 通过 `core.local` in-process ExecutionTarget 执行。
7. Desktop / Edge tools 通过 endpoint execution target 执行。
8. Delivery 能投递 message、run_event、notice、operation_update。
9. Streaming 通过 RunEvent + Delivery 实现。
10. `short_reply` 不再作为 directed tool；progress notice 正常显示。
11. 本地基础测试、真实本地测试、远程 CI、远程 Deploy、真实 Desktop 连接远程 Core 全部通过。
12. Feishu / WeChatBot 在最后完成真实投递测试，并通过人类反馈确认。
