# MeetYou 接口文档

## 1. 总览

MeetYou 当前对外与跨模块扩展统一基于事件协议工作：

- 入站统一为 `InboundEvent`
- 出站统一为 `OutboundEvent`
- 外部网关当前采用：
  - HTTP 入站
  - WebSocket 出站 + 控制命令回传
- 飞书 Bot 通过长连接接收消息，再映射为统一事件

本文档面向：

- 前端开发
- 渠道接入开发
- Bot/IM 适配器开发
- 二次网关开发

## 2. 核心概念

### 2.1 会话

系统采用“每来源独立会话”模型：

- CLI：`cli:local`
- Heart：`system:heart`
- Web：由 `session_id` 或 `source_id` 绑定
- 飞书：`feishu:chat:<chat_id>`

`session_id` 是所有输入输出协议的一等字段，前端和渠道适配器必须保留并传递。

### 2.2 来源与目标

来源 `source` 描述消息从哪里来，目标 `target` 描述消息要到哪里去。

#### source.kind

- `cli`
- `heart`
- `feishu`
- `web`
- `system`

#### target.kind

- `current_session`
- `cli`
- `feishu`
- `web`
- `broadcast`
- `internal`

### 2.3 事件类型

- `message`
- `signal`
- `confirm_request`
- `confirm_response`
- `status`
- `control`
- `error`

### 2.4 流式阶段

当输出为流式生成时，`metadata.stream_event` 与 WebSocket `stream.phase` 会出现以下值：

- `start`
- `chunk`
- `end`
- `error`

## 3. 统一事件结构

### 3.1 InboundEvent

```json
{
  "event_id": "string",
  "session_id": "string",
  "type": "message",
  "role": "user",
  "content": "你好",
  "source": {
    "kind": "web",
    "id": "browser-01",
    "display_name": "",
    "metadata": {}
  },
  "target": {
    "kind": "current_session",
    "id": "",
    "metadata": {}
  },
  "stream_id": "",
  "reply_to": "",
  "metadata": {}
}
```

### 3.2 OutboundEvent

```json
{
  "event_id": "string",
  "session_id": "string",
  "type": "message",
  "role": "assistant",
  "content": "你好，我在。",
  "source": {
    "kind": "system",
    "id": "brain",
    "display_name": "",
    "metadata": {}
  },
  "target": {
    "kind": "web",
    "id": "browser-01",
    "metadata": {}
  },
  "stream_id": "string",
  "reply_to": "",
  "metadata": {
    "stream_event": "chunk"
  }
}
```

### 3.3 ConfirmRequestEvent

```json
{
  "event_id": "string",
  "session_id": "feishu:chat:oc_xxx",
  "type": "confirm_request",
  "role": "system",
  "content": "请求执行危险命令: shutdown /s /t 0",
  "source": {
    "kind": "system",
    "id": "confirm",
    "display_name": "",
    "metadata": {}
  },
  "target": {
    "kind": "current_session",
    "id": "",
    "metadata": {}
  },
  "stream_id": "",
  "reply_to": "",
  "metadata": {},
  "confirm": {
    "request_id": "string",
    "timeout": 30.0,
    "default_decision": false
  }
}
```

### 3.4 ConfirmResponseEvent

```json
{
  "event_id": "string",
  "session_id": "feishu:chat:oc_xxx",
  "type": "confirm_response",
  "role": "user",
  "content": "确认",
  "source": {
    "kind": "feishu",
    "id": "oc_xxx",
    "display_name": "",
    "metadata": {}
  },
  "target": {
    "kind": "internal",
    "id": "",
    "metadata": {}
  },
  "stream_id": "",
  "reply_to": "",
  "metadata": {},
  "confirm": {
    "request_id": "string",
    "accepted": true
  }
}
```

## 4. HTTP 接口

### 4.1 POST /inputs

用途：提交用户文本输入。

#### 请求体

```json
{
  "content": "帮我总结今天的日志",
  "session_id": "web:session:001",
  "source_id": "browser-tab-a",
  "role": "user",
  "metadata": {
    "page": "dashboard"
  }
}
```

#### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `content` | string | 是 | 用户输入文本 |
| `session_id` | string \| null | 否 | 指定已有会话；为空时自动创建或绑定 |
| `source_id` | string | 否 | 外部来源标识，默认 `web-client` |
| `role` | string | 否 | 默认 `user` |
| `metadata` | object | 否 | 外部附加元数据 |

#### 响应

```json
{
  "accepted": true,
  "session_id": "web:session:001",
  "event_id": "string"
}
```

### 4.2 GET /health

用途：网关健康检查。

#### 响应

```json
{
  "status": "ok"
}
```

### 4.3 GET /config

用途：读取全部受管配置快照。

#### 响应

```json
{
  "items": {
    "api_provider": {
      "key": "api_provider",
      "value": "openai",
      "is_secret": false,
      "has_value": true,
      "source": "config",
      "env_key": null
    },
    "api_key": {
      "key": "api_key",
      "value": "sk**********yz",
      "is_secret": true,
      "has_value": true,
      "source": "env",
      "env_key": "MEETYOU_API_KEY"
    }
  }
}
```

说明：

- 密钥字段不会返回明文，只返回掩码值与来源信息。
- 当前受管范围包含 `user/config.json` 与项目 `.env`。

### 4.4 GET /config/{key}

用途：读取单项配置。

#### 响应

