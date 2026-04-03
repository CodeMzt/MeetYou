# MeetYou Interface

本文档描述当前 `gateway` 对外暴露的 HTTP / WebSocket 协议。

本版协议已经完成以下能力：

- 思考参数透传与独立 `reasoning` 流
- 会话级运行状态快照
- token / context 使用统计
- 官方 OpenAI 与 OpenAI-compatible 的分流约定

## 1. General Rules

### 1.1 Session Scope

- `session_id`: 一次持续对话的唯一标识
- `source_id`: 输入来源标识，例如 `browser-tab-a`、`desktop-app`
- `POST /inputs` 不传 `session_id` 时，网关会自动创建
- `GET /ws` 建议始终传稳定的 `source_id`

### 1.2 WebSocket Envelope

所有 WebSocket 消息统一带：

```json
{
  "schema": "meetyou.ws.v1"
}
```

同一轮对话的流式事件统一带：

- `metadata.turn_id`
- `stream.id`
- `stream.phase`: `start | chunk | end | error`
- `stream.channel`: `answer | reasoning`

### 1.3 Event Semantics

- `message`: 只承载正式回答正文
- `reasoning`: 只承载独立思考流
- `status`: 只承载工具链 / 搜索 / 系统提示
- `runtime_status`: 运行状态快照
- `usage`: token 与上下文使用快照

旧的“把 `status` 当作正文流边界”语义已经移除，当前协议以本文件为唯一标准。

## 2. Provider Notes

### 2.1 Official OpenAI

当 `api_provider = openai` 且 host 为 `api.openai.com` 时：

- 网关统一走官方 `Responses API`
- 即使配置写的是 `/v1/chat/completions`，运行时也会归一化到 `/v1/responses`
- `gpt-5.4-nano` 作为合法官方模型处理
- thinking 参数映射到 `reasoning.effort`
- `reasoning` 对外表示官方 reasoning summary 流，不表示原始 chain-of-thought

### 2.2 OpenAI-Compatible

非官方 host 继续走 chat-completions 兼容路径：

- 保持 `messages` / `tools` 形状
- reasoning 透传采用 best-effort
- 私有字段例如 `reasoning_content` 只在兼容路径解析

## 3. HTTP APIs

### 3.1 `GET /health`

```json
{
  "status": "ok"
}
```

### 3.2 `POST /inputs`

提交用户输入。

请求体：

```json
{
  "content": "帮我总结今天的工作",
  "session_id": "web:session:001",
  "source_id": "browser-tab-a",
  "client_message_id": "web-1712076000000-a1b2c3d4",
  "role": "user",
  "metadata": {
    "page": "chat"
  },
  "options": {
    "thinking": {
      "enabled": true,
      "effort": "high",
      "budget_tokens": 1024
    }
  }
}
```

字段：

- `content`: 必填，输入文本
- `session_id`: 选填，会话 id
- `source_id`: 选填，默认 `web-client`
- `role`: 选填，默认 `user`
- `metadata`: 选填，附加元数据
- `options.thinking.enabled`: 选填，是否启用 thinking
- `options.thinking.effort`: 选填，`low | medium | high`
- `options.thinking.budget_tokens`: 选填，provider 支持时透传

合并规则：

- `/config` 中的 `thinking_enabled` / `thinking_effort` / `thinking_budget_tokens` 作为默认值
- `POST /inputs.options` 作为单次覆盖值
- 合并结果传到 `App -> Brain -> Adapter`

响应：

```json
{
  "accepted": true,
  "session_id": "web:session:001",
  "event_id": "string"
}
```

幂等说明：
- `client_message_id` 为可选客户端消息 id。
- 同一 `(session_id, source_id, client_message_id)` 只会入队一次，并返回首次受理时的 `event_id`。

### 3.3 `GET /config`

获取全部受管配置快照。

与 thinking 相关的配置键：

- `thinking_enabled`
- `thinking_effort`
- `thinking_budget_tokens`

### 3.4 `GET /config/{key}`

获取单项配置。

### 3.5 `PATCH /config`

批量更新配置并触发热刷新。

示例：

```json
{
  "updates": {
    "thinking_enabled": true,
    "thinking_effort": "medium",
    "thinking_budget_tokens": 2048
  }
}
```

### 3.6 `GET /memory`

读取记忆快照。

查询参数：

- `source_id`
- `session_id`
- `include_invalidated`

### 3.7 `GET /memory/graph`

读取图视图版本的记忆数据。

### 3.8 `GET /runtime/state`

读取运行状态快照。

查询参数：

- `session_id`: 选填；传入后返回该会话状态，不传则只返回全局与心跳状态

响应：

```json
{
  "global_state": {
    "session_id": "system:global",
    "status": "idle",
    "detail": "",
    "active_tools": [],
    "stream_id": "",
    "turn_id": "",
    "updated_at": "2026-04-01T00:00:00Z"
  },
  "heartbeat_state": {
    "session_id": "system:heart",
    "status": "heartbeat",
    "detail": "tick",
    "active_tools": [
      "heartbeat"
    ],
    "stream_id": "",
    "turn_id": "",
    "updated_at": "2026-04-01T00:00:01Z"
  },
  "session_state": {
    "session_id": "web:session:001",
    "status": "thinking",
    "detail": "Calling model",
    "active_tools": [],
    "stream_id": "stream-001",
    "turn_id": "turn-001",
    "updated_at": "2026-04-01T00:00:02Z"
  }
}
```

