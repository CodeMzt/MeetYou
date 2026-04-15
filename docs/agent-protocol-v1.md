# MeetYou Agent Protocol V1

## 1. 文档目的

Agent Protocol V1 定义 Core Service 与 Agent 之间的统一语义协议，用于支持：

- Agent 注册与鉴权
- 心跳与在线状态
- Capability 快照上报
- Core 下发执行请求
- Agent 回传进度、结果、错误
- 离线缓存补同步
- 大附件通过对象存储独立传输
- 工具执行产生的附件通过 `attachment_outputs` 工具化回传，再由 Core 统一归一化为 attachment object view

V1 同时覆盖两类 Agent：

- `Desktop Agent`
- `Edge Agent / Bridge Agent`

## 2. 协议原则

- Core 是唯一编排者。
- Agent 上报能力，Core 负责选路。
- 协议语义统一，传输通过同一套 `WSS /agent/ws` 主链承载，具体形态按 `transport_profile` 区分。
- 小消息走主协议，大附件走对象存储。
- 支持多 workspace agent membership。
- Agent 不直接发明用户面下载链接；附件相关用户面对象由 Core 统一生成。
- transport heartbeat 只负责 Agent 在线状态、last seen 和运行指标协商；它不等同于 `Core Heart` 的服务端时间编排。
- `agent.hello.ack` 可以重协商 heartbeat 间隔，新 `heartbeat_interval_seconds` 应立即作用到当前连接。

## 3. 传输 Profile

### 3.1 Desktop Profile

- 主传输：`WSS`
- 辅助：`HTTPS`
- 适用：PC 本地 Agent
- 特性：支持低时延双向事件流、支持离线结果补同步

### 3.2 Edge Profile

- 主传输：`WSS`
- 辅助：必要时 `HTTPS` 上传附件元数据或获取对象存储票据
- 适用：树莓派、嵌入式、边缘节点
- 特性：与 Desktop Profile 共享同一套 `meetyou.agent.v1` envelope，只通过 `transport_profile` 标记边缘形态，例如 `edge_wss`

## 4. 鉴权模型

### 4.1 Agent 身份

每个 Agent 具有：

- `agent_id`
- `agent_type`
- `principal_id`
- `workspace_ids[]`

### 4.2 凭据

Agent 不使用 Client Token。

当前正式口径：

- Agent HTTP / WebSocket 与 Client 面分开鉴权，启用后接受 `Authorization: Bearer ...` 或 `X-API-Key`
- WebSocket 额外兼容 `access_token` query 参数，便于非浏览器 runtime 连接
- `desktop-agent` 默认优先读取 `MEETYOU_AGENT_ACCESS_TOKEN`，缺失时回退到 `MEETYOU_GATEWAY_ACCESS_TOKEN`
- `edge-agent` 默认优先读取 `MEETYOU_EDGE_ACCESS_TOKEN`，再回退到 `MEETYOU_AGENT_ACCESS_TOKEN` 与 `MEETYOU_GATEWAY_ACCESS_TOKEN`
- base URL 也支持按 runtime 覆盖：`desktop-agent` 使用 `MEETYOU_AGENT_BASE_URL`，`edge-agent` 优先使用 `MEETYOU_EDGE_BASE_URL`，再回退到共享 base URL 或配置文件
- 后续增强仍可考虑设备证书或 mTLS，但不属于当前正式主链要求

## 5. 会话与调用模型

Agent 协议不直接承载聊天 session，而是围绕 `operation` 和 `capability call` 工作。

补充原则：

- Agent 不理解 `execution_target` 这种高层路由意图
- `execution_target` 的解析、workspace 选路、fallback 决策与审批判断都在 Core 完成
- Agent 只接收已经被 Core 解析完成的 `capability.call.request`

### 5.1 关键标识

- `operation_id`：Core 侧操作对象 ID
- `call_id`：某次 capability 调用 ID
- `agent_id`：执行器 ID
- `workspace_id`：当前路由作用域

一个 operation 可以包含一个或多个 call。

## 6. 消息 Envelope

所有主协议消息采用统一 envelope：

```json
{
  "schema": "meetyou.agent.v1",
  "type": "agent.hello",
  "message_id": "msg_123",
  "sent_at": "2026-04-08T10:00:00Z",
  "agent_id": "desktop-main-agent",
  "correlation_id": "",
  "payload": {}
}
```

字段：

- `schema`：固定为 `meetyou.agent.v1`
- `type`：消息类型
- `message_id`：唯一消息 ID
- `sent_at`：发送时间
- `agent_id`：消息发送方 Agent
- `correlation_id`：关联请求 ID，可为空
- `payload`：消息体

