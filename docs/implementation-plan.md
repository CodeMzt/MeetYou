# MeetYou V2 Implementation Plan

## 1. 目的

本文档是 MeetYou V2 的统一实施计划书，服务于后续 coding、测试、任务编排和阶段验收。

它覆盖：

- 服务器本体 / 多客户端 / 客户端内本地后端 / workspace 节点治理 的总体构建顺序
- 各阶段任务拆分与 feature 拆分
- 任务依赖关系
- 测试依赖关系
- 文档依赖关系
- 每个阶段的交付物和验收条件

本文档不是目标架构说明书，而是执行入口文档；默认执行粒度以 feature 为主，再下钻到 task。

## 2. 相关设计文档

实施时以以下文档为真源：

- `docs/core-client-agent-architecture.md`
- `docs/workspace-capability-model.md`
- `docs/agent-protocol-v1.md`
- `docs/core-api-surfaces.md`
- `docs/storage-and-binary-transfer.md`

现状盘点、旧功能映射与后续阶段安排，补充见：

- `docs/server-centric-migration-baseline.md`

阅读顺序建议：

1. `core-client-agent-architecture.md`
2. `workspace-capability-model.md`
3. `core-api-surfaces.md`
4. `agent-protocol-v1.md`
5. `storage-and-binary-transfer.md`

## 3. 总体目标

V2 的最终目标是：

- 把当前单体本地助手演进为“服务器本体 + 多客户端（其中部分客户端内含本地后端）+ workspace 节点治理”体系
- 让服务器成为唯一真相源
- 让 PC 客户端中的本地执行能力从 Core 剥离为客户端内本地后端
- 让各客户端的交互前端从开发态聊天壳演进为稳定 Client UI
- 为未来 Edge Agent / MQTT transport / workspace 协调打通基础模型

### 3.1 第一版基本可用产品目标

当前阶段的直接产品目标，不是把全部远期能力一次性做完，而是做出“第一版基本可用产品”。

这版产品的定义是：

- 你可以把 Core Service 部署到私人服务器，作为唯一真相源长期运行
- 你可以从至少一个稳定 Client（当前以 Electron PC 端为主）连接并持续使用
- 你可以通过至少一个本地 Agent（当前以 Desktop Agent 为主）执行本地文件/命令/MCP 等能力
- Workspace、Approval、Operation、Procedure、Task 至少形成一条可持续使用、可审计、可调试的主链
- 常见交互 pending（confirm / human input）优先通过资源语义入口提交，而不是依赖临时 transport action

### 3.2 第一版完成判定

当以下条件同时成立时，可认为“第一版基本可用产品”达到完成标准：

1. `Core Service`
- 可稳定启动并作为唯一真相源运行
- `thread/session/operation/approval/workspace/agent/procedure` 资源主链可用

2. `Client`
- Electron 可通过 `client/* + client/ws` 完成聊天、审批、Procedure 执行、任务查看等基本使用链路
- 主要交互 pending 已优先走资源语义入口

3. `Agent`
- Desktop Agent 可完成 capability 上报、调用、结果回传
- 本地文件/命令/MCP 已不再要求 Core 直接执行

4. `Workspace 治理`
- 已具备默认 mode、默认执行目标、capability allowlist、agent routing policy、capability routing override
- 这些治理字段确实参与主链，而不只是展示配置

5. `后台任务`
- scheduled task 和 scheduled reminder 已进入 operation 主链
- task 快照可追踪最近一次 operation 标识与状态

6. `可验证性`
- 后端关键主链具备测试覆盖
- 前端 `typecheck` 和测试可通过

当前判定：已达成。

判定依据：

- Core Service 已稳定承接 `thread/session/operation/approval/workspace/agent/procedure`
- Electron、CIL、Feishu formal client chain 已进入统一 `client/* + client/ws` 主链
- Desktop Agent 已可上报 capability、执行本地能力并回传结果
- Workspace 治理字段已真实参与主链
- scheduled task / scheduled reminder 已进入 operation 主链
- 关键后端测试、前端 `typecheck` 与测试均可通过

### 3.3 第一版暂不要求

以下内容不是第一版基本可用产品的完成前置条件：

- Edge Agent / MQTT 全量落地
- Mobile client
- 附件/对象存储完整产品化
- EventBus 内部等待机制彻底替换
- Task 调度器完全演化为 operation 原生创建者

## 4. 总体实施策略

### 4.1 核心原则

- 先立模型，再迁接口，再剥执行器，再收 UI
- 先引入新模型，不急着一次性删除旧路径
- 每个阶段都要保证主分支可运行
- 高风险重构必须有可验证的中间状态
- `Phase` 用于表达依赖和里程碑，`feature` 用于表达默认代码管理单元

### 4.2 主线顺序

```text
Phase 0  文档收口与基线确认
Phase 1  Core 数据模型与持久化骨架
Phase 2  Core API 分层与新资源骨架
Phase 3  Thread / Session / Operation / Approval 主链打通
Phase 4  PC 客户端内本地后端最小运行时
Phase 5  本地工具从 Core 剥离到客户端内本地后端
Phase 6  Frontend 迁移到 Client API
Phase 7  附件通道与对象存储
Phase 8  Workspace / Memory / Procedure 收口
Phase 9  Edge Agent MQTT 基础设施
Phase 10 清理旧路径与稳定化
```

当前已确认的下一阶段推进顺序补充如下：

1. 先执行 legacy/spec 文档清理，并统一 `mode`、`execution_target`、审批与会话相关术语，避免继续在错误模型上叠加实现
2. 再收口 Phase 3 与 Phase 8 之间仍未统一的核心模型，重点是 approval 主链、session 真相源、workspace 治理边界
3. 在核心模型一致后推进 Phase 7 附件闭环，补齐 upload ticket / complete / download 主链
4. 最后再启动 Phase 9 Edge Agent / MQTT，避免边缘接入与主链收口交叉放大复杂度

### 4.3 当前已冻结决策

当前实施批次已经冻结以下公开语义，后续开发默认按此执行：

- 用户态 mode 固定为：`general`、`research`、`documents`、`study`、`automation`
- `auto`、`normal`、`office` 不再作为公开产品枚举继续扩散；现阶段仅允许作为内部 legacy 映射存在
- `execution_target` 固定为：`core_only`、`specific_agent`、`workspace_any_agent`、`prefer_agent_fallback_core`
- `assistant`、`core`、`desktop` 不再作为正式执行目标枚举继续扩散；仅允许在兼容层做一次性映射
- Feishu 旧 event bus fallback 进入待删除路径，不再视为正式主链
- 正式服务端持久化依赖为 PostgreSQL，不再把文件型状态视为正式运行选项

### 4.4 当前执行批次

本轮执行先做 Phase 0.5，目标是把公开语义和后续阶段入口固定下来：

1. 把重构计划同步到 `docs/` 真源文档
2. 统一公开 `mode` 与 `execution_target` 枚举
3. 为当前 legacy 内核增加过渡映射层，避免 UI 与 API 继续向旧语义漂移
4. 在完成这批收口后，再进入 approval / session / workspace 主链重构

当前状态：已完成。

本批次已落地：

- 文档真源已同步到 `implementation-plan.md`、`server-centric-migration-baseline.md`、`workspace-capability-model.md`、`core-api-surfaces.md`、`agent-protocol-v1.md`
- Client API、Procedure 种子数据和 Electron 主入口已改用新的公开枚举
- Core 已增加 public-to-legacy mode 过渡映射层

下一批进入条件：

1. 正式设计 approval 前置到 operation 的主链
2. 收口 session 真相源
3. 开始 workspace 治理层重构

### 4.5 当前执行批次：Approval 前置到 Operation

本轮进入 Phase 3 的第一批真实收口，范围限定为“显式 `POST /client/operations` 主链”。

本批次目标：

1. 对显式 operation 建立风险判断
2. 对需要确认的 operation 先创建 `approval`
3. 在审批通过后再执行 agent dispatch
4. 保持聊天内工具确认流暂不改动，避免把 `EventBus` 临时流与 operation 主链一次性混改

本批次完成条件：

- `operation` 可进入 `waiting_approval`
- `approval` 决策后可驱动 operation 继续 dispatch 或结束
- 文档与测试同步更新

当前状态：已完成。

本批次已落地：