```json
{
  "key": "api_provider",
  "value": "openai",
  "is_secret": false,
  "has_value": true,
  "source": "config",
  "env_key": null
}
```

### 4.5 PATCH /config

用途：批量更新配置，并返回热更新结果。

#### 请求体

```json
{
  "updates": {
    "api_provider": "anthropic",
    "api_key": "new-secret"
  }
}
```

#### 响应

```json
{
  "applied_keys": ["api_provider", "api_key"],
  "reloaded_components": ["brain"],
  "restart_required_keys": [],
  "warnings": []
}
```

字段说明：

- `applied_keys`：本次已写入的配置项
- `reloaded_components`：已在运行中热更新的组件
- `restart_required_keys`：已持久化但仍需重启 gateway 的配置项
- `warnings`：弃用提示、未知配置项跳过提示等

## 5. WebSocket 接口

### 5.1 连接地址

```text
GET /ws?session_id=<session_id>&source_id=<source_id>
```

### 5.2 连接成功消息

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "connection",
  "connection": {
    "session_id": "web:session:001",
    "source_id": "browser-tab-a",
    "status": "connected"
  }
}
```

### 5.3 出站事件包

服务端向前端发送的统一格式如下：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "event",
  "event": {
    "event_id": "string",
    "session_id": "string",
    "type": "message|status|confirm_request|error",
    "role": "assistant|system|user",
    "content": "string|object",
    "source": {
      "kind": "system",
      "id": "brain",
      "display_name": "",
      "metadata": {}
    },
    "target": {
      "kind": "web",
      "id": "browser-tab-a",
      "metadata": {}
    },
    "stream_id": "string",
    "reply_to": "",
    "metadata": {
      "stream_event": "chunk"
    }
  },
  "stream": {
    "id": "string",
    "phase": "start|chunk|end|error"
  },
  "confirm": {}
}
```

### 5.4 WebSocket 命令

客户端当前支持以下入站命令。

#### ping

```json
{
  "action": "ping"
}
```

响应：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "pong"
}
```

#### confirm_response

```json
{
  "action": "confirm_response",
  "request_id": "string",
  "accepted": true,
  "metadata": {
    "from": "confirm-dialog"
  }
}
```

成功响应：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "ack",
  "ack": {
    "action": "confirm_response",
    "request_id": "string"
  }
}
```

失败响应：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "error",
  "error": {
    "code": "invalid_confirm_response",
    "message": "request_id 和 accepted 为必填字段"
  }
}
```

## 6. 前端处理建议

### 6.1 流式渲染

前端应按 `stream.id` 聚合同一轮生成：

- `phase = start`：创建新输出容器
- `phase = chunk`：向容器追加文本
- `phase = end`：结束本轮流式输出
- `phase = error`：标记该轮输出失败

### 6.2 确认弹窗

当收到：

- `kind = event`
- `event.type = confirm_request`

前端应：

1. 读取 `confirm.request_id`
2. 展示确认内容 `event.content`
3. 用户点击确认/拒绝后，发送 `confirm_response`

### 6.3 错误处理

当收到：

- `kind = error`

前端应按 `error.code` 显示合适提示，不应直接中断 WebSocket 连接。

## 7. 飞书渠道协议约定

### 7.1 入站

飞书消息事件接入后会映射为：

- `source.kind = feishu`
- `source.id = chat_id`
- `session_id = feishu:chat:<chat_id>`

系统会在首次收到飞书会话消息时，自动把 `chat_id` 持久化到 `user/feishu_chat_ids.json`。可通过配置项 `feishu_chat_registry_path` 修改保存位置。

### 7.2 出站

输出默认发送回该 `chat_id`。

如果希望应用启动时的广播欢迎消息主动发到飞书，而不是等飞书先来消息建立会话，需要在配置中提供：

- `feishu_broadcast_chat_ids`
- 或 `feishu_default_chat_id`

流式输出当前采用：

- 接收 `start` 时初始化缓冲
- 接收 `chunk` 时追加缓冲
- 接收 `end` 时一次性发送完整文本

### 7.3 确认回传

飞书侧确认规则：

- 认可：`y` / `yes` / `确认` / `同意` / `允许`
- 拒绝：`n` / `no` / `拒绝` / `取消` / `不同意`

仅当：

- 当前存在待确认请求
- 飞书会话 `session_id` 与待确认会话一致

该文本才会被解释为确认响应，否则仍按普通消息处理。

## 8. 广播规则

应用启动时，Brain 的欢迎回复使用广播目标发送。

当前广播规则：

1. 优先广播到 `SessionManager` 当前已登记的所有默认输出目标
2. 若还没有会话绑定，则退化为广播到已注册适配器类型

这意味着：

- CLI 启动时一定能收到欢迎输出
- 已连接的 WebSocket 会收到广播
- 已建立会话绑定的飞书会话会收到广播
- 若想在“首次还未收到飞书消息之前”就主动广播到飞书，需要通过配置预注册飞书目标 chat_id

## 9. 兼容性说明

- 旧 `Listener` 实现已移除
- 旧 `sensory_queue` 兼容入口已移除
- 新接入方必须走统一事件模型与 `inbound_queue`

## 10. 后续扩展建议

建议新增渠道或前端时遵循以下顺序：

1. 先确定 `source.kind` 与 `session_id` 映射规则
2. 再确定该渠道的默认 `target.kind`
3. 实现确认事件的完整回传
4. 最后再扩展富文本、卡片或附件能力