## 7. Agent 连接生命周期

### 7.1 初始化

```text
Desktop Agent -> Core: agent.hello
Core -> Desktop Agent: agent.hello.ack
Desktop Agent -> Core: agent.capabilities.snapshot
Core -> Desktop Agent: agent.ready
```

### 7.2 运行中

- Agent 发送 `agent.heartbeat`
- Core 下发 `capability.call.request`
- Agent 回传 `accepted/progress/result/error`

补充：

- Core 可在 `agent.hello.ack` 中下发新的 `heartbeat_interval_seconds`
- Agent runtime 收到后应立即重排当前 heartbeat loop，而不是等待旧间隔自然耗尽
- 此 heartbeat 只服务 transport 保活、在线状态与运行指标，不承载 Heart 的时间感判断

### 7.3 回连

回连时可补发：

- 预留的离线补同步消息
- 最新 `agent.capabilities.snapshot`

## 8. Edge Profile 连接生命周期

当前 Edge Profile 与 Desktop Profile 共享同一套连接生命周期：

```text
Edge Agent -> Core: agent.hello
Core -> Edge Agent: agent.hello.ack
Edge Agent -> Core: agent.capabilities.snapshot
Core -> Edge Agent: agent.ready
```

运行中：

- Agent 发送 `agent.heartbeat`
- Core 下发 `capability.call.request`
- Agent 回传 `accepted/progress/result/error`

说明：

- `transport_profile=edge_wss` 只表示运行形态，不引入第二套 envelope
- 如果未来真的需要弱联网拉模式，应作为同一 Agent 协议上的后续扩展，而不是当前主链假设
- 当前 `F93` 的最小能力扩展基线以低风险 capability 样例和稳定性测试为主，例如 `utility.echo`

## 9. 核心消息类型

### 9.1 `agent.hello`

```json
{
  "schema": "meetyou.agent.v1",
  "type": "agent.hello",
  "message_id": "msg_hello_1",
  "sent_at": "2026-04-08T10:00:00Z",
  "agent_id": "desktop-main-agent",
  "payload": {
    "agent_type": "desktop",
    "display_name": "Desktop Main Agent",
    "transport_profile": "desktop_wss",
    "owner_client_id": "desktop-app",
    "owner_client_type": "electron",
    "owner_client_display_name": "Desktop App",
    "workspace_ids": ["personal", "desktop-main", "study"],
    "host": {
      "hostname": "DESKTOP-01",
      "os": "windows",
      "arch": "x86_64"
    },
    "supports_offline_cache": true
  }
}
```

补充约定：

- `desktop-agent` 通常会携带 `owner_client_*`，用于表达它归属于某个具体桌面 Client
- `edge-agent` 一般不带这组字段，而是主要依赖 `agent_type=edge`、`transport_profile=edge_wss` 与 `workspace_ids`

### 9.2 `agent.hello.ack`

```json
{
  "schema": "meetyou.agent.v1",
  "type": "agent.hello.ack",
  "message_id": "msg_hello_ack_1",
  "sent_at": "2026-04-08T10:00:00Z",
  "payload": {
    "accepted": true,
    "registered_agent_id": "desktop-main-agent",
    "heartbeat_interval_seconds": 20,
    "requires_capability_snapshot": true
  }
}
```

字段约定：

- `accepted`：是否接受当前 Agent 身份与连接
- `registered_agent_id`：Core 侧认定的 agent 标识
- `heartbeat_interval_seconds`：当前连接应立即采用的 transport heartbeat 周期
- `requires_capability_snapshot`：是否要求重新上报 capability 快照

### 9.3 `agent.capabilities.snapshot`

```json
{
  "schema": "meetyou.agent.v1",
  "type": "agent.capabilities.snapshot",
  "message_id": "msg_caps_1",
  "sent_at": "2026-04-08T10:00:02Z",
  "agent_id": "desktop-main-agent",
  "payload": {
    "revision": 5,
    "capabilities": [
      {
        "capability_id": "agent.edge-1.math.add",
        "kind": "tool",
        "title": "Add Two Numbers",
        "tags": ["edge", "math", "deterministic"],
        "risk_level": "read",
        "requires_confirmation": false,
        "workspace_ids": ["home-lab"],
        "input_schema": {
          "type": "object",
          "properties": {
            "left": {"type": "number"},
            "right": {"type": "number"}
          },
          "required": ["left", "right"]
        },
        "output_schema": {
          "type": "object",
          "properties": {
            "summary": {"type": "string"},
            "result": {"type": "number"}
          },
          "required": ["summary", "result"]
        }
      },
      {
        "capability_id": "agent.desktop-main.file.write",
        "kind": "tool",
        "title": "Write Local File",
        "risk_level": "write",
        "requires_confirmation": true,
        "workspace_ids": ["desktop-main", "study"]
      }
    ]
  }
}
```