- `POST /client/operations` 在显式 agent capability 调用场景下，已接入基于 capability 风险的审批前置
- 高风险 operation 会先进入 `waiting_approval`
- `POST /client/approvals/{approval_id}/decision` 已能驱动 operation 进入 dispatch 或 reject 终态
- Electron 操作面板已能直接对 pending approval 执行批准/拒绝

下一批进入条件：

1. 收口数据库 session 与运行时 `SessionManager` 的双模型
2. 确定 `SessionManager` 仅保留 transport/runtime registry 职责
3. 把会话真相源彻底迁回数据库与 thread/session 资源

### 4.6 当前执行批次：Session 真相源收口

本轮进入下一批主链收口，目标是把数据库 session 与运行时 registry 明确分层。

本批次目标：

1. 把 `SessionManager` 收口为 runtime registry，不再负责生成或决定会话主键
2. 让 `Client API` 路径优先以数据库 `session` 为真相源
3. 让 `/client/ws` 命令在存在 `core_domain` 时校验 session-thread 归属关系
4. 保留无 `core_domain` 的测试和 legacy 路径最小兼容

本批次完成条件：

- `SessionManager` 只能基于显式 `session_id` 建立运行时绑定
- `get_runtime_usage()` 在数据库 session 已存在但 runtime 未绑定时仍可返回估算快照
- `/client/ws` 不再接受跨 thread 的 session 命令

当前状态：已完成。

本批次已落地：

- `SessionManager` 已改为显式 `bind_runtime_session()` 语义，旧方法只保留兼容别名
- `POST /client/messages` 与 `client/ws` 命令处理已改为显式登记 runtime session 绑定
- `Client API` WebSocket 命令在 `core_domain` 存在时会校验数据库 session 属于当前 thread
- `App.get_runtime_usage()` 已优先基于数据库 session 判断会话存在性，不再强依赖 runtime binding

下一批进入条件：

1. 继续收口聊天内工具确认流到正式 `Approval` 模型
2. 开始把 workspace prompt/capability/execution overlay 提升为真正治理层
3. 评估并下线剩余 legacy session/path 兼容点

### 4.7 当前执行批次：聊天确认流并入 Approval

本轮收口目标是把聊天内 `confirm.requested/confirm.resolved` 从 `EventBus` 临时请求模型，升级为可审计的正式 `Approval` 主链。

本批次目标：

1. 在聊天确认请求触发时创建正式 `approval`
2. 在确认响应时同步更新 `approval` 决策状态
3. 保持现有事件协议兼容（`confirm.requested` / `confirm.resolved` 不直接下线）
4. 在不重写 Brain/Tool 机制的前提下，先完成最小可审计闭环

本批次完成条件：

- 聊天确认请求可关联 `approval_id`
- 确认决策能回写 `approval` 表
- 前端确认交互可携带并保留 `approval_id`
- 测试覆盖确认流的 approval 创建与决策回写

当前状态：已完成。

本批次已落地：

- 聊天确认请求触发时会创建正式 `operation + approval` 上下文，并与 `request_id` 建立关联
- 确认决策会回写 `approval` 状态，并同步更新关联 operation 终态
- `confirm.requested` / `confirm.resolved` 已可携带 approval 关联字段，维持现有事件协议兼容
- 新增 `POST /client/sessions/{session_id}/confirm-response` 资源语义入口，前端默认优先走该入口

下一批进入条件：

1. 清理确认流中仍依赖 `EventBus` 临时 pending 的分支
2. 开始 workspace 治理层（prompt/capability/execution overlay）的主链收口
3. 对齐 Feishu/CIL 的确认入口到资源语义优先

### 4.8 当前执行批次：Workspace 治理层第一批

本轮收口目标是让 workspace 开始真正影响请求处理，而不是仅作为列表与标签存在。

本批次目标：

1. 让 `workspace.base_mode` 在消息入口缺省时自动生效
2. 让 `workspace.default_execution_target` 在操作入口缺省时自动生效
3. 让 `workspace.prompt_overlay` 正式进入 prompt 组装链路
4. 扩展 workspace API / 存储字段，使上述治理信息成为正式 surface

本批次完成条件：

- `client/workspaces` 与 `operator/workspaces` 返回完整治理字段
- 未显式指定 `preferred_mode` 的消息会继承 workspace base mode
- 未显式指定 `execution_target` 的 operation 会继承 workspace 默认执行目标
- prompt 组装阶段可感知 workspace policy

当前状态：已完成。

本批次已落地：

- workspace 默认资料已扩展为 `description`、`prompt_overlay`、`default_execution_target`
- `client/workspaces` 与 `operator/workspaces` 已返回上述治理字段
- 未显式指定 `preferred_mode` 的消息会继承 workspace `base_mode`
- 未显式指定 `execution_target` 的 operation 会继承 workspace `default_execution_target`
- prompt 组装链路已可感知 workspace policy

下一批进入条件：

1. 开始 workspace capability overlay / allowlist 的主链收口
2. 评估并实现 workspace 级 agent 选择偏好与 routing 策略
3. 继续清理确认流中仍依赖 `EventBus` 临时 pending 的分支

### 4.9 当前执行批次：Workspace Capability Overlay / Allowlist

本轮目标是让 workspace 不只是提供默认值，而是开始约束显式 capability 调用边界。

本批次目标：

1. 为 workspace 引入 capability allowlist / overlay 视图
2. 在显式 operation 创建时校验 capability 是否被当前 workspace 允许
3. 把 workspace capability 策略暴露到 operator / client workspace surface
4. 为后续 agent routing 治理保留 capability 优先级与 workspace 策略入口

本批次完成条件：

- workspace 可以声明 `capability_policy` 与 `allowed_capability_ids`
- 显式 capability operation 会校验 workspace allowlist
- API 与测试同步更新

当前状态：已完成。

本批次已落地：

- workspace 已可通过 `capability_policy` 与 `allowed_capability_ids` 声明 capability allowlist
- `client/workspaces` 与 `operator/workspaces` 已公开 workspace capability 治理字段
- 显式 `capability_call` operation 已接入 workspace allowlist 校验
- 当 workspace 启用 allowlist 时，缺少 `capability_id` 的 `capability_call` 将被拒绝

下一批进入条件：

1. 评估并实现 workspace 级 agent 选路治理与 capability 优先级
2. 继续清理确认流中仍依赖 `EventBus` 临时 pending 的分支
3. 开始把 workspace capability overlay 从 allowlist 扩展到更完整的 routing policy

### 4.10 当前执行批次：Workspace Agent 选路治理

本轮目标是让 workspace 不只决定默认执行目标和 capability allowlist，还能开始影响“由哪台 agent 执行”。

本批次目标：

1. 让显式 capability operation 支持 `workspace_any_agent` 自动选路
2. 让 `prefer_agent_fallback_core` 在 agent 不可用时具备明确降级行为
3. 为 workspace 引入最小 agent routing 偏好字段
4. 把选路结果回写到 operation metadata 与事件流，便于审计和 UI 展示

本批次完成条件：

- `workspace_any_agent` 可基于 capability + workspace + agent 状态自动选定目标 agent
- workspace 可声明最小 routing 偏好并参与排序
- 显式 operation 的选路结果可在 operation 响应与事件中观察到

当前状态：已完成。

本批次已落地：

- workspace 已支持最小 agent routing 偏好字段 `preferred_agent_ids`
- 显式 operation 现已支持 `workspace_any_agent` 自动选路
- 当 workspace 默认执行目标为 `specific_agent` 且客户端未显式指定 target 时，系统会按 workspace 选路补出目标 agent
- `prefer_agent_fallback_core` 在无可用 workspace agent 时会显式降级为 `core_only`，并在 operation metadata 中记录 routing reason

下一批进入条件：

1. 继续压缩确认流中对 `EventBus` 临时 pending 的依赖
2. 把 workspace capability overlay 从 allowlist 扩展到更完整的 routing / preference policy
3. 开始为 capability 层引入更稳定的跨 agent 抽象能力命名，而不只是 agent-specific capability id

### 4.11 当前执行批次：聊天确认决策收口到 Approval 资源

本轮目标是继续压缩聊天确认流对 `EventBus` 临时 pending 接口的直接依赖，让确认决策优先通过正式 `Approval` 资源驱动。

本批次目标：

