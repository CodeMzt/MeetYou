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
- 查看 `user_todo` 与 `assistant_schedule` 两类任务结果
- 获取管理页所需的 workspace / procedure / operation / approval / pending human input 聚合数据

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
- `GET /client/workspaces/{workspace_id}/agents`
- `GET /client/tasks`
- `GET /client/memory/search`
- `POST /client/danxi/session/login`
- `GET /client/danxi/session`
- `PATCH /client/danxi/session/webvpn-cookie`
- `GET /client/danxi/profile`
- `GET /client/danxi/divisions`
- `GET /client/danxi/posts`
- `GET /client/danxi/posts/{hole_id}`
- `GET /client/danxi/posts/{hole_id}/floors`
- `POST /client/danxi/posts/{hole_id}/replies`
- `PATCH /client/danxi/floors/{floor_id}`
- `DELETE /client/danxi/floors/{floor_id}`
- `GET /client/danxi/posts/{hole_id}/summary`
- `GET /client/danxi/messages`
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

- `execution_target` 是路由策略枚举，不是“Agent 列表”接口
- Client 可以表达目标偏好，但不负责最终选路
- Core 必须在创建 `operation` 后完成 capability routing
- 当 `execution_target=specific_agent` 时，`target_agent_id` 为必填
- 当 `execution_target` 为其他值时，`target_agent_id` 不应再被当作正式必填字段
- 当 `execution_target` 为空时，Core 可回退到当前 workspace 的 `default_execution_target`

配套约定：

- `GET /client/workspaces/{workspace_id}/agents` 返回的是当前 workspace 下在线可路由的 Agent 列表
- Client 若需要显式展示或挑选目标 Agent，应使用该接口，而不是把 `execution_target` 当作候选节点集合

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
- Electron 独立“工作区与规程”管理页应复用这些字段作为真源，不应在前端维护第二套 workspace 治理状态

### 3.8 Task Surface And Heart Semantics

`task` 资源当前需要显式区分两个域：

- `user_todo`：用户自己的待办对象，可携带 deadline/priority 等语义，但不会因自然语言时间描述被 `Core Heart` 自动 claim
- `assistant_schedule`：助手拥有的定时编排对象，必须带 trigger 语义，会进入 `Core Heart` 的 `scheduler loop`，并在触发时创建或复用正式 operation

补充原则：

- `Core Heart` 是服务端时间编排中枢，不属于 Client 或 Agent transport surface
- `scheduler loop` 负责确定性的 claim / pre-create operation / control event
- `heartbeat reasoning loop` 负责根据 `pending_redelivery`、`awaiting_completion`、逾期 follow-up 等结构化状态判断是否存在时间压力
- `/agent/ws` 上的 `agent.heartbeat` 只负责 agent 在线状态与运行指标，不等同于上述 Heart 时间编排

### 3.9 Danxi Surface

Danxi 二阶段仍归属 `Client API`，但作为一组有明确安全边界的子域资源存在。

当前约定：

- Danxi 登录、会话状态、WebVPN cookie 更新、用户信息、帖子/楼层读取、回复编辑删除、AI 摘要与站内消息统一收口在 `/client/danxi/*`
- Danxi 独立窗口与 `danxi` mode 助手共享同一服务端 Danxi 会话，不允许前端和助手各自维护独立登录态真相源
- 非校园网访问按“先 1 秒直连探测，失败后 WebVPN URL 代理”执行；是否走 `webvpn` 由会话状态返回给 UI，而不是让前端自行猜测
- `POST /client/danxi/session/login` 与 `PATCH /client/danxi/session/webvpn-cookie` 只接受 `encrypted_credentials`；Electron main 在本地使用共享密钥和 purpose 派生 key 做 `aes-256-gcm` 加密封装，Gateway 缺少密文字段时直接拒绝请求，并且只在 purpose 匹配时解密
- 加密 purpose 当前固定为 `danxi.client.login.v1` 与 `danxi.client.webvpn_cookie.v1`；前后端不得随意复用或混用 purpose
- Danxi JWT、refresh token、WebVPN cookie 与必要用户资料会在服务端通过加密封装写入状态后端；恢复后的会话在首次读取时必须做一次低风险有效性校验，若确认过期、撤销或损坏则立即清理
- 日志、错误对象与调试输出不得暴露 email、password、cookie、token 等明文字段；测试与文档也应沿用 `encrypted_credentials` 口径，而不是示例化明文跨边界传输

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

语义细节见 `docs/agent-protocol-v1.md`。

## 6. Operator API

### 6.1 用途

面向：

- 部署与运维
- 配置管理
- Agent 管理
- 安全管理

补充原则：

- `GET /operator/source-profiles` 是 workspace source-profile 偏好的受控目录真源，UI 不应自行发明 profile 名
- `PATCH /operator/workspaces/{workspace_id}` 写入 `preferred_source_profiles` 与 `memory_ranking_policy` 时需要经过服务端校验

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

