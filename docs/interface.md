# MeetYou 前端接口文档

本文档面向前端开发，描述新后端当前对 UI 暴露的完整 HTTP / WebSocket 接口、鉴权规则、通用协议与接入约定。

当前文档对应的协议版本：

- HTTP schema：`meetyou.http.v1`
- WebSocket schema：`meetyou.ws.v1`
- 机器可读 schema：`GET /schema/ui`

建议前端将本文件作为人工说明，将 `GET /schema/ui` 作为枚举、字段分组和配置表单的机器真源。

## 1. 接入总览

前端当前会用到的主要接口：

- 聊天输入：`POST /inputs`
- 会话实时流：`GET /ws`
- 运行状态：`GET /runtime/state`
- 用量统计：`GET /runtime/usage`
- 配置中心：`GET /schema/ui`、`GET /config`、`GET /config/{key}`、`PATCH /config`
- 记忆视图：`GET /memory`、`GET /memory/graph`
- 服务健康：`GET /health`

核心设计原则：

- HTTP 负责提交动作、拉取快照、读取配置
- WebSocket 负责实时事件、确认流、人类补充输入流
- 所有错误都返回结构化错误对象，不再依赖 `"Error: ..."` 字符串契约
- `session_id` 是会话主键，`source_id` 是前端连接来源标识
- 流式回答用 `message`，独立思考摘要用 `reasoning`，运行态推送统一走 `runtime`

## 2. 鉴权与跨域

### 2.1 鉴权规则

- `GET /health` 默认免鉴权
- 其他 HTTP 接口默认受保护
- WebSocket 连接默认受保护
- 如果服务端未配置 `gateway_access_token`，则 HTTP / WS 鉴权会放开

支持的鉴权方式：

- HTTP：`Authorization: Bearer <token>`
- HTTP：`X-API-Key: <token>`
- WebSocket：同样支持 `Authorization` 和 `X-API-Key`
- WebSocket：额外支持 query 参数 `access_token=<token>`

推荐：

- 浏览器前端优先走 `Authorization: Bearer`
- 如果浏览器环境不方便设置 WS header，再改用 `access_token` query 参数

### 2.2 CORS 与 Origin

- 默认仅允许 loopback 来源，例如 `http://127.0.0.1:*`、`http://localhost:*`
- 额外允许列表由配置项 `gateway_cors_origins` 控制
- WebSocket 连接也会校验 `Origin`

当 Origin 不在允许列表内时，WebSocket 会先返回错误帧，再关闭连接。

## 3. 会话与来源标识

### 3.1 `session_id`

- 表示一段持续对话
- 前端应尽量在同一聊天窗口内复用稳定的 `session_id`
- `POST /inputs` 不传 `session_id` 时，后端会自动创建新会话
- `GET /ws` 传入的 `session_id` 若不存在，后端也会创建并绑定

### 3.2 `source_id`

- 表示当前输入 / 连接来源
- 建议为每个前端实例分配稳定值，例如 `desktop-app`、`browser-tab-a`
- 同一页面刷新后若希望继续复用会话，建议仍然使用相同 `source_id`

### 3.3 `client_message_id`

- 用于 `POST /inputs` 幂等去重
- 后端以 `(session_id, source_id, client_message_id)` 作为去重键
- 若重复提交同一条消息，后端不会重复入队，而是返回第一次受理时的 `event_id`

## 4. 通用响应协议

### 4.1 HTTP 成功响应

HTTP 返回结构按 `kind` 分为：

- `health`
- `ack`
- `runtime`
- `schema`
- 普通资源对象，例如 `/config`、`/memory`

### 4.2 HTTP 错误响应

所有 HTTP 错误统一返回：

```json
{
  "schema": "meetyou.http.v1",
  "kind": "error",
  "error": {
    "code": "unauthorized",
    "category": "runtime",
    "message": "缺少有效访问令牌",
    "retryable": false,
    "details": {
      "auth_type": "bearer_or_api_key"
    },
    "occurred_at": "2026-04-01T00:00:00Z"
  }
}
```

错误对象字段：