1. 让 `POST /client/approvals/{approval_id}/decision` 可直接处理聊天确认类 approval
2. 让 approval 决策能够恢复或终止对应的确认等待，而不必依赖单独的确认提交入口
3. 保留现有 `confirm.requested / confirm.resolved` 和 `confirm-response` 兼容面，但让它们退居次级路径
4. 把确认决策结果继续同步回 approval / operation / 事件流

本批次完成条件：

- 聊天确认 approval 可以通过 `approval decision` 主入口直接处理
- 决策后能够恢复或拒绝待确认执行链路
- 测试覆盖 approval 决策驱动的聊天确认闭环

当前状态：已完成。

本批次已落地：

- `POST /client/approvals/{approval_id}/decision` 现在可以直接处理 `chat_confirmation` 类型的 approval
- 聊天确认的批准/拒绝已不再必须依赖专用 `confirm-response` 入口
- `confirm-response` 与 websocket `confirm_response` 仍保留兼容路径，但已退居次级入口
- 拒绝原因现在会随确认决策一并回写到后端确认链路

下一批进入条件：

1. 把 workspace capability overlay 从 allowlist 扩展到更完整的 routing / preference policy
2. 开始为 capability 层引入更稳定的跨 agent 抽象能力命名
3. 继续清理剩余依赖 `EventBus` 临时 pending 暴露面的交互分支

### 4.12 当前执行批次：Workspace Routing / Preference Policy 第一批

本轮目标是把 workspace 的 agent 选路从“少量列表偏好”推进到“可配置的排序策略”。

本批次目标：

1. 为 workspace 引入最小 routing policy 字段
2. 为 workspace 引入 agent type 偏好字段
3. 把 routing policy 接入 `workspace_any_agent` 与默认 `specific_agent` 自动选路
4. 保持现有 `preferred_agent_ids` 兼容，并纳入统一排序体系

本批次完成条件：

- workspace 可以声明 `agent_routing_policy`
- workspace 可以声明 `preferred_agent_types`
- 显式 operation 的自动选路会按 policy + preferred_agent_ids + preferred_agent_types + owner affinity 排序
- API 与测试同步更新

当前状态：已完成。

本批次已落地：

- workspace 已支持 `agent_routing_policy`
- workspace 已支持 `preferred_agent_types`
- `workspace_any_agent` 与默认 `specific_agent` 自动选路已接入 policy + preferred_agent_ids + preferred_agent_types + owner affinity 的统一排序
- `strict_preferred` 与 `prefer_owner_client` 已具备真实行为

下一批进入条件：

1. 开始为 capability 层引入更稳定的跨 agent 抽象能力命名
2. 继续清理剩余依赖 `EventBus` 临时 pending 暴露面的交互分支
3. 评估 workspace routing policy 是否需要进一步扩展到 capability 级偏好策略

### 4.13 当前执行批次：跨 Agent Capability 抽象命名

本轮目标是让显式 operation 不再只能引用某一台 agent 的具体 capability id，而可以使用稳定的抽象能力名。

本批次目标：

1. 为 agent capability 引入 `abstract_capability_key`
2. 让显式 operation 在保留 `capability_id` 字段名的前提下，同时支持“具体 capability id 或抽象 capability key”
3. 让 workspace 自动选路可基于抽象 capability key 选择匹配 agent 的具体 capability
4. 保持现有 agent-specific capability id 完全兼容

本批次完成条件：

- capability 可声明抽象 key
- 显式 operation 可用抽象 key 进入主链
- 自动选路可将抽象 key 解析到实际 agent capability
- API 与测试同步更新

当前状态：已完成。

本批次已落地：

- agent capability 现已支持声明 `abstract_capability_key`
- 显式 operation 在保留 `capability_id` 字段名的前提下，已经支持“具体 capability id 或抽象 capability key”
- workspace 自动选路现在可以先按抽象 key 找到候选 agent，再解析成目标 agent 的具体 capability
- 现有 agent-specific capability id 完全保留兼容

下一批进入条件：

1. 继续清理剩余依赖 `EventBus` 临时 pending 暴露面的交互分支
2. 评估 capability 级 routing / preference policy 是否需要单独建模
3. 逐步把更多显式 operation 与 procedure 收口到抽象 capability key 语义

### 4.14 当前执行批次：Human Input 资源语义入口

本轮目标是继续减少上层对 `EventBus` 交互动作的直接依赖，让补充输入优先通过资源语义入口提交。

本批次目标：

1. 新增 `human input` 的资源语义提交入口
2. 让前端优先通过 HTTP 资源入口提交补充输入
3. 保留 websocket `input_response` 兼容路径，但让它退居次级入口
4. 维持现有 human input 请求事件协议不变

本批次完成条件：

- 存在 `POST /client/sessions/{session_id}/human-input-response`
- 前端优先走资源语义提交路径
- human input 的兼容 websocket 入口仍可用
- API 与测试同步更新

当前状态：已完成。

本批次已落地：

- 新增 `POST /client/sessions/{session_id}/human-input-response`
- 前端 human input 提交已优先走 HTTP 资源入口，失败后再回退 websocket
- `input_response` 兼容路径仍保留

下一批进入条件：

1. 评估 capability 级 routing / preference policy 是否需要单独建模
2. 继续清理剩余依赖 `EventBus` 临时 pending 暴露面的交互分支
3. 逐步把更多交互型 pending request 收口到资源语义入口

### 4.15 当前执行批次：Capability 级 Routing / Preference Policy 第一批

本轮目标是在 workspace 全局选路策略之外，再提供按 capability 维度覆写选路策略的能力。

本批次目标：

1. 为 workspace 引入 `capability_routing_overrides`
2. 让显式 operation 在按抽象 capability key 或具体 capability id 选路时，可命中 capability 级 override
3. 让 capability 级 override 能覆写 workspace 级 `preferred_agent_ids`、`preferred_agent_types`、`agent_routing_policy`
4. 保持现有 workspace 全局选路策略完全兼容

本批次完成条件：

- workspace 可声明 capability 级 routing override
- 自动选路会优先应用 capability override，再回退 workspace 全局策略
- API 与测试同步更新

当前状态：已完成。

本批次已落地：

- workspace 已支持 `capability_routing_overrides`
- capability 级 override 已可覆写 workspace 全局 `preferred_agent_ids`、`preferred_agent_types`、`agent_routing_policy`
- 显式 operation 的自动选路已优先应用 capability override，再回退 workspace 全局策略

下一批进入条件：

1. 继续清理剩余依赖 `EventBus` 临时 pending 暴露面的交互分支
2. 逐步把更多交互型 pending request 收口到资源语义入口
3. 评估是否需要把 procedure/task 也接入 capability 级 routing policy

### 4.16 当前执行批次：客户端交互资源化收口第一批

本轮目标是把客户端侧剩余的交互 pending 响应从 websocket action 优先，收口为 HTTP 资源入口优先。

本批次目标：

1. 为 `GatewayConversationClient` 增加确认与补充输入的资源语义提交方法
2. 让 CIL 优先走资源语义入口提交 confirm / human input 响应
3. 保留 websocket `send_command()` 回退路径，避免一次性切断兼容面
4. 对齐测试与文档，明确 websocket action 已退居兼容层

本批次完成条件：

- `GatewayConversationClient` 可直接提交 confirm / human input 资源请求
- CIL 不再默认用 websocket action 提交交互响应
- 回退路径仍可用

当前状态：已完成。

本批次已落地：

- `GatewayConversationClient` 已支持直接提交 confirm / human input 资源请求
- CIL 现在优先走资源语义入口提交 confirm / human input 响应
- websocket `send_command()` 仍保留为兼容回退路径

下一批进入条件：

1. 继续清理剩余依赖 `EventBus` 临时 pending 暴露面的交互分支
2. 逐步把更多交互型 pending request 收口到资源语义入口
3. 评估是否需要让 Feishu / 其他 channel adapter 同样优先走资源入口

### 4.17 当前执行批次：Adapter 交互资源化第二批

本轮目标是在 CIL 之外，把 Feishu / channel adapter 的交互 pending 响应也收口到资源语义入口优先。

本批次目标：

