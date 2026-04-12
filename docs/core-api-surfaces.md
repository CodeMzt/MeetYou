# MeetYou Core API Surfaces V2

## 1. 文档目的

本文档定义 Core Service 对外暴露的 API 面分层，避免再把用户接口、设备接口、运维接口、调试接口混在同一套 surface 中。

目标：

- Client、Agent、Operator、Developer 各走各的入口与鉴权模型
- 前端只依赖稳定用户面，不默认依赖调试面
- 让跨会话协作、审批、附件、Agent 调度都拥有清晰资源模型

## 2. 资源模型

V2 推荐的核心资源：

- `thread`
- `session`
- `message`
- `operation`
- `approval`
- `attachment`
- `workspace`
- `agent`
- `task`
- `memory`

## 3. Client API

### 3.1 用途

面向：

- Electron UI
- 飞书
- 未来手机 App

### 3.2 主要资源

- `threads`
- `sessions`
- `messages`
- `operations`
- `approvals`
- `attachments`
- `workspaces`
- `tasks`
- `memory`

### 3.3 关键能力

- 发送消息
- 创建或加入 thread
- 订阅 thread 事件流
- 发起 operation
- 查看 operation 进度、结果、附件
- 提交审批结果
- 切换 workspace
- 查看任务和记忆结果

### 3.4 建议端点轮廓

- `POST /client/threads`
- `POST /client/sessions`
- `POST /client/messages`
- `POST /client/operations`
- `GET /client/operations/{operation_id}`
- `POST /client/approvals/{approval_id}/decision`
- `GET /client/procedures`
- `GET /client/procedures/{procedure_id}`
- `GET /client/threads/{thread_id}/procedure-context`
- `PUT /client/threads/{thread_id}/pinned-procedure`
- `DELETE /client/threads/{thread_id}/pinned-procedure`
- `GET /client/workspaces`
- `GET /client/tasks`
- `GET /client/memory/search`
- `GET /client/ws`

### 3.5 关键原则

- 不暴露底层 capability 内部细节给普通用户面
- 不让前端默认依赖 `/runtime/debug`
- 飞书与 Electron 都属于 Client API，只是交互能力不同

### 3.6 Operation 路由语义

`POST /client/operations` 的正式执行目标枚举固定为：

- `core_only`
- `specific_agent`
- `workspace_any_agent`
- `prefer_agent_fallback_core`

原则：

- Client 可以表达目标偏好，但不负责最终选路
- Core 必须在创建 `operation` 后完成 capability routing
- 当 `execution_target=specific_agent` 时，`target_agent_id` 为必填
- 当 `execution_target` 为其他值时，`target_agent_id` 不应再被当作正式必填字段
- 当 `execution_target` 为空时，Core 可回退到当前 workspace 的 `default_execution_target`

补充约定：

- `capability_id` 既可以是具体 capability id，也可以是稳定的抽象 capability key
- 当传入抽象 capability key 时，Core 需要先完成 workspace 内候选 agent 选择，再解析为目标 agent 的具体 capability

补充约定：

- `procedure_call` 现在可以通过 `procedure_id` 推导 preferred capability ref，并进入同一套 capability routing 主链
- scheduled task 执行上下文也可以携带 preferred capability ref 与 routing preference，但当前仍由后台执行路径消费，而非经由 `client/operations` 直接创建

### 3.7 Workspace Surface

`GET /client/workspaces` 与 `GET /operator/workspaces` 当前至少应暴露：

- `workspace_id`
- `title`
- `description`
- `base_mode`
- `prompt_overlay`
- `default_execution_target`
- `capability_policy`
- `allowed_capability_ids`
- `preferred_agent_ids`
- `preferred_agent_types`
- `preferred_source_profiles`
- `agent_routing_policy`
- `memory_ranking_policy`
- `capability_routing_overrides`

补充原则：