- `code`：稳定错误码，前端应优先按这个字段分支
- `category`：`runtime | validation | dependency`
- `message`：展示给用户或日志的可读消息
- `retryable`：是否适合前端提示重试
- `details`：额外上下文
- `occurred_at`：错误发生时间

### 4.3 WebSocket 通用帧

所有 WebSocket 出站帧都包含：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "connection | event | runtime | ack | error | health | pong"
}
```

### 4.4 WebSocket 错误帧

WebSocket 错误与 HTTP 错误共用同一 `error` 结构：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "error",
  "error": {
    "code": "invalid_payload",
    "category": "validation",
    "message": "..."
  }
}
```

前端收到 `kind = error` 时，应：

- 记录错误码与消息
- 对 `unauthorized`、`origin_not_allowed` 这类连接级错误直接进入断开状态
- 对 `stale_confirm_response`、`stale_input_response` 这类交互级错误，只关闭当前弹窗或当前请求状态，不必整条连接下线

## 5. 机器可读 Schema

### 5.1 `GET /schema/ui`

用途：

- 获取前端配置页需要的 provider、thinking 努力级别、配置分组、配置字段定义
- 获取协议枚举，例如 WS frame kind、event type、runtime resource、runtime status

鉴权：

- 需要

响应：

```json
{
  "schema": "meetyou.http.v1",
  "kind": "schema",
  "ui_schema": {
    "http_schema": "meetyou.http.v1",
    "ws_schema": "meetyou.ws.v1",
    "ws_frame_kinds": ["connection", "event", "runtime", "ack", "error", "health", "pong"],
    "ws_event_types": ["message", "reasoning", "status", "confirm_request", "human_input_request", "runtime_status", "usage", "error"],
    "ws_runtime_resources": ["state", "usage", "debug"],
    "runtime_statuses": ["initializing", "idle", "thinking", "tool_calling", "answering", "waiting_confirm", "waiting_human_input", "heartbeat", "error", "shutting_down"],
    "providers": [
      { "label": "OpenAI", "value": "openai" },
      { "label": "Anthropic", "value": "anthropic" }
    ],
    "thinking_efforts": [
      { "label": "低", "value": "low" },
      { "label": "中", "value": "medium" },
      { "label": "高", "value": "high" }
    ],
    "config_groups": [],
    "config_fields": []
  }
}
```

前端建议：

- 不要在前端硬编码 provider 列表和配置字段描述
- 配置表单优先使用 `config_groups + config_fields` 渲染
- 协议枚举校验优先使用这里的返回值

## 6. HTTP 接口

### 6.1 `GET /health`

用途：

- 检查服务是否存活、是否可用、是否处于降级状态

鉴权：

- 不需要

响应：

```json
{
  "schema": "meetyou.http.v1",
  "kind": "health",
  "health": {
    "service": "meetyou-runtime",
    "version": "service-runtime-v1alpha1",
    "status": "ready",
    "live": true,
    "ready": true,
    "degraded": false,
    "components": [
      {
        "name": "session_execution",
        "status": "ready",
        "detail": "ok",
        "last_event": "gateway.ready",
        "updated_at": "2026-04-01T00:00:00Z"
      }
    ],
    "checks": [],
    "metrics": {},
    "telemetry": [],
    "errors": [],
    "updated_at": "2026-04-01T00:00:00Z"
  }
}
```

字段说明：

- `status`：服务整体状态，可能值为 `starting | ready | degraded | stopping | error`
- `live`：进程是否仍然活着
- `ready`：服务是否可对外提供正常能力
- `degraded`：服务是否处于降级状态
- `components`：组件级健康信息
- `checks`：运行时检查项
- `metrics`：关键指标快照
- `telemetry`：最近的遥测信号
- `errors`：最近记录的结构化运行时错误

前端建议：

- 用 `ready` 决定是否允许用户发起聊天
- 用 `degraded` 呈现黄色告警，而不是直接当作不可用

### 6.2 `POST /inputs`

用途：

- 提交用户消息到指定会话

鉴权：

- 需要

请求体：