### 9.4 `agent.heartbeat`

```json
{
  "schema": "meetyou.agent.v1",
  "type": "agent.heartbeat",
  "message_id": "msg_hb_1",
  "sent_at": "2026-04-08T10:00:20Z",
  "agent_id": "desktop-main-agent",
  "payload": {
    "status": "ready",
    "metrics": {
      "cpu_percent": 12.5,
      "memory_percent": 44.1,
      "active_calls": 1,
      "offline_queue_size": 2
    }
  }
}
```

说明：

- 该消息表达的是 transport liveness 与运行时 metrics
- 常见指标包括 CPU、内存、活跃调用数与 `offline_queue_size`
- 它不直接表达 `Core Heart` 的 `pending_redelivery`、`awaiting_completion` 或逾期 follow-up 等时间压力

### 9.5 `capability.call.request`

```json
{
  "schema": "meetyou.agent.v1",
  "type": "capability.call.request",
  "message_id": "msg_call_req_1",
  "sent_at": "2026-04-08T10:01:00Z",
  "payload": {
    "operation_id": "op_123",
    "call_id": "call_123",
    "workspace_id": "desktop-main",
    "capability_id": "agent.desktop-main.file.write",
    "arguments": {
      "path": "C:/work/demo.txt",
      "content": "hello"
    },
    "approval": {
      "required": true,
      "approval_id": "approval_123",
      "approved": true
    },
    "timeout_seconds": 60,
    "attachment_inputs": [],
    "audit_context": {
      "principal_id": "self",
      "requested_by_client_id": "feishu-main",
      "reason": "User requested file update"
    }
  }
}
```

### 9.6 `capability.call.accepted`

```json
{
  "schema": "meetyou.agent.v1",
  "type": "capability.call.accepted",
  "message_id": "msg_call_accept_1",
  "sent_at": "2026-04-08T10:01:01Z",
  "agent_id": "desktop-main-agent",
  "correlation_id": "call_123",
  "payload": {
    "call_id": "call_123",
    "started_at": "2026-04-08T10:01:01Z"
  }
}
```

### 9.7 `capability.call.progress`

```json
{
  "schema": "meetyou.agent.v1",
  "type": "capability.call.progress",
  "message_id": "msg_call_progress_1",
  "sent_at": "2026-04-08T10:01:03Z",
  "agent_id": "desktop-main-agent",
  "correlation_id": "call_123",
  "payload": {
    "call_id": "call_123",
    "phase": "running",
    "detail": "Writing file content"
  }
}
```

### 9.8 `capability.call.result`

```json
{
  "schema": "meetyou.agent.v1",
  "type": "capability.call.result",
  "message_id": "msg_call_result_1",
  "sent_at": "2026-04-08T10:01:04Z",
  "agent_id": "desktop-main-agent",
  "correlation_id": "call_123",
  "payload": {
    "call_id": "call_123",
    "status": "succeeded",
    "result": {
      "written": true,
      "bytes": 5
    },
    "attachment_outputs": [],
    "finished_at": "2026-04-08T10:01:04Z"
  }
}
```

### 9.9 `capability.call.error`

```json
{
  "schema": "meetyou.agent.v1",
  "type": "capability.call.error",
  "message_id": "msg_call_error_1",
  "sent_at": "2026-04-08T10:01:04Z",
  "agent_id": "desktop-main-agent",
  "correlation_id": "call_123",
  "payload": {
    "call_id": "call_123",
    "status": "failed",
    "error": {
      "code": "path_not_allowed",
      "category": "authorization",
      "message": "Requested path is outside allowed roots",
      "retryable": false
    },
    "finished_at": "2026-04-08T10:01:04Z"
  }
}
```

### 9.10 `agent.offline.receipts`

Desktop Agent 回连后补同步离线执行结果摘要。

### 9.11 `agent.offline.attachments`

Desktop Agent 回连后补同步离线期间产生的附件引用。

## 10. 大附件传输

大附件不应通过 WSS 主消息通道传输。

统一模型：

1. Agent 向 Core 请求上传票据
2. Core 返回对象存储上传信息
3. Agent 直接上传到对象存储
4. Agent 回传 `attachment_ref`
5. Core 将附件引用附着到 operation 或消息流

`attachment_ref` 示例：