1. 让 Feishu / gateway adapter 优先调用 confirm / human input 的 HTTP 资源入口
2. 保留 EventBus 与 websocket 动作面的兼容回退路径
3. 继续减少上层 adapter 直接依赖 `EventBus.submit_*` 的场景
4. 对齐测试与文档，明确 adapter 侧也进入资源语义优先阶段

本批次完成条件：

- Feishu / gateway adapter 优先走资源入口提交交互响应
- 兼容回退路径仍可用
- 测试覆盖 adapter 层的资源入口优先行为

当前状态：已完成。

本批次已落地：

- Feishu / gateway adapter 现在优先走资源语义入口提交 confirm / human input 响应
- `GatewayConversationClient` 的 confirm / human input 资源方法已在 CIL 与 Feishu formal chain 中复用
- EventBus 直提交与 websocket action 均保留为兼容回退路径

下一批进入条件：

1. 继续清理剩余依赖 `EventBus` 临时 pending 暴露面的交互分支
2. 逐步把更多 adapter / channel 也收口到资源语义入口
3. 评估 procedure/task 是否需要接 capability 级 routing policy

### 4.18 当前执行批次：交互响应服务化收口

本轮目标是把本地 adapter 与 gateway route 对 `EventBus.submit_*` 的直接依赖收进统一服务层，而不是继续让上层组件直接碰 `EventBus`。

本批次目标：

1. 引入统一的交互响应服务 façade
2. 让 gateway route、CLI adapter、本地 Feishu 兼容链路统一通过服务层提交 confirm / human input 响应
3. 保留 EventBus 等待机制本身，但把直接提交接口尽量下沉到服务层后面
4. 对齐测试与文档，明确上层 adapter / route 不再直接依赖 `EventBus.submit_*`

本批次完成条件：

- 存在统一交互响应服务
- gateway / CLI / 本地 Feishu fallback 不再直接调用 `EventBus.submit_*`
- 测试覆盖服务层和主要适配点

当前状态：已完成。

本批次已落地：

- 新增 `InteractionResponseService`
- gateway route、CLI adapter、本地 Feishu 兼容链路已统一通过服务层提交交互响应
- 服务层已兼容旧测试夹具与较窄签名的 submitter

下一批进入条件：

1. 评估是否还需要让更多 adapter/channel 完成同样的服务化收口
2. 继续压缩 `EventBus` 在上层交互中的直接可见性
3. 再决定 procedure/task 是否需要接 capability 级 routing policy

### 4.19 当前执行批次：EventBus 可见性收口

本轮目标是继续压缩 `EventBus` 在上层组件中的直接可见性，尤其是 pending 查询和状态判断，不再让上层去读 `EventBus` 的内部字段。

本批次目标：

1. 扩展统一交互响应服务，承接 pending 查询与确认状态快照
2. 让 `App`、gateway 依赖和本地 adapter 优先通过服务层获取交互状态
3. 尽量消除上层对 `has_pending_confirmation`、`pending_request_id`、`pending_confirmation_session_id` 等内部字段的直接读取
4. 保持 `EventBus` 内部等待机制不变，但把它进一步藏到服务层后面

本批次完成条件：

- 存在统一的 pending 查询/状态快照接口
- 上层主要组件不再直接读取 `EventBus` 的确认 pending 字段
- 测试与文档同步更新

当前状态：已完成。

本批次已落地：

- `InteractionResponseService` 已扩展为统一的 pending 查询/状态快照门面
- `App` 的 runtime debug 确认状态已改为通过服务层获取
- gateway route、CLI、本地 Feishu fallback 已统一通过服务层提交与查询交互状态

下一批进入条件：

1. 评估是否还剩其他 adapter/channel 需要完成同类服务化迁移
2. 再决定是否把 procedure/task 接到 capability 级 routing policy
3. 如有必要，再考虑 EventBus 内部等待机制自身的后续重构

### 4.20 当前执行批次：Procedure / Task 与 Capability Routing Policy 衔接第一批

本轮目标是先让 Procedure 真正接上 capability routing policy 主链，不再只是 UI 展示和 prompt 提示；Task 暂时只对齐语义边界，不改调度器实现。

本批次目标：

1. 扩展 procedure 的 capability / routing 偏好公开 surface
2. 让 `procedure_call` 在创建 operation 时自动继承 procedure 的 preferred capability ref、执行目标和 routing preference
3. 让 procedure 的 routing preference 能参与 workspace 自动选路排序
4. 先不重写 Task 调度器，只把 task 的 capability policy 衔接保留为下一批入口

本批次完成条件：

- `client/procedures` 暴露 procedure capability / routing 偏好
- `procedure_call` 真正进入 capability routing 主链
- 测试覆盖 procedure capability ref 与 routing preference 生效

当前状态：已完成。

本批次已落地：

- `client/procedures` 已公开 procedure 的 capability / routing 偏好字段
- `procedure_call` 已会自动继承 procedure 的 preferred capability ref、执行目标和 routing preference
- Procedure 的 routing preference 已能参与 workspace 自动选路排序
- Task 调度器本轮未重写，仍保留为下一批入口

下一批进入条件：

1. 评估是否要把 task 调度器接到 capability 级 routing policy
2. 评估是否还有其他 adapter/channel 需要完成同类服务化迁移
3. 如有必要，再考虑 EventBus 等待机制自身的后续重构

### 4.21 当前执行批次：Task 调度器接入 Capability Routing Policy

本轮目标是让 Task 从“仅记录 execution_target”进一步升级为“记录 capability/routing 偏好，并在调度输出中真正携带这些偏好”。

本批次目标：

1. 为 scheduled task 记录引入 preferred capability ref 与 routing preference 字段
2. 让 `claim_due_tasks()`、background snapshot 和 `get_task_by_key()` 输出这些字段
3. 让 `App._handle_scheduled_task()` 的 route context 带上 task routing 偏好
4. 保持现有 Task 调度器和后台执行流程兼容

本批次完成条件：

- scheduled task 可声明 capability/routing 偏好
- 调度输出会显式带上这些字段
- App 的 scheduled task 执行上下文能看到这些偏好
- 测试与文档同步更新

当前状态：已完成。

本批次已落地：

- scheduled task 记录已支持 `preferred_capability_ref`、`preferred_agent_ids`、`preferred_agent_types`、`agent_routing_policy`
- `claim_due_tasks()`、background snapshot、`get_task_by_key()` 已显式带出这些字段
- `App._handle_scheduled_task()` 已把 task routing 偏好写入 route_context 和执行输入

下一批进入条件：

1. 评估是否还有其他 adapter/channel 需要完成同类服务化迁移
2. 如有必要，再考虑 EventBus 等待机制自身的后续重构
3. 评估 task 调度器是否需要进一步演化为真正的 operation 创建者

### 4.22 当前执行批次：Scheduled Task 产出 Operation 第一批

本轮目标是让 scheduled task 不只携带 capability/routing 偏好，而是在后台执行开始/结束时真正进入 `operation` 主链。

本批次目标：

1. 在 scheduled task 开始执行时创建正式 operation 记录
2. 在 scheduled task 完成或失败时更新 operation 状态与摘要
3. 把 operation 标识回写到 task 快照，便于调试与审计
4. 尽量保持现有 scheduler/Heart/App 执行流程兼容

本批次完成条件：

- scheduled task 运行会创建并更新 operation
- task 快照可看到最近一次 operation 标识与状态
- 测试与文档同步更新

当前状态：已完成。

本批次已落地：

- scheduled task 开始执行时会创建正式 `operation`
- scheduled task 完成或失败时会更新 operation 状态与摘要
- task 快照已记录 `last_operation_id` 与 `last_operation_status`
- App 的 scheduled task 执行主链已进入 operation 视角

下一批进入条件：

1. 评估其余 adapter/channel 是否还需要完成同类服务化迁移
2. 如有必要，再考虑 EventBus 等待机制自身的后续重构
3. 评估 scheduled reminder 是否也需要进入同一套 operation 主链

### 4.23 当前执行批次：Scheduled Reminder 产出 Operation

本轮目标是把上一批的 task operation 主链扩展到 scheduled reminder，让后台提醒也进入统一的 operation 记录与状态流。

本批次目标：

1. 在 scheduled reminder 开始处理时创建正式 operation
2. 在 reminder 完成后更新 operation 状态与摘要
3. 把 operation 标识回写到 task 快照
4. 尽量复用上一批的 task operation helper，避免形成第二套分支逻辑