```json
{
  "content": "帮我总结今天的工作",
  "session_id": "web:session:001",
  "source_id": "browser-tab-a",
  "client_message_id": "web-1712076000000-a1b2c3d4",
  "role": "user",
  "preferred_mode": "research",
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

字段说明：

- `content`：必填，用户输入文本
- `session_id`：选填，不传则后端自动创建
- `source_id`：选填，默认 `web-client`
- `client_message_id`：选填，用于幂等
- `role`：选填，默认 `user`
- `preferred_mode`：选填，告诉后端优先采用的助手模式
- `metadata`：选填，透传附加信息
- `options.thinking.enabled`：选填，是否启用本轮 thinking
- `options.thinking.effort`：选填，`low | medium | high`
- `options.thinking.budget_tokens`：选填，本轮 thinking token 预算

合并规则：

- 配置里的 `thinking_enabled`、`thinking_effort`、`thinking_budget_tokens` 是默认值
- `POST /inputs.options` 是单次覆盖值
- 最终参数由后端统一合并后送入执行链路

成功响应：

```json
{
  "schema": "meetyou.http.v1",
  "kind": "ack",
  "ack": {
    "action": "input.accepted",
    "accepted": true,
    "session_id": "web:session:001",
    "event_id": "e3f0f0d6...",
    "request_id": ""
  }
}
```

字段说明：

- `ack.action`：当前固定为 `input.accepted`
- `ack.accepted`：是否受理成功
- `ack.session_id`：最终使用的会话 id
- `ack.event_id`：本次输入生成的入站事件 id
- `ack.request_id`：当前为空字符串，前端可忽略

前端建议：

- 输入框提交成功后立即落一条本地 optimistic user message
- 真正的回答内容由 WebSocket 后续事件驱动更新
- 若重复发送同一 `client_message_id`，以前一次 `event_id` 作为已受理结果处理即可

### 6.3 `GET /config`

用途：

- 读取全部受管配置项

鉴权：

- 需要

响应：

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
      "value": "te*****et",
      "is_secret": true,
      "has_value": true,
      "source": "env",
      "env_key": "MEETYOU_API_KEY"
    }
  }
}
```

字段说明：

- `value`：配置当前值；密钥类字段通常是脱敏值
- `is_secret`：是否为敏感项
- `has_value`：后端是否检测到此项已设置
- `source`：值来源，例如 `config`、`env`、`default`
- `env_key`：若来源可被环境变量覆盖，则返回对应变量名

### 6.4 `GET /config/{key}`

用途：

- 读取单个配置项

鉴权：

- 需要

成功响应结构与 `/config.items[key]` 一致。

失败时：

- 返回 `404`
- `error.code = config_not_found`

### 6.5 `PATCH /config`

用途：

- 批量更新配置并触发热刷新

鉴权：

- 需要

请求体：

```json
{
  "updates": {
    "thinking_enabled": true,
    "thinking_effort": "medium",
    "thinking_budget_tokens": 2048
  }
}
```

成功响应：

```json
{
  "applied_keys": ["thinking_budget_tokens", "thinking_effort", "thinking_enabled"],
  "reloaded_components": ["brain"],
  "restart_required_keys": [],
  "warnings": []
}
```

字段说明：

- `applied_keys`：本次真正写入的配置键
- `reloaded_components`：已完成热刷新的组件
- `restart_required_keys`：需要重启才能完全生效的配置键
- `warnings`：非阻塞告警

失败时：

- 非法更新返回 `400`
- `error.code = invalid_config_update`

### 6.6 `GET /memory`

用途：

- 获取记忆快照

鉴权：

- 需要

查询参数：

- `source_id`：选填，按来源过滤
- `session_id`：选填，按会话过滤
- `include_invalidated`：选填，是否包含失效记录，默认 `false`

响应结构：

- `metadata`：记忆模型与更新时间
- `scope`：当前快照对应的来源与会话范围
- `working_summaries`：全局 / 会话工作摘要
- `records`：记忆记录数组
- `edges`：记忆关系数组
- `stats`：统计信息

适合场景：

- 记忆面板
- 开发态调试
- 关系数据二次加工