- `GET /client/attachments?owner_type=...&owner_id=...`
- `GET /client/attachments/{attachment_id}`
- `DELETE /client/attachments/{attachment_id}`
- `POST /client/attachments/upload-ticket`
- `PUT /client/attachments/upload/{ticket_id}`
- `POST /client/attachments/{attachment_id}/complete`
- `GET /client/attachments/{attachment_id}/download-ticket`
- `GET /client/attachments/content/{attachment_id}?ticket_id=...`

当前实现状态：

- `client` 侧 attachment 主链已落地
- `client` 侧已支持按 owner 列出、读取 metadata、删除 attachment，并返回 `created_at` / `updated_at` / `uploaded_at` / `completed_at` / `deleted_at` 等关键时间戳
- `agent` 侧 attachment uploader 已落地
- Core 已把 `list_attachments`、`read_attachment`、`delete_attachment` 作为助手工具暴露；工具应面向 attachment domain，而不是直接操作 object store 路径
- tool / capability 产出的附件应先进入 `attachment_outputs`，再由 Core 归一化为统一 attachment object view；Client UI 不应直接消费 Agent 原始 `local_path` 或临时下载链接
- Electron 独立“附件管理”页应复用同一套 attachment domain API、时间戳字段与 download ticket 逻辑

### 9.4 Attachment Object View

当前用户面在 message、operation 与管理页中应复用统一附件对象视图，而不是依赖 surface-specific payload。

建议字段：

- `attachmentId`
- `fileName`
- `kind`
- `mimeType`
- `sizeBytes`
- `downloadUrl`
- `lifecyclePolicy`

原则：

- `attachment` 资源是真相源，attachment object view 是给 Client UI 的稳定投影视图
- 同一个对象视图可被 message、operation、管理页复用，避免每个面各自拼装下载逻辑
- 下载仍必须通过 download ticket / 权限校验，而不是把对象存储路径直接暴露给 UI

## 10. 管理页与状态反馈

### 10.1 管理页职责

当前 Electron 独立“工作区与规程”窗口属于 Client 正式产品面的一部分，其职责包括：

- 展示当前 workspace 概览与治理字段
- 承接受控的 workspace 治理编辑，例如 source profile 偏好与 memory ranking policy
- 展示 procedure catalog、detail 与 thread 当前 procedure context
- 聚合当前 thread / workspace 下的运行中 operation、待审批与待补充输入状态

当前 Electron 独立“附件管理”页同样属于 Client 正式产品面的一部分，其职责包括：

- 按 owner 列出 attachment
- 展示 `created_at`、`uploaded_at`、`completed_at`、`deleted_at` 等关键时间戳
- 复用 download ticket / delete attachment 主链，而不是直接拼接对象存储地址

原则：

- 管理页是用户面，不是 operator / developer 面
- 它消费的仍然是 `client/*` 与必要的 `operator` 受控目录接口，不应回退到 `/runtime/debug`
- 管理页展示的状态必须与主窗口共享同一套 operation / approval / human input 真相源

### 10.2 状态反馈模型

当前前端状态反馈采用双层模型：

- 顶层反馈：`StatusIsland` 负责展示连接状态、思考中 / 工具调用中等全局即时反馈
- 执行态反馈：operation 列表负责展示 `status`、`phase`、`detail`、`tone`、`summary` 与 attachment object view
- 附件反馈：上传成功/失败等瞬时反馈由状态区承接，不再默认向聊天流插入“上传成功”类系统消息

原则：

- `StatusIsland` 只负责“当前系统大致在做什么”，不替代 operation 细节面
- operation 的 `tone/summary` 应来自服务端状态和归一化结果，而不是仅靠前端本地猜测
- 当附件尚未完成 upload / complete 时，反馈应停留在 operation 状态层，不应提前生成可下载 UI
- 独立附件管理页应复用同一套 attachment object view 与下载票据逻辑，而不是复制另一条附件模型

## 11. UI 覆盖原则

主 UI 需要覆盖的产品能力：

- threads / sessions / messages
- operations
- approvals
- workspaces
- tasks
- citations / attachments
- agent 在线状态摘要
- 独立管理页中的 workspace / procedure / pending state 聚合视图

主 UI 不需要默认覆盖：

- operator config
- developer diagnostics
- 原始 capability 矩阵

## 12. 对当前仓库的指导

- 现有 `gateway/api.py` 应逐步拆成四类 router，而不是继续堆在一份 API 文件里。
- 旧 `/inputs`、`/controls`、根 `/ws` 等迁移错误 surface 应单独放在 legacy 模块，不应继续混入正式 router 装配层。
- 前端 `useMeetYou` 应只消费 Client API。
- 配置中心、debug、runtime diagnostics 应从默认聊天路径中分离。
- 附件显示层应统一消费 attachment object view，而不是在 message / operation / 管理页各自定义不同下载结构。
- 管理页和主窗口的状态反馈应复用同一套 operation / approval / human input 数据模型。

## 13. 待决问题

- 是否要把 `thread event stream` 和 `operation event stream` 分成两条 WS 订阅。
- 飞书是否需要单独的审批摘要格式，以适配弱交互界面。
