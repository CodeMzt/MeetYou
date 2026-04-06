# 助手中层编排重构 Spec

## Why
当前项目已完成服务优先运行时重构，但助手中层仍存在 mode / skill / tool / prompt / memory / task / heartbeat 多中心治理、状态机分裂、权限边界分散和上下文注入链路冗杂等问题，导致模式切换生硬、工具能力漂移、记忆语义不稳、心跳与健康口径不一致，以及提示词成本持续膨胀。  
本次变更以允许大幅重构为前提，重建助手中层编排中枢，统一能力注册、授权、副作用控制、上下文规划、记忆分层和任务状态模型，以提升用户体验、高稳定性、高质量、强鲁棒性和强可用性。

## What Changes
- 建立统一 Capability Registry，收敛 mode、skill、tool bundle、prompt bundle、MCP server、side-effect policy、risk policy 与上下文规划策略
- 建立统一 Authorization Gateway，在工具执行前统一处理可见性、风险分级、确认流、可信写路径与只读策略
- 建立统一 Context Planner，合并 memory prefetch、working summary、history compaction、session preload 与 live web 偏好
- 重构记忆系统为 episode、durable memory、conversation summary、memory graph 的显式分层，并补齐同步 durable upsert 能力
- 重构任务与定时任务运行时状态模型，显式拆分 schedule、execution、delivery 与 heartbeat signal 语义
- 重构 heartbeat 规则与候选问题构造，统一其与服务健康、任务系统和后台状态的判断口径
- 重构模式切换与 SKILL 机制，使 skill 成为真正能力对象，并支持无缝 route rebuild 与工具面切换
- 重构 prompt 装配和长度治理，建立 provider 无关的 Length Policy、上下文预算和裁剪优先级
- 为中层编排增加启动期一致性校验、迁移策略、调试观测和系统级回归测试
- **BREAKING**：移除仅靠 prompt 注入的半能力化 skill 语义，改为显式能力声明
- **BREAKING**：移除分散在各工具内部的副作用控制主路径，改由统一 Authorization Gateway 决策
- **BREAKING**：移除任务记录中混合式状态拼接主路径，改为结构化状态对象与稳定状态转移
- **BREAKING**：移除将历史摘要作为普通 system message 回灌的主路径，改为受控上下文注入

## Impact
- Affected specs: 助手模式路由、SKILL 系统、Prompt 装配、工具权限与执行、记忆系统、上下文管理、任务系统、定时任务、Heartbeat、服务健康、调试接口、测试体系
- Affected code: `core/assistant_modes.py`、`core/semantic_router.py`、`core/brain.py`、`core/context.py`、`core/tools_manager.py`、`core/tool_runtime/`、`core/heart.py`、`tools/agent_memory.py`、`tools/memory.py`、`tools/memory_layers.py`、`tools/task_manager.py`、`tools/scenario_tools.py`、`tools/system_tools.py`、`tools/document_tools.py`、`gateway/`、`prompt/`、`user/`、`tests/`

## ADDED Requirements
### Requirement: 统一能力注册中心
系统 SHALL 提供 Capability Registry 作为助手中层的单一事实来源，统一声明 mode、skill、tool、prompt、MCP server、风险等级、只读/可写策略与上下文规划属性。

#### Scenario: 新增一个 skill 能力
- **WHEN** 开发者新增一个 skill
- **THEN** 系统 SHALL 通过单一注册声明该 skill 的 prompt、工具能力、MCP 依赖、上下文需求与副作用策略
- **AND** SHALL 在启动期校验该 skill 引用的工具、bundle、prompt 与 server 均存在且兼容

### Requirement: 统一授权与副作用网关
系统 SHALL 在任意工具执行前通过统一 Authorization Gateway 完成能力可见性判断、风险分级、确认流、可信写入边界、只读策略和副作用审计。

#### Scenario: 只读模式下请求写入本地文件
- **WHEN** 当前 route 或 skill 被标记为只读
- **THEN** 系统 SHALL 在工具执行前拒绝写入型调用
- **AND** SHALL 返回结构化拒绝结果，说明拒绝原因、风险分类与允许的替代路径

### Requirement: 统一上下文规划器
系统 SHALL 提供 Context Planner 统一决定每轮对话的上下文组成、预算分配、预加载策略和裁剪顺序。

#### Scenario: 上下文预算不足
- **WHEN** 当前模型上下文预算不足以容纳全部历史、记忆和工具轨迹
- **THEN** 系统 SHALL 按预定义优先级裁剪工具噪音、低价值历史与可再生上下文
- **AND** SHALL 保留系统约束、未完成任务、高价值记忆与最近用户意图

### Requirement: 分层记忆模型
系统 SHALL 将记忆显式拆分为 episode、durable memory、conversation summary 与 memory graph，并为显式记忆写入提供同步 durable upsert 路径。

#### Scenario: 助手被要求记住稳定偏好
- **WHEN** 模型或用户显式要求记住长期稳定的信息
- **THEN** 系统 SHALL 直接写入 durable memory 或 durable upsert 队列
- **AND** SHALL 不依赖 housekeeping 完成后才能使该记忆可检索

### Requirement: 会话感知的记忆检索
系统 SHALL 支持基于 user、session、global 与 source policy 的显式检索范围，并让调试接口和主执行链路使用一致语义。

#### Scenario: 按当前会话检索上下文
- **WHEN** 系统为某一 session 进行自动记忆预取
- **THEN** 检索 SHALL 正确识别该 session 的局部上下文与全局 durable memory
- **AND** SHALL 不再忽略 session 过滤条件