本批次完成条件：

- scheduled reminder 开始/结束时会形成正式 operation 记录
- task 快照可记录 reminder 最近一次 operation 标识与状态
- 测试与文档同步更新

当前状态：已完成。

本批次已落地：

- scheduled reminder 开始处理时会创建正式 `operation`
- scheduled reminder 完成后会更新 operation 状态与摘要
- task 快照已记录 reminder 最近一次 operation 标识与状态

下一批进入条件：

1. 评估其余 adapter/channel 是否还需要完成同类服务化迁移
2. 如有必要，再考虑 EventBus 等待机制自身的后续重构
3. 评估 Heart / scheduler 是否需要进一步演化为显式 operation 创建者

### 4.24 当前执行批次：Electron 第一版产品化收口

本轮目标是面向“第一版基本可用产品”的完成判定，把 Electron 从开发态聊天壳继续收口为更像正式客户端的形态。

本批次目标：

1. 强化 Core / Local Agent / Workspace 状态可见性
2. 让 workspace、procedure、operation 等主链信息在主界面上更可见
3. 降低调试能力在主路径中的暴露度，把开发态信息继续压回次级入口
4. 保持现有 `client/* + client/ws` 主链不变，以最小前端改动完成产品化增强

本批次完成条件：

- 主界面能直观看到 Core、Local Agent、Workspace 三类状态
- workspace 关键治理信息在主界面可见
- procedure / operation 主链信息比当前更可见
- 调试态信息不再侵入主聊天主路径

当前状态：已完成。

本批次当前已落地：

- 输入框已从“未连通即完全禁用”调整为“允许先输入，连通后发送”
- 顶部主路径已移除 `Procedure` 快捷执行入口
- 标题栏已改为突出 `Core / Agent / Workspace` 三类状态与当前 workspace 信息
- 主界面已新增明确的 workspace 信息区
- 诊断入口已从标题栏主路径移到 workspace 卡片中的次级入口
- 主界面已显式展示运行中的 operation、待审批数和待补充输入数

本批次结论：

- Electron 主界面已经不再把 `Procedure` 作为用户主功能入口
- 第一版产品主路径已收口为：状态可见、workspace 可见、operation 可见、调试降权

### 4.25 当前执行批次：Heart / Scheduler 显式 Operation 创建

本轮目标是让后台调度器本身开始承担 operation 预创建职责，而不是完全由 App 执行器在收到 control event 后再临时创建。

本批次目标：

1. 让 Heart 在 claim due task 后预创建 operation
2. 把 `operation_id` 连同 `task_key / claim_token` 一起放进 control event
3. 让 App 在处理 scheduled task / reminder 时优先复用 Heart 预创建的 operation
4. 保持现有 scheduler->control event->App 执行流程兼容

本批次完成条件：

- Heart 调度器会在 claim 后创建 operation
- control event 已显式携带 `operation_id`
- App 不再必然重复创建第二条 task operation
- 测试与文档同步更新

当前状态：已完成。

本批次已落地：

- Heart 调度器已在 claim due task 后预创建 operation
- control event 已携带 `operation_id`
- App 处理 scheduled task / reminder 时会优先复用 Heart 预创建的 operation

下一批进入条件：

1. 继续推进 Electron 第一版产品化收口
2. 评估其余 adapter/channel 是否还需要完成同类服务化迁移
3. 如有必要，再考虑 EventBus 等待机制自身的后续重构

### 4.26 当前执行批次：第二大版本第一批 - 附件主链基础闭环

本轮目标是正式启动第二大版本，并优先补齐附件主链的基础闭环。

本批次目标：

1. Core 实现 attachment upload ticket / complete / download ticket 基础服务
2. 暴露 `client` 侧 attachment 资源入口
3. 为后续 Desktop Agent uploader / 前端下载流提供稳定的资源契约
4. 先完成服务端主链和最小前端入口，不在本批引入完整对象存储接入

本批次完成条件：

- 存在可用的 attachment metadata / upload ticket / complete / download ticket 主链
- client API 已能申请 upload ticket、完成 attachment、获取 download ticket
- 测试与文档同步更新

当前状态：已完成。

本批次已落地：

- Core 已实现 `client` 侧 attachment upload ticket / upload / complete / download ticket / download content 主链
- Attachment 内容已可先落到服务端本地 attachment store，作为第二版第一批的对象存储占位实现
- 前端已补 client attachment helper，并把附件按钮升级为最小可用上传入口

下一批进入条件：

1. 为 Desktop Agent 补 attachment uploader，替换服务端本地上传占位路径
2. 把 attachment reference 真正接到消息 / operation 展示层
3. 评估是否启动 Edge Agent / MQTT 第一批

### 4.27 当前执行批次：第二大版本第二批 - Desktop Agent Uploader

本轮目标是把附件主链从 `client` 侧扩展到 Desktop Agent，使本地执行器也能回传正式 attachment reference。

当前状态：已完成。

本批次已落地：

- `agent` 侧 attachment upload ticket / upload / complete 主链已落地
- Desktop Agent runtime 已可自动处理 handler 返回的 `attachment_outputs`
- `capability.call.result` 已能携带正式 attachment refs

下一批进入条件：

1. 把 attachment reference 真正接到消息 / operation 展示层
2. 评估是否启动 Edge Agent / MQTT 第一批
3. 继续完善对象存储替换当前服务端本地 attachment store 的方案

### 4.28 当前执行批次：第二大版本第三批 - Attachment Reference 展示层

本轮目标是把 attachment reference 真正从“后端结果字段”变成“前端可见、可下载的对象”。

当前状态：已完成。

本批次已落地：

- operation 中的 attachment outputs 已可在主界面渲染
- attachment ref 已具备下载动作
- 人工验收手册已覆盖 client / agent attachment 主链

下一批进入条件：

1. 评估是否启动 Edge Agent / MQTT 第一批
2. 继续完善对象存储替换当前服务端本地 attachment store 的方案
3. 评估 attachment ref 是否需要继续接入消息层而不仅是 operation 层

### 4.29 当前执行批次：第二大版本第四批 - Object Store 抽象层

本轮目标是把当前 attachment 服务对服务端本地文件落盘的直接依赖抽出来，为后续 MinIO / S3 接入做后端抽象准备。

当前状态：已完成。

本批次已落地：

- 已引入最小 object store 抽象层
- AttachmentService 已通过 object store 抽象读写附件内容
- 当前本地 attachment store 行为保持兼容，后续切 MinIO / S3 不再需要重写 attachment 主业务逻辑

下一批进入条件：

1. 评估是否启动 Edge Agent / MQTT 第一批
2. 继续推进对象存储从本地后端切换到 MinIO / S3
3. 评估 attachment ref 是否接入消息层与更完整的 UI 对象模型

### 4.30 当前执行批次：第二大版本第五批 - Edge Agent / MQTT 第一批骨架

本轮目标是正式启动 Edge Agent / MQTT 路线，先补 topic/helper、lease envelope 和最小 edge agent 骨架，而不一次性实现整套 broker 集成。

当前状态：已完成。

本批次已落地：

- 已引入 edge MQTT topic/helper 实现
- 已引入 `agent.pull.next` / `agent.pull.empty` / `capability.call.lease` envelope builder
- 已提供 edge agent 最小配置与 runtime skeleton

下一批进入条件：

1. 继续推进对象存储从本地后端切换到 MinIO / S3
2. 评估 Edge Agent / MQTT 是否启动 broker 集成第一批
3. 评估 attachment ref 是否接入消息层与更完整的 UI 对象模型

### 4.31 当前执行批次：第二大版本第六批 - Attachment Reference 接入消息层

本轮目标是让 attachment ref 不只停在 operation 卡片里，而是进入消息层对象模型，成为更完整的主界面对象。

本批次目标：

1. 为 chat turn 引入结构化 attachment 对象
2. 让 client 上传附件结果写入结构化 system turn
3. 在消息渲染层显式展示 attachment 并可下载

本批次完成条件：

- chat turn 可承载 attachment 对象
- 用户上传的 attachment 会以结构化方式出现在消息层
- 主界面可从消息层下载 attachment

当前状态：已完成。

本批次已落地：

- chat turn 已支持结构化 attachment 对象
- client 上传的 attachment 结果已写入结构化 system turn
- 主界面已可从消息层直接下载 attachment