### 6.7 `GET /memory/graph`

用途：

- 获取适合图视图渲染的记忆结构

鉴权：

- 需要

查询参数与 `/memory` 相同。

与 `/memory` 的区别：

- 节点字段为 `nodes`
- 边字段为 `edges`
- 边格式更适合直接喂给图可视化组件

### 6.8 `GET /runtime/state`

用途：

- 拉取运行状态快照

鉴权：

- 需要

查询参数：

- `session_id`：选填；传入后返回该会话状态，不传则只返回全局与心跳状态

响应：

```json
{
  "schema": "meetyou.http.v1",
  "kind": "runtime",
  "runtime": {
    "resource": "state",
    "session_id": "web:session:001",
    "state": {
      "global_state": {
        "session_id": "system:global",
        "status": "idle",
        "detail": "",
        "active_tools": [],
        "current_mode": "",
        "route_reason": "",
        "action_risk": "read",
        "source_profile": "",
        "stream_id": "",
        "turn_id": "",
        "updated_at": "2026-04-01T00:00:00Z"
      },
      "heartbeat_state": {
        "session_id": "system:heart",
        "status": "heartbeat",
        "detail": "tick",
        "active_tools": ["heartbeat"],
        "current_mode": "",
        "route_reason": "",
        "action_risk": "read",
        "source_profile": "",
        "stream_id": "",
        "turn_id": "",
        "updated_at": "2026-04-01T00:00:01Z"
      },
      "session_state": {
        "session_id": "web:session:001",
        "status": "thinking",
        "detail": "Calling model",
        "active_tools": ["search_memory"],
        "current_mode": "research",
        "route_reason": "Matched research signals: latest, direct_url",
        "action_risk": "read",
        "source_profile": "tech_global",
        "stream_id": "stream-1",
        "turn_id": "turn-1",
        "updated_at": "2026-04-01T00:00:02Z"
      }
    }
  }
}
```

`RuntimeStateSnapshot` 字段说明：

- `status`：运行状态
- `detail`：当前阶段描述
- `active_tools`：正在执行或最近活跃的工具
- `current_mode`：当前助手模式
- `route_reason`：模式路由原因
- `action_risk`：当前动作风险级别
- `source_profile`：当前信息源画像
- `stream_id`：当前回答流 id
- `turn_id`：当前轮次 id
- `updated_at`：更新时间

运行状态枚举：

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

前端建议：

- `global_state` 用于展示服务主状态
- `heartbeat_state` 用于后台轮询 / 守护状态
- `session_state` 用于当前聊天窗口状态条

### 6.9 `GET /runtime/usage`

用途：

- 获取指定会话的上下文 / token 使用情况

鉴权：

- 需要

查询参数：

- `session_id`：必填

响应：

```json
{
  "schema": "meetyou.http.v1",
  "kind": "runtime",
  "runtime": {
    "resource": "usage",
    "session_id": "web:session:001",
    "usage": {
      "session_id": "web:session:001",
      "usage_ready": true,
      "context_limit_tokens": 128000,
      "context_limit_source": "config_override",
      "context_limit_model": "deepseek-reasoner",
      "context_limit_confidence": "high",
      "current_context_tokens_estimated": 2048,
      "context_breakdown": {
        "system": 200,
        "history": 800,
        "tool_history": 128,
        "memory_context": 256,
        "policy": 256,
        "current_input": 128,
        "proprioception": 280,
        "total": 2048
      },
      "last_turn_usage": {
        "prompt_tokens": 900,
        "completion_tokens": 120,
        "reasoning_tokens": 44,
        "total_tokens": 1064
      },
      "session_totals": {
        "prompt_tokens": 1900,
        "completion_tokens": 240,
        "reasoning_tokens": 88,
        "total_tokens": 2228,
        "turn_count": 2
      },
      "usage_source": "provider",
      "updated_at": "2026-04-01T00:00:03Z"
    }
  }
}
```

### 6.10 `GET /runtime/debug`

用途：

- 获取统一的中层调试快照，便于一次性查看路由、上下文计划、记忆检索范围、任务后台状态与授权决策

鉴权：