### Requirement: 结构化任务编排状态模型
系统 SHALL 为任务系统建立独立的 ScheduleState、ExecutionState、DeliveryState 与 HeartbeatSignalState，并通过稳定状态转移管理自动执行、补发、失败与重试。

#### Scenario: 定时任务执行成功但未即时投递
- **WHEN** 自动任务执行完成但当前渠道不可投递
- **THEN** 系统 SHALL 记录执行成功与待补发状态
- **AND** SHALL 允许后续补发过程独立更新 DeliveryState 而不污染执行结果

### Requirement: Heartbeat 与健康口径统一
系统 SHALL 使 heartbeat、后台状态聚合与服务健康使用一致的问题候选、退化规则与信号类型集合。

#### Scenario: 记忆 consolidation 长时间停滞
- **WHEN** pending consolidation 超过退化阈值
- **THEN** 服务健康 SHALL 标记 degraded
- **AND** Heartbeat SHALL 将其识别为系统问题候选并按冷却规则决定是否通知用户

### Requirement: 无缝模式切换
系统 SHALL 支持 route rebuild，使模式切换、skill 激活与工具面变化在单轮内以受控方式完成，而不依赖“单独一轮只做切模”的硬性约束。

#### Scenario: 对话中切换到研究模式
- **WHEN** 当前对话识别到需要切换到研究模式并启用额外 research skill
- **THEN** 系统 SHALL 原子更新 route、capability set、prompt 片段与上下文计划
- **AND** SHALL 保持本轮意图连续，不因中途切模而丢失用户目标

### Requirement: 统一长度治理策略
系统 SHALL 提供 provider 无关的 Length Policy，统一定义输出长度、推理预算、上下文保留比例和裁剪保底空间。

#### Scenario: 不同模型处理同一长任务
- **WHEN** 系统切换不同 provider 或 model
- **THEN** 每轮请求 SHALL 使用统一的长度治理策略进行适配
- **AND** SHALL 避免因 provider 差异造成输出长度和稳定性大幅漂移

### Requirement: 启动期一致性校验
系统 SHALL 在启动期校验 capability registry、prompt 资源、skill 声明、tool schema、MCP server 依赖与风险策略的一致性。

#### Scenario: mode 引用了不存在的工具
- **WHEN** 系统启动时发现 mode、skill 或 bundle 引用了未注册工具
- **THEN** 系统 SHALL 阻止不一致配置进入运行态
- **AND** SHALL 返回可定位的结构化启动错误

## MODIFIED Requirements
### Requirement: Assistant Mode 管理
Assistant Mode 管理不再以硬编码 prompt、tool bundle 与 skill 注入列表为主。  
系统 SHALL 基于 Capability Registry 和 Route Runtime 生成模式能力面、Prompt 片段、上下文计划和副作用策略，并允许 mode 与 skill 的组合式装配。

### Requirement: 工具执行
工具执行不再仅依赖 route allowlist 与工具内部自检。  
系统 SHALL 在统一 Authorization Gateway 中完成权限判断、风险控制、确认流和副作用审计，再交由执行器运行具体工具。

### Requirement: 记忆写入与召回
记忆写入与召回不再混合依赖 episode consolidation、working summary 与隐式过滤逻辑。  
系统 SHALL 以显式分层模型管理记忆，并让召回范围、写入语义、摘要来源和调试接口保持一致。

### Requirement: 定时任务与补发
定时任务不再通过混合字段拼接 schedule、execution 与 delivery 结果。  
系统 SHALL 以结构化状态对象和可验证的状态转移管理 claim、execute、retry、deliver、redeliver 与 completion。

### Requirement: Heartbeat
Heartbeat 不再依赖与健康检查不一致的候选问题集合或无效信号枚举。  
系统 SHALL 仅使用稳定、受支持且与系统健康一致的信号类型和规则集生成通知决策。

### Requirement: 历史裁剪
历史裁剪不再通过将摘要作为普通 system message 重新插入的方式完成。  
系统 SHALL 采用受控的上下文注入机制承载压缩结果，并区分系统指令与历史摘要语义。

## REMOVED Requirements
### Requirement: Prompt-only Skill
**Reason**: 仅通过 prompt 注入定义 skill 无法稳定表达工具能力、上下文需求与副作用边界，会导致能力漂移和治理失真。  
**Migration**: 所有 skill 改为显式 capability 声明；只保留纯文本增强的场景需明确标记为 prompt-only enhancement 而非完整 skill。

### Requirement: 分散式副作用控制
**Reason**: 将写入限制、命令确认和风险控制分散到各工具内部会造成策略不一致、测试困难和安全边界漂移。  
**Migration**: 将写入边界、确认流和风险策略前移到 Authorization Gateway；工具内部仅保留资源级约束与执行细节。

### Requirement: 混合式任务状态记录
**Reason**: 任务记录混合保存调度、执行、投递和编排状态，容易引发状态漂移与心跳误判。  
**Migration**: 使用结构化状态对象、显式状态转移与兼容迁移逻辑替代旧字段拼接主路径。

### Requirement: System Message 历史摘要回灌
**Reason**: 将历史摘要伪装为普通 system message 会混淆系统规则与上下文压缩内容，放大 prompt 污染风险。  
**Migration**: 引入专用的上下文注入层或 metadata 承载摘要，并更新所有调用方消费方式。
