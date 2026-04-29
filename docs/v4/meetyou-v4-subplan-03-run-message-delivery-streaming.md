# V4 细分计划 03：Run / Message / Delivery / Streaming / progress_notice

## 目标

建立 Core-owned conversation runtime。所有对话消息、流式响应、进度提示、Run 状态、工具进度和通知都通过 RunEvent + Message + Delivery 统一管理。

---

## 核心原则

1. Run 负责执行生命周期。
2. Message 负责 Thread 持久化消息。
3. RunEvent 负责执行过程事件流和 streaming。
4. Delivery 负责把 Message / RunEvent / Notice 投递给 Endpoint。
5. Delivery 不生成回复。
6. `short_reply` 删除，替换为 `assistant.progress_notice`。

---

## 服务

新增 / 重构：

```text
ThreadService
MessageService
RunService
RunEventService
DeliveryService
DeliveryPolicyService
EndpointOutboxService
SubscriptionService
```

---

## Run 生命周期

```text
queued
running
waiting_for_approval
waiting_for_endpoint
succeeded
failed
cancelled
```

Run 创建来源：

```text
user_message
scheduled_job
system_heartbeat
webhook
manual
retry
```

---

## Streaming 设计

### 事件流

```text
run.created
run.started
message.delta
assistant.progress_notice
tool.call.created
tool.call.dispatched
tool.call.completed
message.completed
run.completed
```

### message.delta

```json
{
  "type": "message.delta",
  "durable": true,
  "payload": {
    "message_id": "msg_assistant_001",
    "delta": "你好",
    "index": 0
  }
}
```

### final message

```text
LLM streaming complete
  -> MessageService.create(role=assistant, content=full_text)
  -> RunEventService.append(type=message.completed)
  -> DeliveryService.deliver(delivery.message)
```

---

## short_reply 替换方案

### 删除

删除 directed tool：

```text
short_reply
client.<client_id>.short_reply
```

从以下位置移除：

```text
tools schema
endpoint capabilities
prompt tool instructions
tool registry
ClientToolDispatchService replacement paths
tests expecting short_reply tool call
```

### 新增 Runtime Action

```text
emit_progress_notice(text: str, severity: str = "info", ttl_seconds: int = 60)
```

内部实现：

```text
RunEventService.append(
  type="assistant.progress_notice",
  durable=false,
  payload={text, severity, ttl_seconds}
)
DeliveryService.publish(event)
```

### 禁止

```text
emit_progress_notice -> ToolRouter
emit_progress_notice -> Operation
emit_progress_notice -> OperationCall
assistant.progress_notice -> Message final content
```

---

## DeliveryPolicy

默认用户对话：

```json
{
  "targets": [
    {"selector": "origin_endpoint", "when": "exists"},
    {"endpoint_id": "core.inbox", "required": true}
  ],
  "offline_policy": "store_and_retry"
}
```

默认定时任务：

```json
{
  "targets": [
    {"endpoint_id": "core.inbox", "required": true},
    {"selector": "user.primary_endpoint", "required": false}
  ],
  "offline_policy": "store_and_retry"
}
```

默认 heartbeat：

```json
{
  "targets": [
    {"endpoint_id": "core.inbox", "required": true}
  ],
  "notify_when": "important_only",
  "offline_policy": "store_and_retry"
}
```

---

## 断线恢复

Endpoint 重连后：

```text
subscription.start(thread_id, last_seen_event_seq)
```

Core：

```text
1. 校验 endpoint 是否有 workspace/thread 权限
2. 查询 durable run_events seq > last_seen_event_seq
3. 补发 delivery.run_event
4. 返回当前 active runs snapshot
5. 开始 live fan-out
```

---

## 测试

### Unit

- RunEvent seq 单调递增。
- durable / transient 事件区分。
- Message final 持久化。
- DeliveryPolicy 解析。
- Outbox 创建和重试。

### Integration

- 创建 Thread -> user message -> Run -> streaming delta -> final message。
- Endpoint 订阅后收到 delta。
- Endpoint 断线重连后恢复。
- No origin endpoint 的 scheduled run 不投递给 core.scheduler。

### short_reply / progress_notice

- grep 确认 `short_reply` 不在 tool schema。
- runtime action 产生 `assistant.progress_notice`。
- `assistant.progress_notice` 在线可见。
- final assistant message 不包含 progress_notice。
- progress_notice 不创建 OperationCall。

---

## 真实测试

1. 本地启动 Core。
2. 本地启动 Desktop UI。
3. 创建 Thread。
4. 发送一个会 streaming 的问题。
5. 确认 UI 逐步显示 delta。
6. 触发一个长任务，确认 progress_notice 短提示显示。
7. 确认最终回复进入 Thread 历史。
8. 断开 Desktop，再重连，确认 Thread 和最终消息仍在。

---

## 验收

- [x] Streaming 走 RunEvent。
- [x] Final reply 走 Message。
- [x] Delivery 统一投递。
- [x] short_reply 删除。
- [x] assistant.progress_notice 工作正常。
- [x] 断线恢复可用。