状态枚举固定为：

- `initializing`
- `idle`
- `thinking`
- `tool_calling`
- `answering`
- `waiting_confirm`
- `waiting_human_input`
- `heartbeat`
- `error`
- `shutting_down`

### 3.9 `GET /runtime/usage`

读取某个会话的 context / token 使用情况。

查询参数：

- `session_id`: 必填

响应：

```json
{
  "session_id": "web:session:001",
  "context_limit_tokens": 400000,
  "current_context_tokens_estimated": 4120,
  "context_breakdown": {
    "system": 400,
    "history": 1800,
    "tool_history": 600,
    "memory_context": 320,
    "policy": 450,
    "current_input": 180,
    "proprioception": 370,
    "total": 4120
  },
  "last_turn_usage": {
    "prompt_tokens": 2200,
    "completion_tokens": 260,
    "reasoning_tokens": 80,
    "total_tokens": 2540
  },
  "session_totals": {
    "prompt_tokens": 6800,
    "completion_tokens": 720,
    "reasoning_tokens": 180,
    "total_tokens": 7700,
    "turn_count": 4
  },
  "usage_source": "provider",
  "updated_at": "2026-04-01T00:00:03Z"
}
```

上下文组成固定为：

- `system`
- `history`
- `tool_history`
- `memory_context`
- `policy`
- `current_input`
- `proprioception`

口径说明：

- provider 原生 usage 优先
- provider 未返回时使用后端估算值
- `usage_source` 为 `provider | estimated`
- `context_breakdown` 是统一估算口径，不保证与各 provider 账单数字完全一致

## 4. WebSocket API

### 4.1 Connect

```text
GET /ws?session_id=<session_id>&source_id=<source_id>
```

### 4.2 Connection Frame

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

### 4.3 Event Envelope

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "event",
  "event": {
    "event_id": "string",
    "session_id": "web:session:001",
    "type": "message",
    "role": "assistant",
    "content": "string or object",
    "metadata": {
      "stream_event": "chunk",
      "stream_channel": "answer",
      "turn_id": "turn-001"
    }
  },
  "stream": {
    "id": "stream-001",
    "phase": "chunk",
    "channel": "answer"
  }
}
```

### 4.4 Event Types

- `message`: 正文流
- `reasoning`: 思考流
- `status`: 搜索 / 工具状态
- `confirm_request`: 确认请求
- `human_input_request`: 同一轮内的人类补充输入请求
- `runtime_status`: 运行状态快照
- `usage`: 使用量快照
- `error`: 错误消息

### 4.5 `message`

约定：

- `event.content` 为正文内容
- `stream.channel = "answer"`

### 4.6 `reasoning`

约定：

- `event.content` 为字符串
- `stream.channel = "reasoning"`
- 与同一轮回答共享 `metadata.turn_id`
- 不会混入 `message` 正文流

官方 OpenAI 说明：

- `reasoning` 表示官方 reasoning summary
- 不表示原始思考全文

### 4.7 `runtime_status`

约定：

- `event.content` 为对象
- 结构与 `GET /runtime/state` 中的单个快照一致

### 4.8 `usage`

约定：

- `event.content` 为对象
- 结构与 `GET /runtime/usage` 一致

### 4.9 Incoming Commands

`ping`:

```json
{
  "action": "ping"
}
```

返回：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "pong"
}
```

`confirm_response`:

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

`input_response`:

```json
{
  "action": "input_response",
  "request_id": "string",
  "answer_text": "B",
  "selected_option": "B",
  "metadata": {
    "from": "human-input-panel"
  }
}
```

`human_input_request` 额外字段：

```json
{
  "input_request": {
    "request_id": "string",
    "question": "请选择一个方案",
    "options": ["方案 A", "方案 B"],
    "placeholder": "也可以直接补充说明",
    "timeout": 60
  }
}
```

## 5. Runtime State Flow

会话状态迁移：

1. 收到请求后进入 `thinking`
2. 调用工具时进入 `tool_calling`
3. 开始输出正文时进入 `answering`
4. 等待用户确认时进入 `waiting_confirm`
5. 等待用户补充信息时进入 `waiting_human_input`
6. 当前轮完成后回到 `idle`
7. 出错时进入 `error`

心跳状态独立维护：

- 执行中：`heartbeat`
- 空闲：`idle`

全局状态主要表示服务生命周期：

- 启动中：`initializing`
- 运行中：`idle`
- 关闭中：`shutting_down`

## 6. Frontend Integration

- 聊天输入继续走 `POST /inputs`
- 回答正文只消费 `message`
- 同一轮追问通过 `human_input_request` / `input_response` 完成，不会创建新的用户 turn
- 思考摘要只消费 `reasoning`
- 运行状态消费 `runtime_status`
- token / context 统计消费 `usage` 或 `GET /runtime/usage`

当前前端已经基于这套协议实现，不再保留旧适配分支。