下一批进入条件：

1. 继续推进对象存储从本地后端切换到 MinIO / S3
2. 评估 Edge Agent / MQTT 是否启动 broker 集成第一批
3. 评估 operation / message 是否需要统一 attachment object 视图

### 4.32 当前执行批次：第二大版本第七批 - 可配置 Object Store Backend

本轮目标是把 object store 抽象进一步推进为“可配置后端”，而不只是代码里存在一个本地实现类。

当前状态：已完成。

本批次已落地：

- 已引入 object store 工厂与配置解析
- 已引入 `object_store_backend` / `attachment_storage_root` 等配置入口
- bootstrap 已通过工厂创建 attachment object store
- 当前支持 `local/filesystem`，并对未来 MinIO/S3 切换保留稳定入口

下一批进入条件：

1. 评估 Edge Agent / MQTT 是否启动 broker 集成第一批
2. 继续推进对象存储从本地后端切换到 MinIO / S3
3. 评估 operation / message 是否需要统一 attachment object 视图

### 4.34 当前执行批次：第二大版本第九批 - S3-Compatible Object Store 第一批

本轮目标是把 object store 从“仅本地/文件系统可配置”推进到“具备 S3-compatible 后端能力”，为后续 MinIO / S3 真接入提供正式实现位点。

当前状态：已完成。

本批次已落地：

- 已引入 `S3CompatibleObjectStore`
- 已引入 `object_store_endpoint` / `object_store_bucket` / `object_store_region` / `object_store_access_key` / `object_store_secret_key`
- client / agent attachment 下载已切到基于 object store 读取字节，而不再依赖本地路径接口
- 当前支持 `local/filesystem/s3_compatible/minio` 后端标识

下一批进入条件：

1. 评估 Edge Agent / MQTT 是否启动 broker 集成第一批
2. 评估是否需要为 `s3_compatible` 增加真实预签名下载 URL 而不是当前代理下载
3. 评估 operation / message 是否需要统一 attachment object 视图

### 4.33 当前执行批次：第二大版本第八批 - Edge Agent 正式运行目标

本轮目标是把 edge agent 从“协议/骨架代码”推进到“正式运行目标”，让 `python main.py edge-agent` 成为有效入口。

本批次目标：

1. 新增 `edge_agent/main.py`
2. 将 `edge-agent` 接入 `main.py` 运行入口与 usage 文案
3. 补最小 edge-agent runtime 启动测试

本批次完成条件：

- 存在 `python main.py edge-agent` 正式入口
- edge-agent 最小 runtime 可启动/停止
- 测试与文档同步更新

当前状态：已完成。

本批次已落地：

- 已新增 `edge_agent/main.py`
- `main.py` 已支持 `python main.py edge-agent`
- 已补最小 edge-agent runtime 启动测试

下一批进入条件：

1. 评估 Edge Agent / MQTT 是否启动 broker 集成第一批
2. 继续推进对象存储从本地后端切换到 MinIO / S3
3. 评估 operation / message 是否需要统一 attachment object 视图

## 5. 当前代码与目标代码的映射

### 5.1 将保留并演进的目录

- `core/`
- `gateway/`
- `service_runtime/`
- `meetyou-ui/`

### 5.2 将新增的主要目录

- `desktop_agent/`
- `core/db/` 或 `core/persistence/` 下新的数据库实现
- `gateway/routes/client/`
- `gateway/routes/agent/`
- `gateway/routes/operator/`
- `gateway/routes/developer/`

### 5.3 将逐步降级或替换的旧路径

- 旧的 `session + /inputs + /ws` 单一路径
- 当前把终端本地工具直接塞在 Core 内的做法
- 当前前端默认依赖 `/runtime/debug` 的链路
- 当前文件型业务真相源

### 5.4 Feature 拆分视图

#### 5.4.1 拆分原则

- `Phase` 负责表达依赖、先后顺序和里程碑，不直接作为默认代码合并粒度
- `Feature` 是默认的代码管理单元；后续分支、提交、回归和验收优先按 feature 组织
- 一个 feature 应尽量只覆盖一条主链、一个 surface 或一个明确的 cross-surface 闭环
- 每个 feature 都应能指向明确代码边界、最小验证方式和对应文档落点

#### 5.4.2 Feature 清单

##### Phase 0 / 0.5

- `F00` 文档真源与迁移基线收口。边界：`docs/`。状态：已完成。
- `F01` 公开 `mode` / `execution_target` 冻结与兼容映射。边界：`core/`、`gateway/`、`meetyou-ui/`。关联批次：`4.4`。状态：已完成。

##### Phase 1

- `F10` Core 数据模型、PostgreSQL bootstrap 与 migration 骨架。边界：`core/db/`、`service_runtime/`、`core/app.py`。状态：已完成。

##### Phase 2

- `F20` Client / Agent / Operator / Developer 四类 surface 骨架与正式实时入口收口。边界：`gateway/`、`clients/`。状态：已完成。

##### Phase 3

- `F30` 显式 operation 审批前置。边界：`core/services/approval_service.py`、`gateway/routes/client.py`。关联批次：`4.5`。状态：已完成。
- `F31` Session 真相源收口。边界：`core/session_manager.py`、`core/app.py`、`gateway/routes/client.py`。关联批次：`4.6`。状态：已完成。
- `F32` 聊天确认与 human input 资源语义入口。边界：`gateway/routes/client.py`、`clients/gateway_client.py`、`cil/`、`sensors/`。关联批次：`4.7`、`4.11`、`4.14`、`4.16`、`4.17`。状态：已完成。
- `F33` 交互响应服务化与 EventBus 可见性收口。边界：`core/interaction_response_service.py`、`core/event_bus.py`、`gateway/`、`sensors/`。关联批次：`4.18`、`4.19`。状态：已完成。

##### Phase 4 / 5

- `F40` Desktop Agent 最小运行时、握手和 capability snapshot 主链。边界：`desktop_agent/`、`gateway/routes/agent.py`。状态：已完成。
- `F41` 本地工具从 Core 剥离到 Desktop Agent 与本地策略守卫。边界：`desktop_agent/`、`tools/`、`core/services/agent_dispatch_service.py`。状态：已完成。

##### Phase 6

- `F60` Frontend 迁移到 `client/* + client/ws` 正式主链。边界：`meetyou-ui/src/hooks/`、`meetyou-ui/src/clientApi.ts`。状态：已完成。
- `F61` Electron 第一版产品化收口。边界：`meetyou-ui/src/App.tsx`、`components/layout/`、`components/workspace/`、`components/chat/`。关联批次：`4.24`。状态：已完成。

##### Phase 7

- `F70` Client attachment 主链基础闭环。边界：`core/services/attachment_service.py`、`gateway/routes/client.py`、`meetyou-ui/src/clientApi.ts`。关联批次：`4.26`。状态：已完成。
- `F71` Desktop Agent attachment uploader。边界：`desktop_agent/runtime.py`、`gateway/routes/agent.py`。关联批次：`4.27`。状态：已完成。
- `F72` Attachment object 展示层。边界：`meetyou-ui/src/components/chat/`、`meetyou-ui/src/types.ts`。关联批次：`4.28`、`4.31`。状态：已完成。
- `F73` Object store 抽象与可配置 backend。边界：`core/storage/object_store.py`、`core/config.py`、`core/app.py`。关联批次：`4.29`、`4.32`。状态：已完成。
- `F74` S3-compatible object store 第一批。边界：`core/storage/object_store.py`、`core/services/attachment_service.py`。关联批次：`4.34`。状态：已完成。
- `F75` Attachment 统一对象视图。边界：`core/services/attachment_service.py`、`meetyou-ui/src/types.ts`、`components/chat/`。状态：已完成。
- `F76` 对象存储产品化能力。范围：预签名下载 URL、部署配置说明、MinIO / S3 实际接入验收。边界：`core/storage/`、`gateway/routes/client.py`、`docs/`。状态：待开始。
- `F77` 短生命周期截图附件与清理策略。边界：`desktop_agent/`、`core/services/attachment_service.py`、后台清理任务。状态：待开始。

##### Phase 8