- `base_mode` 是消息入口在未显式指定 mode 时的默认值
- `default_execution_target` 是 operation 入口在未显式指定执行目标时的默认值
- `prompt_overlay` 会进入 prompt 组装链路，作为 workspace policy 的一部分
- 当 workspace 启用 `capability_policy=allowlist` 时，显式 `capability_call` 必须满足 allowlist 约束
- 当 operation 使用 `workspace_any_agent` 时，Core 可依据 workspace `preferred_agent_ids` 与 owner-client affinity 自动补出目标 agent
- 当 workspace 配置 `preferred_agent_types` 与 `agent_routing_policy` 时，Core 会把这些字段纳入自动选路排序
- 当 workspace 配置 `preferred_source_profiles` 时，Core 会把这些来源偏好注入消息路由治理；procedure 的推荐来源仍优先于 workspace 偏好
- 当前 `memory_ranking_policy` 已公开为 workspace surface 字段；V1 仅支持 `workspace_first`
- 当 workspace 配置 `capability_routing_overrides` 时，Core 会对特定 capability ref/abstract key 优先应用 capability 级 override

## 4. 跨会话协作

这是 V2 的新增重点。

### 4.1 线程模型

- `thread` 是跨 session 的逻辑会话
- `session` 是某个具体 Client 的运行实例

### 4.2 操作模型

- `operation` 独立于某个具体 session
- 一个 operation 可以被多个 Client 观察

### 4.3 示例

用户在飞书发送：

- “去桌面电脑上执行某操作并回一张截图”

Core 将：

- 在当前 thread 下创建 operation
- 把 operation 路由到 Desktop Agent
- 把截图附件挂到 operation
- 把结果推送给飞书和桌面 UI 上关注该 thread 的 session

## 5. Agent API

### 5.1 用途

面向：

- Desktop Agent
- Edge Agent
- Bridge Agent

### 5.2 主要资源

- `agent registration`
- `capability snapshots`
- `capability calls`
- `offline receipts`
- `attachment upload tickets`

### 5.3 建议端点 / 通道轮廓

- `WSS /agent/ws`
- `POST /agent/register`
- `POST /agent/attachments/upload-ticket`
- `POST /agent/attachments/complete`
- `POST /agent/offline/receipts`
- MQTT topic: `meetyou/agents/{agent_id}/*`

语义细节见 `docs/agent-protocol-v1.md`。

## 6. Operator API

### 6.1 用途

面向：

- 部署与运维
- 配置管理
- Agent 管理
- 安全管理

### 6.2 主要资源

- `config`
- `health`
- `agent registry`
- `background jobs`
- `tokens`
- `audit logs`

### 6.3 建议端点轮廓

- `GET /operator/health`
- `GET /operator/config`
- `PATCH /operator/config`
- `GET /operator/source-profiles`
- `PATCH /operator/workspaces/{workspace_id}`
- `GET /operator/agents`
- `POST /operator/agents/{agent_id}/disable`
- `GET /operator/audit`

## 7. Developer API

### 7.1 用途

面向开发调试，不属于默认产品面。

### 7.2 主要资源

- `route decisions`
- `capability sets`
- `authorization previews`
- `request diagnostics`
- `usage snapshots`
- `compression snapshots`
- `checkpoints`

### 7.3 原则

- `/runtime/debug` 不再视作普通前端接口
- 默认主 UI 不应常态依赖 Developer API

## 8. 审批 API

审批属于 Client API 的重要资源，但本身是独立领域模型。

### 8.1 审批流

1. Core 创建 `approval`
2. 一个或多个 Client 收到审批请求
3. 某个具备权限的 Client 提交决策
4. Core 决定放行、拒绝或超时关闭

补充原则：

- WebSocket 中的 `confirm.requested` / `confirm.resolved` 只是投递事件，不是真相源
- 真相源始终是 `approval` 与 `operation` 资源

### 8.2 聊天确认流与 Approval 对齐

为兼容现有客户端交互，聊天确认仍保留 `confirm.requested` / `confirm.resolved` 事件协议；
但该协议下的确认请求与确认决策已要求关联正式 `Approval` 资源。

补充约定：

- `confirm.requested` 可携带 `approval_id`、`approval_status`、`approval_type`、`risk_level`、`operation_id`
- `POST /client/sessions/{session_id}/confirm-response` 用于以资源语义提交确认结果，避免仅依赖 websocket 动作语义
- websocket `confirm_response` 仍保留兼容，但后续会逐步收敛为资源语义入口优先
- `POST /client/approvals/{approval_id}/decision` 现已成为聊天确认 approval 的首选决策入口

