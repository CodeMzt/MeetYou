# Endpoint Protocol V4

本文件取代旧 Agent protocol 说明。V4 不再使用 `/agent/ws` 作为正式主链。

## Transport

- WebSocket: `GET /endpoint/ws`
- Protocol: `meetyou.endpoint.ws.v4`
- Auth: 按部署配置使用 `Authorization: Bearer ...` 或 `X-API-Key`

## Provider Lifecycle

Endpoint Provider 连接后按顺序完成：

1. `endpoint.hello`
2. Core 返回连接确认
3. `endpoint.capabilities.snapshot`
4. `endpoint.ready`
5. 周期性 `endpoint.heartbeat`
6. 断开前可发送 `endpoint.goodbye`

`endpoint.heartbeat` 只表示连接保活，不触发系统心跳。

## Subscriptions

Endpoint Provider 可订阅 Thread、Run 或其他投递目标：

- `subscription.start`
- `subscription.update`
- `subscription.stop`

断线重连后应重新声明能力和订阅，Core 根据 Thread / Run / Delivery 状态继续 fan-out。

## Delivery Frames

- `delivery.message`
- `delivery.run_event`
- `delivery.notice`
- `delivery.operation_update`
- `delivery.inbox_item`

Delivery frame 只投递已由 Core 产生或持久化的事件，不生成 assistant 内容。

## Tool Frames

- `tool.call.request`
- `tool.call.result`
- `tool.call.error`
- `tool.call.cancel`

工具调用必须先由 ToolRouter 解析 ExecutionTarget，再由 Endpoint Provider 执行被分配给自身的请求。

## Removed

以下旧协议不属于 V4：

- `/agent/ws`
- `/client/ws`
- Client-owned permission
- Client-owned executable capability
- `source_client_id`
- `target_client_id`