- 需要

查询参数：

- `session_id`：必填

响应：

```json
{
  "schema": "meetyou.http.v1",
  "kind": "runtime",
  "runtime": {
    "resource": "debug",
    "session_id": "web:session:001",
    "debug": {
      "session_id": "web:session:001",
      "route": {
        "requested_mode": "normal",
        "current_mode": "research",
        "route_reason": "Brain switched mode: Need citations and source tracking",
        "source_profile": "tech_global",
        "tool_bundle": ["research_tool", "research_topic", "inspect_page", "track_source_updates"],
        "mcp_servers": [],
        "prompt_bundle": "research",
        "active_skills": [],
        "loaded_skills": [],
        "confidence": "high",
        "should_preload_context": true,
        "prefer_live_web": true,
        "signals": ["deep_research"],
        "adapter_name": "semantic_router",
        "used_keyword_fallback": false,
        "authorization_policy": {
          "read_only": true
        },
        "disable_tools": false
      },
      "route_history": [
        { "round": 0, "mode": "normal" },
        { "round": 1, "mode": "research" }
      ],
      "context_plan": {
        "length_policy": {
          "target_input_tokens": 4096
        },
        "layers": {
          "conversation_summary": true,
          "memory_recall": true,
          "session_preload": true,
          "prefer_live_web": true
        },
        "breakdown": {
          "total": 2048
        }
      },
      "memory_scope": {
        "session_id": "web:session:001",
        "prefetched": true,
        "found": true,
        "profile_count": 1,
        "fact_count": 2,
        "recent_event_count": 1
      },
      "authorization": {
        "route_preview": {
          "visible_tools": ["research_tool", "research_topic", "inspect_page", "track_source_updates"],
          "candidate_tools": ["research_tool", "research_topic", "inspect_page", "track_source_updates"],
          "authorization_preview": [
            {
              "tool_name": "research_tool",
              "allowed": true,
              "action_risk": "read"
            }
          ]
        },
        "recent_decisions": [
          {
            "tool_name": "research_topic",
            "ok": true,
            "authorization": {
              "allowed": true,
              "action_risk": "read"
            }
          }
        ]
      },
      "task_state": {
        "background": {
          "schedule": {
            "due_task_count": 1
          },
          "execution": {
            "awaiting_completion_count": 0
          },
          "delivery": {
            "pending_redelivery_count": 0
          },
          "system": {}
        },
        "sources": ["task_manager.schedule", "task_manager.execution", "task_manager.delivery"]
      },
      "runtime_state": {
        "session_id": "web:session:001",
        "status": "thinking"
      },
      "usage": {
        "session_id": "web:session:001",
        "usage_ready": true
      },
      "updated_at": "2026-04-01T00:00:04Z"
    }
  }
}
```

字段说明：

- `route`：当前 Route Runtime 的脱敏快照，不包含原始用户内容
- `context_plan`：本轮上下文计划的长度策略、层级开关与 token 拆分
- `memory_scope`：自动记忆预取是否命中，以及命中的 profile / fact / event 数量
- `authorization.route_preview`：当前路由下的工具可见性与授权预览
- `authorization.recent_decisions`：最近执行过的工具授权结果摘要
- `task_state.background`：后台任务系统的 schedule / execution / delivery 三层快照

前端建议：

- 将该接口用于开发态诊断面板，不建议在普通聊天主界面默认展开
- 直接展示 `route / context_plan / authorization / task_state`，避免自行拼装多个接口
- 把 `memory_scope` 视为命中范围摘要，不要将其当作完整记忆内容源

字段说明：

- `usage_ready`：当前会话是否已有可展示 usage
- `context_limit_tokens`：上下文上限
- `context_limit_source`：上限来源
- `context_limit_model`：推导上限时参考的模型
- `context_limit_confidence`：可信度
- `current_context_tokens_estimated`：当前估算上下文 token
- `context_breakdown`：统一估算口径下的上下文拆分
- `last_turn_usage`：上一轮用量
- `session_totals`：本会话累计用量
- `usage_source`：`provider | estimated`

`context_breakdown` 固定字段：