- `F80` Workspace 默认治理字段主链化。边界：`core/services/workspace_service.py`、`core/prompt_assembler.py`、`gateway/routes/`。关联批次：`4.8`。状态：已完成。
- `F81` Workspace capability allowlist / overlay。边界：`core/services/workspace_service.py`、`core/services/operation_service.py`。关联批次：`4.9`。状态：已完成。
- `F82` Workspace agent routing / preference policy。边界：`core/services/agent_dispatch_service.py`、`core/services/workspace_service.py`。关联批次：`4.10`、`4.12`。状态：已完成。
- `F83` 跨 agent capability 抽象命名与 capability routing override。边界：`core/services/capability_service.py`、`core/services/agent_dispatch_service.py`、`gateway/models.py`。关联批次：`4.13`、`4.15`。状态：已完成。
- `F84` Procedure capability / routing integration。边界：`core/services/procedure_service.py`、`gateway/routes/client.py`。关联批次：`4.20`。状态：已完成。
- `F85` Task routing preference integration。边界：`tools/task_manager.py`、`core/app.py`、`core/services/operation_service.py`。关联批次：`4.21`。状态：已完成。
- `F86` Scheduler operation 主链。边界：`core/heart.py`、`core/app.py`、`tools/task_manager.py`。关联批次：`4.22`、`4.23`、`4.25`。状态：已完成。
- `F87` Workspace memory ranking 与 tags 主链。边界：`core/memory/`、workspace 查询服务、前端 workspace 视图。状态：待开始。
- `F88` Procedure pin 与显式 procedure 指定主链。边界：`core/services/procedure_service.py`、`meetyou-ui/src/hooks/core/useProcedures.ts`、主界面 procedure UI。状态：待开始。

##### Phase 9

- `F90` Edge Agent 协议骨架与 pull / lease envelope。边界：`edge_agent/protocol.py`、`edge_agent/runtime.py`。关联批次：`4.30`。状态：已完成。
- `F91` Edge Agent 正式运行目标。边界：`edge_agent/main.py`、`main.py`。关联批次：`4.33`。状态：已完成。
- `F92` MQTT broker 集成第一批。范围：broker 连接、topic 收发、pull/lease 实际通信。边界：`edge_agent/`、gateway bridge、相关测试。状态：待开始。
- `F93` Edge pull / lease 稳定性与 broker 集成测试。边界：`tests/test_edge_agent_*`、MQTT 集成环境。状态：待开始。

##### Phase 10

- `F100` Legacy path cleanup。范围：旧 `session + /inputs + /ws` 主路径、Core 直执行本地工具、过期兼容入口。边界：`gateway/`、`core/`、`desktop_agent/`。状态：待开始。
- `F101` 稳定化与验收文档收口。范围：README、启动手册、手工验收、回归命令统一。边界：`README.md`、`docs/`、`scripts/`。状态：进行中。

## 6. 阶段计划

## Phase 0 文档与基线

### 目标

- 确认 V2 目标模型
- 收口设计文档
- 删除过时草案与旧重构计划

### 输入依赖

- 无

### 交付物

- 本实施计划书
- 保留下来的 5 份目标设计文档
- 当前迁移基线、旧功能映射、缺口矩阵与后续阶段计划文档

### 验收

- `docs/` 中只保留当前仍要用的设计文档
- 后续开发者能只通过本文档和 5 份设计文档推进 coding

## Phase 0.5 公开语义冻结

### 目标

- 固定公开 `mode` 与 `execution_target` 枚举
- 阻止前端、路由和种子数据继续产生旧值
- 为 legacy assistant mode 内核提供过渡映射层

### 输入依赖

- Phase 0
- `workspace-capability-model.md`
- `core-api-surfaces.md`

### 主要任务

1. 固定公开 mode 枚举为 `general | research | documents | study | automation`
2. 固定 `execution_target` 枚举为 `core_only | specific_agent | workspace_any_agent | prefer_agent_fallback_core`
3. 清理 Procedure、前端类型、API 请求响应中的旧枚举值
4. 在 Core 输入侧增加 public-to-legacy 过渡映射

### 验收

- 前端不再发送 `normal`、`auto`、`office`、`desktop`、`assistant` 等旧公开值
- Client API 输出的 Procedure 和 Operation 枚举为新值
- 旧内核仍可通过过渡映射运行

当前状态：已完成。

## Phase 1 Core 数据模型与持久化骨架

### 目标

- 为 Core 引入数据库层
- 建立 `principal / client / workspace / agent / thread / session / operation / approval / attachment` 基础模型

### 输入依赖

- `core-client-agent-architecture.md`
- `workspace-capability-model.md`
- `storage-and-binary-transfer.md`

### 主要任务

1. 引入 PostgreSQL 配置与连接层
2. 建立 migration 机制
3. 建立基础表：
   - principals
   - clients
   - workspaces
   - agents
   - workspace_agent_memberships
   - threads
   - sessions
   - operations
   - approvals
   - attachments
4. 为现有运行态保留兼容层，不立即切断旧逻辑

### 代码范围

- `core/`
- `service_runtime/`
- 新的数据库模块

### 测试

- 单元测试：模型与 repository
- 集成测试：migration + CRUD
- 回归测试：现有 service 仍可启动

### 验收

- Core 可以在数据库中创建和读取上述资源
- 不影响当前基础 service 启动

## Phase 2 Core API 分层与新资源骨架

### 目标

- 把当前混合 API 拆成 Client / Agent / Operator / Developer 四类 surface
- 建立新 router 骨架

### 输入依赖

- Phase 1
- `core-api-surfaces.md`

### 主要任务

1. 建立新的路由目录结构
2. 先创建空骨架接口：
   - `/client/*`
   - `/agent/*`
   - `/operator/*`
   - `/developer/*`
3. 为新旧接口并存做 versioned adapter
4. 把 `/runtime/debug` 从默认用户面逻辑上剥离

### 测试

- 路由注册测试
- auth boundary 测试
- OpenAPI / schema 基础测试

### 验收

- 新路由可启动
- 旧前端仍不被破坏
- 新旧接口能并存一段时间

## Phase 3 Thread / Session / Operation / Approval 主链

### 目标

- 建立新的交互主线
- 让“跨会话协作”成为正式模型

### 输入依赖

- Phase 1
- Phase 2
- `workspace-capability-model.md`

### 主要任务

1. 新建 thread service
2. 新建 session service
3. 新建 operation service
4. 新建 approval service
5. 让消息输入能挂到 thread/session 上
6. 让 operation 结果可以回流到多个 session

### 测试

- thread CRUD
- session attach/detach
- operation lifecycle
- approval lifecycle
- 跨 session 事件广播

### 验收

- 可以从飞书 session 发起 operation，并让桌面 session 看到同一 operation 的状态变化

## Phase 4 PC 客户端内本地后端最小运行时

### 目标

- 引入 PC 客户端内本地后端进程
- 打通 `hello / heartbeat / capabilities snapshot`

### 输入依赖

- Phase 2
- `agent-protocol-v1.md`
- `storage-and-binary-transfer.md`

### 主要任务

1. 新建或收口 `desktop_agent/`，作为 PC 客户端本地后端实现
2. 实现配置加载
3. 实现 WSS 连接
4. 实现 `agent.hello`
5. 实现 `agent.heartbeat`
6. 实现 `agent.capabilities.snapshot`
7. 在 Core 中引入 agent registry service

### 测试

- PC 客户端本地后端启动测试
- 注册与心跳测试
- capability snapshot 测试

### 验收

- PC 客户端本地后端可在 Core 中显示为在线
- Core 可读取其 capability 快照

## Phase 5 本地工具从 Core 剥离到客户端内本地后端

### 目标

- 将终端环境强耦合的 tool 从 Core 中迁出

### 输入依赖

- Phase 4
- `workspace-capability-model.md`

### 主要任务

1. 识别需迁出的工具：
   - 本地文件读写
   - shell / git
   - 本地 MCP
   - 截图 / 桌面自动化
2. 为这些工具建立 Agent capability 映射
3. Core 中保留 capability routing，不再直接执行
4. 为客户端内本地后端增加 Local Policy Guard

### 测试

- capability call request / result 测试
- 本地策略拒绝测试
- Core 路由选择测试

### 验收

- 典型本地工具路径可通过客户端内本地后端成功执行
- Core 中相关直接执行路径开始下线

## Phase 6 Frontend 迁移到 Client API

### 目标

