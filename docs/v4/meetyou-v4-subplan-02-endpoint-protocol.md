# V4 细分计划 02：Endpoint Protocol / Gateway / Connection

## 目标

用 `/endpoint/ws` 和 `meetyou.endpoint.ws.v4` 替换 V3 的 `/client/ws` 和 `meetyou.client.ws.v1`。Client 概念降级为 Endpoint Provider；Desktop、Edge 和外部 adapter 都通过 Endpoint 与 Core 交互。

---

## 协议入口

新增：

```text
GET /endpoint/ws
protocol = meetyou.endpoint.ws.v4
```

删除或禁用：

```text
GET /client/ws
protocol = meetyou.client.ws.v1
```

如果保留旧入口用于报错，应返回：

```text
410 Gone
message: /client/ws is removed in V4. Use /endpoint/ws.
```

不要实现兼容 adapter。

---

## Frame 类型

### 生命周期

```text
endpoint.hello
endpoint.capabilities.snapshot
endpoint.ready
endpoint.heartbeat
endpoint.goodbye
```

`endpoint.heartbeat` 只更新连接状态：

```text
last_seen_at
status
load / health optional
capability fingerprint optional
```

不得触发 system heartbeat。

### 订阅

```text
subscription.start
subscription.update
subscription.stop
```

订阅对象：

```text
thread
run
workspace_inbox
operation
endpoint_personal_stream
```

### 投递

```text
delivery.message
delivery.run_event
delivery.notice
delivery.operation_update
delivery.inbox_item
```

### 工具调用

```text
tool.call.request
tool.call.result
tool.call.error
tool.call.cancel
```

---

## endpoint.hello 示例

```json
{
  "type": "endpoint.hello",
  "protocol": "meetyou.endpoint.ws.v4",
  "provider": {
    "provider_type": "desktop",
    "provider_id": "home-pc",
    "display_name": "Home PC"
  },
  "endpoints": [
    {
      "endpoint_id": "desktop.home-pc.ui",
      "endpoint_type": "desktop_ui",
      "roles": ["input", "output"],
      "workspace_ids": ["personal"]
    },
    {
      "endpoint_id": "desktop.home-pc.executor",
      "endpoint_type": "desktop_executor",
      "roles": ["execution"],
      "workspace_ids": ["personal"]
    }
  ]
}
```

---

## endpoint.capabilities.snapshot 示例

```json
{
  "type": "endpoint.capabilities.snapshot",
  "endpoint_id": "desktop.home-pc.executor",
  "capabilities": [
    {
      "tool_key": "file.read",
      "risk_level": "read",
      "requires_confirmation": false,
      "schema": {}
    },
    {
      "tool_key": "shell.exec",
      "risk_level": "system",
      "requires_confirmation": true,
      "schema": {}
    }
  ]
}
```

---

## subscription.start 示例

```json
{
  "type": "subscription.start",
  "subscription_id": "sub_123",
  "target_type": "thread",
  "target_id": "thread_abc",
  "last_seen_event_seq": 42
}
```

Core 返回：

```text
subscription.ack
then replay durable run_events seq > 42
then live delivery.* frames
```

---

## 服务实现

新增 / 重构：

```text
GatewayEndpointWebSocket
EndpointConnectionService
EndpointRegistryService
EndpointCapabilityService
SubscriptionService
EndpointTransportService
```

删除 / 替换：

```text
EndpointService as runtime identity owner
Endpoint connection manager
/endpoint/ws gateway handler
endpoint_tool_sdk frame names
```

`endpoint_tool_sdk` 是新的 Endpoint protocol / runtime SDK 入口。V4 不保留 `client_tool_sdk` / `client_tool_protocol.py` 作为运行时兼容层。

```text
endpoint_protocol_sdk
```

---

## 测试

### 基础协议测试

- 正常连接 `/endpoint/ws`。
- `endpoint.hello` 创建 / 更新 endpoints。
- `endpoint.capabilities.snapshot` 更新 capabilities。
- `endpoint.ready` 标记 ready。
- `endpoint.heartbeat` 更新 last_seen。
- `endpoint.goodbye` 标记 disconnected。

### 旧入口测试

- `/client/ws` 返回 410 / 404。
- 不存在任何自动转发到 `/endpoint/ws` 的兼容逻辑。

### 订阅测试

- endpoint 订阅 thread。
- DeliveryService 发布 run_event。
- endpoint 收到 `delivery.run_event`。
- endpoint 断开重连后按 seq replay。

---

## 验收

- [x] `/endpoint/ws` 可用。
- [x] `/client/ws` 不可作为 V4 入口使用。
- [x] Desktop / Edge 使用 endpoint frames。
- [x] endpoint.heartbeat 只做 keepalive。
- [x] EndpointCapabilities 写入 DB。
- [x] Subscription 能接收 run/message events。