- `system`
- `history`
- `tool_history`
- `memory_context`
- `policy`
- `current_input`
- `proprioception`
- `total`

口径说明：

- 如果 provider 返回原生 usage，则 `usage_source = provider`
- 否则后端回退到估算值，`usage_source = estimated`
- `context_breakdown` 是统一估算口径，不保证与账单精确一致

## 7. WebSocket 接口

### 7.1 连接地址

```text
GET /ws?session_id=<session_id>&source_id=<source_id>&access_token=<token>
```

参数说明：

- `session_id`：选填，不传则自动创建
- `source_id`：选填，默认 `websocket`
- `access_token`：选填，仅当无法通过 header 传鉴权时使用

连接成功后，服务端会先发送一条 `connection` 帧。

### 7.2 `connection` 帧

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

字段说明：

- `connection.session_id`：最终绑定的会话 id
- `connection.source_id`：本次连接来源
- `connection.status`：当前固定为 `connected`

### 7.3 `event` 帧

除运行态外，大多数实时消息都通过 `kind = event` 发送：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "event",
  "event": {
    "event_id": "evt-1",
    "session_id": "web:session:001",
    "type": "message",
    "role": "assistant",
    "content": "你好，我来帮你总结。",
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
    "stream_id": "stream-1",
    "reply_to": "",
    "metadata": {
      "turn_id": "turn-1",
      "stream_event": "chunk",
      "stream_channel": "answer"
    }
  },
  "stream": {
    "id": "stream-1",
    "phase": "chunk",
    "channel": "answer"
  }
}
```

通用字段说明：

- `event.event_id`：事件唯一 id
- `event.session_id`：所属会话
- `event.type`：事件类型
- `event.role`：角色，常见为 `assistant`、`system`
- `event.content`：事件正文
- `event.source`：发送方来源
- `event.target`：目标来源
- `event.stream_id`：流 id
- `event.reply_to`：回复关系
- `event.metadata`：扩展元数据
- `stream.id`：流 id，通常与 `event.stream_id` 一致
- `stream.phase`：`start | chunk | end | error`
- `stream.channel`：`answer | reasoning`

### 7.4 事件类型

当前已定义的 WS 事件类型：

- `message`
- `reasoning`
- `status`
- `confirm_request`
- `human_input_request`
- `runtime_status`
- `usage`
- `error`

注意：

- `runtime_status` 和 `usage` 在 WebSocket 出站时会被提升为 `kind = runtime`
- 因此前端收到的帧类型应优先按 `kind` 解析，而不是只按 `event.type`

### 7.5 `message`

用途：

- 承载正式回答正文

约定：

- `event.content` 为字符串或可直接渲染内容
- `stream.channel = answer`
- 同一轮的开始、增量、结束分别由 `stream.phase` 表示

前端建议：

- 以 `stream.id` 或 `metadata.turn_id` 聚合同一轮回答
- `start` 时创建 assistant 消息，`chunk` 时追加，`end` 时结束流状态

### 7.6 `reasoning`

用途：

- 承载独立的思考摘要流

约定：

- `event.content` 通常为字符串
- `stream.channel = reasoning`
- 与同一轮正式回答共享 `metadata.turn_id`
- 不会混入 `message` 正文流

说明：

- 对官方 OpenAI，这里表示 reasoning summary，不表示原始 chain-of-thought

前端建议：

- 将 reasoning 作为单独面板、折叠区或 secondary message 展示
- 不要把 reasoning 和 answer 直接拼接成一条正文

### 7.7 `status`

用途：

- 展示工具链、搜索、系统提示等过程状态

约定：

- `event.content` 通常为可读文本
- 不作为正式回答正文

前端建议：

- 放到事件时间线、状态提示条或调试面板

### 7.8 `confirm_request`

用途：

- 后端要求用户确认某个动作

示例：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "event",
  "event": {
    "type": "confirm_request",
    "content": "是否执行写入操作？",
    "confirm": {
      "request_id": "req-1",
      "timeout": 30,
      "default_decision": false
    },
    "metadata": {
      "turn_id": "turn-1"
    }
  }
}
```