补充约定：

- 共享 client SDK / adapter 应优先调用资源语义入口，而不是 websocket action
- Feishu / CIL 等 channel adapter 也应复用共享 client SDK 的资源语义方法
- 本地兼容 adapter / route 如仍需桥接到 EventBus，应优先通过统一交互响应服务，而不是直接调用 `EventBus.submit_*`
- 本地兼容 adapter / route 如需读取 pending 状态，也应优先通过统一交互响应服务，而不是直接读取 `EventBus` 内部字段

### 8.4 Procedure Read-Only Surface And Governance Callback

- `GET /client/procedures` 返回可见 procedure catalog 的摘要列表
- `GET /client/procedures/{procedure_id}` 返回 procedure 内容视图需要的完整字段，例如 `prompt_overlay`、`recommended_source_profiles` 与 routing 偏好
- `GET /client/threads/{thread_id}/procedure-context` 返回 thread 当前的 `pinned_procedure`、最近一次 `latest_inferred_procedure`、当前 `effective_procedure` 以及来源 `source`
- `PUT /client/threads/{thread_id}/pinned-procedure` 与 `DELETE /client/threads/{thread_id}/pinned-procedure` 用于用户显式固定 / 取消固定当前 thread 的 procedure
- AI 发起的 Procedure `create / update / delete` 仍通过确认回调治理；当前实现复用现有 confirmation + approval 主链，而不是为 procedure 再单独引入第二套确认协议

### 8.3 Human Input 提交

- `human_input.requested` / `human_input.resolved` 事件协议继续保留
- `POST /client/sessions/{session_id}/human-input-response` 现已成为补充输入的首选提交入口
- websocket `input_response` 仍保留兼容，但不再是首选资源入口

补充约定：

- 共享 client SDK / adapter 应优先调用 `POST /client/sessions/{session_id}/human-input-response`
- Feishu / CIL 等 channel adapter 也应复用共享 client SDK 的资源语义方法
- 本地兼容 adapter / route 如仍需桥接到 EventBus，应优先通过统一交互响应服务，而不是直接调用 `EventBus.submit_*`
- 本地兼容 adapter / route 如需读取 pending 状态，也应优先通过统一交互响应服务，而不是直接读取 `EventBus` 内部字段

### 8.2 高风险审批来源

V2 允许：

- Electron UI 审批高风险动作
- 飞书审批高风险动作

前提是该 Client 具备高风险审批权限。

## 9. 附件 API

### 9.1 原则

- 小文本可直接走主协议
- 大附件只走对象存储通道
- Client 与 Agent 都通过 Core 申请对象存储票据

### 9.2 附件资源

- `attachment`
- `attachment_upload_ticket`
- `attachment_download_ticket`

### 9.3 建议端点轮廓

- `POST /client/attachments/upload-ticket`
- `PUT /client/attachments/upload/{ticket_id}`
- `POST /client/attachments/{attachment_id}/complete`
- `GET /client/attachments/{attachment_id}/download-ticket`
- `GET /client/attachments/content/{attachment_id}?ticket_id=...`

当前实现状态：

- `client` 侧 attachment 主链已落地
- `agent` 侧 attachment uploader 仍属于下一批

## 10. UI 覆盖原则

主 UI 需要覆盖的产品能力：

- threads / sessions / messages
- operations
- approvals
- workspaces
- tasks
- citations / attachments
- agent 在线状态摘要

主 UI 不需要默认覆盖：

- operator config
- developer diagnostics
- 原始 capability 矩阵

## 11. 对当前仓库的指导

- 现有 `gateway/api.py` 应逐步拆成四类 router，而不是继续堆在一份 API 文件里。
- 前端 `useMeetYou` 应只消费 Client API。
- 配置中心、debug、runtime diagnostics 应从默认聊天路径中分离。

## 12. 待决问题

- 是否要把 `thread event stream` 和 `operation event stream` 分成两条 WS 订阅。
- 飞书是否需要单独的审批摘要格式，以适配弱交互界面。