```json
{
  "attachment_id": "att_123",
  "kind": "image",
  "object_key": "ops/2026/04/08/att_123.png",
  "mime_type": "image/png",
  "size_bytes": 245120,
  "sha256": "..."
}
```

### 10.1 Tool / Capability 附件输出约定

当 tool 或 capability 产出文件时，结果 payload 应优先返回 `attachment_outputs`，而不是在 `result` 文本里嵌入临时链接。

示例：

```json
{
  "call_id": "call_123",
  "status": "succeeded",
  "result": {
    "summary": "report exported"
  },
  "attachment_outputs": [
    {
      "attachment_id": "att_uploaded",
      "file_name": "report.txt",
      "kind": "file",
      "mime_type": "text/plain",
      "size_bytes": 12,
      "lifecycle_policy": "normal"
    }
  ],
  "finished_at": "2026-04-08T10:01:04Z"
}
```

约定：

- tool / capability 本地原始输出可先带 `local_path`
- Desktop Agent runtime 负责在发送 `capability.call.result` 前完成 upload ticket / upload / complete，并把上传后的 attachment object 填回 `attachment_outputs`
- `result.summary` 用于状态摘要，`attachment_outputs` 用于结构化附件产物；两者职责不要混用

### 10.2 Core 归一化职责

Core 收到 `attachment_outputs` 后应：

- 校验 attachment 归属与权限
- 归一化为统一 attachment object view，供 operation / message / 管理页复用
- 避免把 Agent 侧本地路径、上传票据或对象存储内部键直接透出给 Client

### 10.3 状态反馈协同

Agent 侧状态反馈与附件输出应配合工作：

- `capability.call.progress` 用于表达上传前或处理中间态
- `capability.call.result` 中的 `result.summary` 用于给前端生成 operation `summary`
- 只有当 `attachment_outputs` 已完成上传并被 Core 接受后，用户面才应显示可下载附件对象
- 如果上传仍在进行，状态应继续停留在 operation 的 `phase/detail/summary`，而不是提前伪造下载入口

详细设计见 `docs/storage-and-binary-transfer.md`。

## 11. Desktop Agent 离线缓存

### 11.1 支持范围

Desktop Agent 支持局部离线任务缓存，但必须受本地策略限制。

可缓存：

- 已获批准的本地操作
- 本地定时触发的低风险动作
- 离线期间产生的附件与结果收据

### 11.2 不可缓存

- 未获审批的高风险操作
- 需要 Core 实时研究/记忆判断的复杂编排
- 需要全局状态一致性的写操作

### 11.3 回连同步

回连后 Agent 必须：

- 上传离线执行结果
- 上传附件引用
- 让 Core 统一补落审计与最终状态

## 12. 多 Workspace Agent Membership

协议允许一个 Agent 在 `agent.hello` 与 `capabilities.snapshot` 中声明多个 `workspace_ids`。

Core 在执行路由时仍要判断：

- 当前 workspace 是否允许该 Agent
- 当前 capability 是否在该 workspace 可用
- 当前审批与风险策略是否允许执行

## 13. Bridge Agent

Bridge Agent 代表可代管多个子设备的执行器。

示例能力命名：

- `agent.bridge-home.camera-01.capture`
- `agent.bridge-home.sensor-02.read`

Core 无需理解桥下子设备的底层协议，只消费 Bridge Agent 暴露出的 capability。

## 14. 取消与超时

Core 可发送：

- `capability.call.cancel`

Agent 可因以下原因返回失败：

- 超时
- 资源不可用
- 本地权限不足
- 路径 / 命令策略拒绝

## 15. 实施顺序

### Phase 1

- `agent.hello`
- `agent.capabilities.snapshot`
- `agent.heartbeat`
- Desktop Profile 基础通道

### Phase 2

- `capability.call.request`
- `accepted/progress/result/error`
- 对象存储附件通道

### Phase 3

- Edge Profile over `WSS /agent/ws`
- Edge Agent 最小运行时与测试基线
- Desktop 离线缓存补同步

当前验证建议：

- 协议/构造器基线：`tests/test_edge_agent_protocol.py`
- 运行时与 heartbeat 协商：`tests/test_edge_agent_runtime.py`
- Gateway 侧注册/调用联调：`tests/test_gateway_agent_api.py`

### Phase 4

- Bridge Agent
- 更细粒度的设备状态与附件流

## 16. 待决问题

- 是否需要为未来弱联网 transport profile 增加任务拉取机制。
- 离线缓存的本地加密与过期策略。
- 对象存储下载 URL 的时效与复用策略。