字段说明：

- `confirm.request_id`：前端回传确认结果时必填
- `confirm.timeout`：超时时间，单位秒
- `confirm.default_decision`：超时默认决策

前端处理：

- 弹出确认框
- 保存 `request_id`
- 用户确认后通过 `confirm_response` 回传

### 7.9 `human_input_request`

用途：

- 在同一轮执行中，请求用户补充信息

示例：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "event",
  "event": {
    "type": "human_input_request",
    "content": "请补充一个部署环境",
    "input_request": {
      "request_id": "req-2",
      "question": "请选择一个方案",
      "options": ["方案 A", "方案 B"],
      "placeholder": "也可以直接补充说明",
      "timeout": 60
    },
    "metadata": {
      "turn_id": "turn-1"
    }
  }
}
```

字段说明：

- `input_request.request_id`：回传时必填
- `input_request.question`：问题文本
- `input_request.options`：可选项数组
- `input_request.placeholder`：输入框占位
- `input_request.timeout`：超时时间，单位秒

前端处理：

- 打开同轮补充输入 UI
- 用户提交后通过 `input_response` 回传
- 不需要重新调用 `POST /inputs`

### 7.10 `runtime` 帧

运行态推送统一使用 `kind = runtime`：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "runtime",
  "runtime": {
    "resource": "state",
    "session_id": "web:session:001",
    "state": {
      "session_id": "web:session:001",
      "status": "thinking",
      "turn_id": "turn-1"
    },
    "usage": null,
    "metadata": {
      "turn_id": "turn-1"
    },
    "event_id": "evt-runtime-1"
  }
}
```

资源类型：

- `state`
- `usage`

约定：

- `resource = state` 时，`runtime.state` 对应运行状态快照
- `resource = usage` 时，`runtime.usage` 对应用量快照
- `runtime.metadata.turn_id` 用于关联到具体对话轮次

前端建议：

- 把 `runtime.state` 视为实时态更新
- 把 `GET /runtime/state` 视为初始快照或补偿拉取
- 把 `runtime.usage` 视为实时更新，把 `GET /runtime/usage` 视为补偿拉取

### 7.11 `health` 帧

协议层已保留 `kind = health` 帧，用于推送运行时健康信息。

当前说明：

- 前端需要支持解析
- 目前后端主路径已支持该 frame kind，但健康信息更常通过 `GET /health` 拉取

### 7.12 `ack` 帧