- 前端改成基于 `thread / session / operation / approval` 模型
- 去掉对旧接口和默认 debug 面的依赖

### 当前状态补记

- `useMeetYou` 已通过 `clientApi.ts` 走 `workspace / thread / session / message / client/ws` 正式主链
- 主窗口已通过 `fetchRuntimeUsageSnapshot` 完成 usage / context 初始 hydration
- richer Client 本阶段已补齐 connection / session / operation 状态分层、approval / human input 一等 UI、Procedure 正式入口、附件入口占位以及 devtools debug 迁移
- 下一步重点改为 Phase 7 的附件闭环，而不是继续在主窗口补零散占位

### 输入依赖

- Phase 2
- Phase 3
- `core-api-surfaces.md`

### 主要任务

1. 建立前端 connection store
2. 重构 `useMeetYou` 为多 store / 多 hook 结构
3. 引入 thread/session/operation 概念到 UI 状态
4. 把审批、Procedure 与附件入口做成一等 UI 对象
5. 将 `/runtime/debug` 移到 devtools 面

### 测试

- typecheck
- 组件测试
- 断线重连与 operation 状态同步测试

### 验收

- 前端主路径只依赖 Client API
- 跨 session operation 可在 UI 中正常展示
- approval / human input / Procedure / attachment 入口已作为主路径显式对象出现
- `/runtime/debug` 已迁到独立 devtools 面

## Phase 7 附件通道与对象存储

### 目标

- 附件脱离主消息流
- 建立 upload ticket / complete / download ticket
- 将当前主窗口附件入口占位升级为真实可上传、可回显、可下载的 attachment reference 主链

### 输入依赖

- Phase 1
- Phase 4
- `storage-and-binary-transfer.md`

### 主要任务

1. Core 中实现附件元数据与 ticket 服务
2. 在客户端内本地后端实现 attachment uploader
3. 前端中实现 attachment download flow
4. 支持截图类短生命周期附件

### 测试

- ticket 签发测试
- 上传完成测试
- 下载权限测试
- 短生命周期清理测试

### 验收

- 桌面截图可上传并回传 attachment reference
- 飞书或前端可下载查看

## Phase 8 Workspace / Memory / Procedure 收口

### 目标

- 让 workspace 成为真实作用域
- 收口 global memory + workspace tags
- 让 Procedure 成为一等对象并支持 pin

### 输入依赖

- Phase 1
- Phase 3
- `workspace-capability-model.md`

### 主要任务

1. memory records 改为服务端统一存储
2. 引入 workspace tags 检索排序
3. Procedure 服务化
4. 支持 thread 级 pinned procedure
5. 前端增加显式 procedure 指定能力

### 测试

- memory 检索排序测试
- workspace 优先级测试
- procedure pin 测试

### 验收

- 当前 workspace 的记忆优先显示
- 其他 workspace 来源记忆可见且带来源标记
- 用户可显式固定 procedure

## Phase 9 Edge Agent MQTT 基础设施

### 目标

- 为树莓派等设备引入 MQTT transport
- 支持 pull 模式

### 输入依赖

- Phase 2
- `agent-protocol-v1.md`

### 主要任务

1. 建立 Agent Gateway / MQTT bridge
2. 实现 topic 规范
3. 实现 `agent.pull.next`
4. 实现 `capability.call.lease`
5. 实现 edge agent 最小样例

### 测试

- MQTT broker 集成测试
- lease 机制测试
- pull empty / pull lease 测试

### 验收

- 弱设备可通过 pull 模式领取任务

## Phase 10 清理旧路径与稳定化

### 目标

- 删除已被替代的旧实现
- 收口文档与测试

### 输入依赖

- 前面全部阶段

### 主要任务

1. 清理旧 `session + /inputs + /ws` 主路径
2. 下线直接在 Core 执行的终端本地工具
3. 更新 README、迁移文档与当前基线文档
4. 收口测试命令与开发命令

### 测试

- 全量回归
- 手工 smoke test

### 验收

- 新架构为默认路径
- 文档与代码一致

## 7. 任务依赖图

### 7.1 高层依赖

```text
Phase 0
  -> Phase 1
  -> Phase 2

Phase 1 -> Phase 3
Phase 2 -> Phase 3

Phase 2 -> Phase 4
Phase 4 -> Phase 5

Phase 3 -> Phase 6
Phase 2 -> Phase 6

Phase 1 -> Phase 7
Phase 4 -> Phase 7

Phase 1 -> Phase 8
Phase 3 -> Phase 8

Phase 2 -> Phase 9

Phase 5 -> Phase 10
Phase 6 -> Phase 10
Phase 7 -> Phase 10
Phase 8 -> Phase 10
Phase 9 -> Phase 10
```

### 7.2 可以并行的部分

- Phase 4 与 Phase 6 的前半段可部分并行
- Phase 7 的对象存储接入可与 Phase 6 前端迁移并行
- Phase 8 的 Procedure 收口可在 Phase 6 后半段并行推进

## 8. 文档依赖图

### 8.1 架构级

- `implementation-plan.md` 依赖全部设计文档
- `core-client-agent-architecture.md` 是最高层目标文档

### 8.2 领域级

- `workspace-capability-model.md` 依赖架构文档
- `core-api-surfaces.md` 依赖架构文档和领域模型文档
- `agent-protocol-v1.md` 依赖架构文档和领域模型文档
- `storage-and-binary-transfer.md` 依赖架构文档和 agent 协议文档

### 8.3 coding 参考级

- Phase 1 主要读：
  - `workspace-capability-model.md`
  - `storage-and-binary-transfer.md`
- Phase 2 / 3 / 6 主要读：
  - `core-api-surfaces.md`
- Phase 4 / 5 / 9 主要读：
  - `agent-protocol-v1.md`
- Phase 7 主要读：
  - `storage-and-binary-transfer.md`

## 9. 测试策略

## 9.1 后端测试层次

### 单元测试

- repository
- capability routing
- memory ranking
- approval decision logic
- attachment ticket logic

### 集成测试

- database migrations
- client API routers
- agent API routers
- Desktop Agent 与 Core 握手
- object storage ticket flow

### 端到端测试

- Electron / Client -> Core -> Desktop Agent -> Attachment -> Client
- Feishu -> Core -> Desktop Agent -> Screenshot -> Feishu

## 9.2 前端测试层次

- typecheck
- hooks / store 测试
- operation 与 approval 组件测试
- 断线重连状态测试

## 9.3 Agent 测试层次

- capability registry
- local policy guard
- offline queue
- attachment uploader
- reconnect / replay

## 10. 每阶段建议命令

### 后端

- `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`
- 或按阶段执行相关测试文件

### 前端

- `npm run typecheck`
- `npm run test`
- `npm run build`

### Agent

- 建议新增独立测试目录与命令，例如：
  - `.venv\Scripts\python.exe -m unittest discover -s tests_agent -p "test_*.py"`

## 11. 里程碑

### Milestone A

- Phase 1 + Phase 2 完成
- Core 已具备新数据与新 API 骨架

### Milestone B

- Phase 3 + Phase 4 完成
- Thread / Operation / Approval 主链与 Desktop Agent 注册打通

### Milestone C

- Phase 5 + Phase 6 + Phase 7 完成
- 典型桌面操作与截图回传全链路可用

### Milestone D

- Phase 8 + Phase 9 + Phase 10 完成
- 新架构成为默认路径

## 12. 推荐执行粒度

不要按“文件”为单位推进，按“feature / 可验收 tranche”推进。

推荐每个 tranche 满足：

- 功能闭环
- 有测试
- 可独立合并
- 不破坏主路径
- 优先只落一个 feature；如果必须跨 feature，必须在批次说明里显式写清原因

## 13. 一键执行的理解

本文档的目标不是现在生成一个自动脚本去盲目执行全部重构，而是：

- 让后续 coding 可以按本文档中的 `Phase -> Feature -> Task` 清单机械推进
- 每个阶段都能明确输入、输出、依赖、测试和验收

真正的一键执行应建立在：

- 每个 Phase 具备独立脚本或任务 runner
- 测试命令和环境准备已标准化

## 14. 过时文档处理规则

以下文档如果与本计划冲突，以本计划和 5 份目标设计文档为准：

- 旧重构计划
- 旧单体接口思路
- 旧本地优先运行假设

# 全部完成后清向用户报告