当 WebSocket 入站命令成功时，服务端返回：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "ack",
  "ack": {
    "action": "confirm_response",
    "accepted": true,
    "session_id": "web:session:001",
    "event_id": "",
    "request_id": "req-1"
  }
}
```

字段说明：

- `action`：对应收到的命令动作
- `accepted`：是否受理成功
- `session_id`：当前会话
- `request_id`：对应确认 / 补充输入请求 id
- `event_id`：当前命令通常不返回事件 id，可为空字符串

### 7.13 `pong` 帧

客户端发：

```json
{
  "action": "ping"
}
```

服务端回：

```json
{
  "schema": "meetyou.ws.v1",
  "kind": "pong"
}
```

可用于保活或连接探测。

## 8. WebSocket 入站命令

### 8.1 `ping`

请求：

```json
{
  "action": "ping"
}
```

响应：

- `kind = pong`

### 8.2 `confirm_response`

用途：

- 响应 `confirm_request`

请求：

```json
{
  "action": "confirm_response",
  "request_id": "req-1",
  "accepted": true,
  "metadata": {
    "from": "confirm-dialog"
  }
}
```

字段要求：

- `request_id`：必填
- `accepted`：必填
- `metadata`：选填

成功：

- 返回 `kind = ack`

失败：

- 缺字段时返回 `invalid_confirm_response`
- 请求已失效或会话不匹配时返回 `stale_confirm_response`

### 8.3 `input_response`

用途：

- 响应 `human_input_request`

请求：

```json
{
  "action": "input_response",
  "request_id": "req-2",
  "answer_text": "B",
  "selected_option": "B",
  "metadata": {
    "from": "human-input-panel"
  }
}
```

字段要求：

- `request_id`：必填
- `answer_text`：选填，用户自由输入
- `selected_option`：选填，用户选中的预设项
- `metadata`：选填

成功：

- 返回 `kind = ack`

失败：

- 缺少 `request_id` 时返回 `invalid_input_response`
- 请求已失效或会话不匹配时返回 `stale_input_response`

### 8.4 不支持的命令

当 `action` 不在支持列表内时，返回：

- `kind = error`
- `error.code = unsupported_action`

## 9. 前端状态管理建议

### 9.1 建议拆分三类状态

- 连接状态：是否已连接、是否鉴权通过、最近错误
- 会话状态：消息列表、流式聚合、确认弹窗、人类输入弹窗
- 运行状态：health、runtime.state、runtime.usage

### 9.2 初始加载建议

推荐顺序：

1. `GET /health`
2. `GET /schema/ui`
3. 若进入聊天页，建立 `GET /ws`
4. 建立成功后拉 `GET /runtime/state`
5. 若已有 `session_id`，再拉 `GET /runtime/usage`

### 9.3 聊天页建议流转

1. 首次进入页面，若没有会话则先建立 WS
2. 提交输入时调用 `POST /inputs`
3. 收到 `ack` 后保持本地 optimistic 状态
4. 收到 `message` / `reasoning` / `status` / `runtime` 实时更新 UI
5. 收到 `confirm_request` 或 `human_input_request` 时进入同轮交互
6. 当前轮结束后，以 `runtime.state.status = idle` 或流结束作为收尾信号

### 9.4 长会话建议

- 以前端本地裁剪策略保留最近若干条 turn
- 保留最新的活动工具状态和当前流内容
- 需要完整历史时，再结合后端记忆或本地持久化方案补足

## 10. 错误码与前端处理建议

常见错误码：

- `unauthorized`：缺少或错误的访问令牌
- `origin_not_allowed`：当前 Origin 不被允许
- `invalid_request`：HTTP 请求体或查询参数校验失败
- `invalid_config_update`：配置更新非法
- `config_not_found`：配置键不存在
- `runtime_state_not_found`：运行状态不存在
- `runtime_usage_not_found`：用量快照不存在
- `invalid_payload`：WS 入站载荷不合法
- `invalid_confirm_response`：确认响应缺字段
- `stale_confirm_response`：确认请求已过期或不匹配
- `invalid_input_response`：补充输入缺字段
- `stale_input_response`：补充输入请求已过期或不匹配
- `unsupported_action`：不支持的 WS action

前端处理建议：

- 对 `unauthorized`：跳登录、弹凭证错误或提示检查 token
- 对 `origin_not_allowed`：提示当前前端来源不在白名单
- 对 `invalid_request` / `invalid_config_update`：就地展示表单错误
- 对 `stale_*`：关闭当前弹窗并提示“请求已失效”
- 对 `runtime_*_not_found`：清空当前侧栏快照并允许稍后重试

## 11. 与旧协议的关键差异

- `GET /schema/ui` 现在是前端配置和协议枚举的单一来源
- `reasoning` 已独立为单独流，不再混入 `message`
- `runtime_status` 与 `usage` 的 WS 推送统一提升为 `kind = runtime`
- 所有错误改为结构化对象，不再依赖字符串前缀
- 配置页不应再硬编码 provider、thinking effort 和字段定义
- 鉴权与 CORS 已收紧，桌面端 / 浏览器端需要显式考虑 token 与 Origin

## 12. 推荐实现清单

前端接入至少应支持：

- HTTP Bearer / API Key 注入
- WebSocket token 注入
- `connection / event / runtime / ack / error / health / pong` 全部 frame kind
- `message / reasoning / status / confirm_request / human_input_request` 事件分支
- `runtime.state` 与 `runtime.usage` 的实时更新
- `stale_confirm_response`、`stale_input_response` 的友好处理
- `GET /schema/ui` 驱动配置页面
- 长会话裁剪或等效性能策略

如果后端协议继续演进，应以 `GET /schema/ui` 与本文件同步更新为准。
