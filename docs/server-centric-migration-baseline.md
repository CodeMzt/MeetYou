# 服务端中心化当前基线与后续收口顺序

## 1. 目的

本文档记录当前仓库已经落地到什么程度、仍有哪些关键偏差，以及后续应该按什么顺序继续收口。

它不是目标架构说明书的替代品，而是面向当前代码现状的执行基线，回答三个问题：

1. 当前代码已经走到哪一步
2. 目标模型与当前实现之间还差什么
3. 下一步应该先收什么，再做什么

## 2. 结论摘要

- 正式后端入口已经统一为 `python main.py service`
- `client/*`、`agent/*`、`operator/*`、`developer/*` 四类 surface 已经存在，`GET /client/ws` 是正式实时入口
- Desktop Agent 已具备最小可用运行时，本地文件、Shell、工作区分析与本地 MCP 已不再默认留在 Core 直执行
- 记忆、任务、source catalog、office、study 等运行态已迁到数据库或 state blob 后端，服务器作为权威状态源的主链基本成立
- `.trae/` 下的 AI 规划残留、旧 `interface.md` 和旧 smoke 清单已移除，文档真源已收口到 `docs/` 下的目标设计文档、实施计划、迁移说明与本文档
- 当前最大的未收口问题不再是“有没有新入口”，而是“核心模型是否真正统一”：审批仍偏 EventBus 临时流、session 仍有双模型、workspace 仍未成为完整治理中心、前端仍偏开发壳

补充：当前阶段的直接目标已经明确为“第一版基本可用产品”，其完成判定以 `docs/implementation-plan.md` 中的 3.1 / 3.2 为准。

当前结论：按实施计划中的完成判定，第一版基本可用产品已经达成。

补充：当前开发已正式进入“第二大版本”阶段，当前优先级转向附件主链、后台调度深化与 edge 基础设施。

当前第二版进度：第一批“附件主链基础闭环”已经落地，`client` 侧 attachment ticket / upload / complete / download content 主链可用。

当前第二版进度补充：第二批“Desktop Agent uploader”已经落地，agent 已可上传并回传 attachment refs。

当前第二版进度补充：第三批“Attachment Reference 展示层”已经落地，operation 已可展示并下载 attachment refs。

当前第二版进度补充：第四批“Object Store 抽象层”已经落地，AttachmentService 已不再直接依赖本地路径实现。 

当前第二版进度补充：第五批“Edge Agent / MQTT 第一批骨架”已经落地，topic/helper、lease envelope 与最小 edge runtime skeleton 已具备。 

当前第二版进度补充：下一批进入 attachment ref 接入消息层，使附件从 operation 扩展到更完整的 UI 对象模型。 

当前第二版进度补充：第六批“Attachment Reference 接入消息层”已经落地，attachment 现在既可在 operation 层显示，也可在消息层显示。 

当前第二版进度补充：第七批“可配置 Object Store Backend”已经落地，attachment 存储已具备正式配置入口。 

当前第二版进度补充：第八批“Edge Agent 正式运行目标”已经落地，`python main.py edge-agent` 已可用。 

当前第二版进度补充：第九批“S3-Compatible Object Store 第一批”已经落地，对象存储后端已从 local/filesystem 扩展到 `s3_compatible`。 

当前第二版执行总结：

- 第一批：`client` attachment 主链基础闭环已完成
- 第二批：Desktop Agent uploader 已完成
- 第三批：Attachment reference 展示层已完成
- 第四批：Object Store 抽象层已完成
- 第五批：Edge Agent / MQTT 第一批骨架已完成

当前第二版进度补充：下一批进入 Edge Agent / MQTT 第一批骨架实现。

当前第二版进度补充：下一批进入对象存储后端抽象，为 MinIO / S3 接入做准备。

## 2.1 当前执行批次

本轮已经正式启动的收口批次是：

1. 冻结公开 `mode` 与 `execution_target` 枚举
2. 把计划同步到 `docs/` 真源文档
3. 给当前 legacy assistant mode 内核增加过渡映射层
4. 为下一批 approval / session / workspace 主链重构铺路

本批次完成前，不再接受新的公开枚举继续扩散到前端、Procedure、API 或种子数据。

当前状态：已完成。

本批次已交付：

- 公开 mode 已固定为 `general | research | documents | study | automation`
- 公开 `execution_target` 已固定为 `core_only | specific_agent | workspace_any_agent | prefer_agent_fallback_core`
- Client API Procedure / Operation 输出已切到新枚举
- Electron 主输入模式选择已切到新枚举
- Core 已增加 public-to-legacy mode 映射，避免当前 assistant runtime 立即失效

下一批将进入：approval / session / workspace 主链收口。

## 2.2 当前进行中的子阶段

当前正在执行的子阶段是：`Approval 前置到显式 Operation`。

范围说明：

- 只处理 `POST /client/operations` 创建的显式 operation
- 风险来源先以 capability 的 `requires_confirmation` 与 `risk_level` 为准
- 聊天内工具确认流仍暂时保留在 `EventBus` 链路，不在本批次一起收口

阶段出口：

- 显式 operation 不再在需要审批时直接 dispatch
- `approval -> decision -> dispatch` 形成正式闭环

当前状态：已完成。

本批次交付结果：

- 显式 agent capability operation 已支持 capability 风险判定
- 高风险 operation 已先创建 `approval`，并进入 `waiting_approval`
- approval 批准后再 dispatch，拒绝后 operation 进入 `rejected`
- UI 已能从 operation 面板直接批准或拒绝这类显式审批

下一批将进入：session 真相源收口。

## 2.3 已完成的 Session 真相源收口

本批次范围：

- 收口 `SessionManager` 为 runtime registry
- 让 `Client API` 的 session 存在性优先以数据库为准
- 为 `client/ws` 命令增加 session-thread 归属校验

交付结果：

- `SessionManager` 不再负责生成 session 主键，只接受显式 `session_id` 建立 runtime binding
- `POST /client/messages` 与 `client/ws` 命令都会显式登记 runtime session 绑定
- `App.get_runtime_usage()` 已优先使用数据库 session 判断会话存在性
- 在 `core_domain` 存在时，`client/ws` 会拒绝跨 thread 的 session 命令
- 无数据库依赖的旧测试/legacy 路径仍保留最小兼容

下一批将进入：聊天内确认流并入正式 `Approval` 模型，以及 workspace 治理层收口。

## 2.4 当前进行中的子阶段

当前正在执行的子阶段：`聊天确认流并入正式 Approval`。

范围说明：

- 保留现有 `confirm.requested/confirm.resolved` 事件协议
- 在事件协议之下补齐 approval 资源创建与决策回写
- 先聚焦聊天确认主链，不扩展到所有历史确认分支

阶段出口：

- 聊天确认请求具备可追踪 `approval_id`
- 确认决策可追溯到 `approval` 资源

当前状态：已完成。

本批次交付结果：

- 聊天确认流已具备 `operation + approval` 可审计上下文
- `confirm.requested` / `confirm.resolved` 事件已补充 approval 关联字段
- 前端确认提交已优先走 `POST /client/sessions/{session_id}/confirm-response`
- websocket `confirm_response` 保留兼容路径

下一批将进入：确认流进一步去临时 pending 化，以及 workspace 治理层收口。

## 2.5 当前进行中的子阶段

当前正在执行的子阶段：`Workspace 治理层第一批`。

范围说明：

- 先让 workspace 的 `base_mode`、`prompt_overlay`、`default_execution_target` 真正参与消息与操作主链
- 暂不在本批实现完整 capability overlay / allowlist / workspace routing matrix

阶段出口：

- workspace 不再只是列表项，而会影响 mode、prompt 与默认执行位置

当前状态：已完成。

本批次交付结果：

- workspace 已公开 `description`、`prompt_overlay`、`default_execution_target` 治理字段
- 消息入口缺省 mode 已继承 workspace `base_mode`
- operation 入口缺省执行目标已继承 workspace `default_execution_target`
- prompt 组装时已加入 workspace policy 片段

下一批将进入：workspace capability overlay / allowlist 收口，以及 agent 选路治理。

## 2.6 当前进行中的子阶段

当前正在执行的子阶段：`Workspace Capability Overlay / Allowlist`。

范围说明：

- 先让 workspace 能声明 capability allowlist / overlay 视图
- 先把治理约束接到显式 operation capability 调用主链
- 暂不在本批完成完整 workspace routing matrix

阶段出口：

- workspace 可显式约束哪些 capability 允许进入当前作用域
- 显式 operation capability 调用不再只看 agent binding，还要看 workspace 策略

当前状态：已完成。

本批次交付结果：

- workspace 已支持 `capability_policy=allow_all|allowlist`
- workspace 已支持 `allowed_capability_ids[]`
- 显式 capability operation 已会校验 workspace allowlist
- 当 workspace 开启 allowlist 且 `capability_call` 缺少 `capability_id` 时，请求会被拒绝

下一批将进入：workspace agent 选路治理与 routing policy 第一批。

## 2.7 当前进行中的子阶段

当前正在执行的子阶段：`Workspace Agent 选路治理`。

范围说明：

- 先聚焦显式 capability operation 的 agent 自动选路
- 先实现 workspace 范围内的最小排序偏好与 fallback 语义
- 暂不在本批覆盖所有聊天内隐式工具路由

阶段出口：

- `workspace_any_agent` 与 `prefer_agent_fallback_core` 在显式 operation 上具备真实行为
- workspace 开始影响 agent 选择顺序而不只是 capability 准入

当前状态：已完成。

本批次交付结果：

- workspace 已支持 `preferred_agent_ids[]`
- 显式 operation 已支持 `workspace_any_agent` 自动选路
- workspace 默认 `specific_agent` 现在可以自动补出目标 agent
- `prefer_agent_fallback_core` 在无可用 workspace agent 时已具备显式降级语义

下一批将进入：确认流进一步去临时 pending 化，以及 workspace routing policy 继续扩展。

## 2.8 当前进行中的子阶段

当前正在执行的子阶段：`聊天确认决策收口到 Approval 资源`。

范围说明：

- 优先统一确认决策入口到 `POST /client/approvals/{approval_id}/decision`
- 保留 websocket / confirm-response 兼容路径，但不再把它们视为首选决策面
- 暂不在本批彻底移除 EventBus 等待机制本身，只先压缩其暴露面

阶段出口：

- 聊天确认的批准/拒绝可以由 approval 资源主入口直接驱动
- 确认兼容入口退化为历史兼容层

当前状态：已完成。

本批次交付结果：

- `POST /client/approvals/{approval_id}/decision` 已能直接驱动聊天确认闭环
- 聊天确认不再必须先走 `confirm-response` 专用入口
- 拒绝原因已能沿确认决策路径回写到确认处理链路

下一批将进入：workspace routing / preference policy 第一批。

## 2.9 当前进行中的子阶段

当前正在执行的子阶段：`Workspace Routing / Preference Policy 第一批`。

范围说明：

- 先为 workspace 增加最小 agent 选路策略字段
- 先把排序策略接到显式 operation 的自动选路
- 暂不在本批处理跨 agent 抽象 capability 命名

阶段出口：

- workspace 自动选路会受显式 policy 字段影响
- `preferred_agent_ids`、agent type 偏好和 owner affinity 将进入统一排序体系

当前状态：已完成。

本批次交付结果：

- workspace 已支持 `agent_routing_policy`
- workspace 已支持 `preferred_agent_types[]`
- `workspace_any_agent` 自动选路已进入 policy 驱动排序
- 默认 `specific_agent` 自动补目标时也会使用同一套路由策略

下一批将进入：跨 Agent capability 抽象命名。

## 2.10 当前进行中的子阶段

当前正在执行的子阶段：`跨 Agent Capability 抽象命名`。

范围说明：

- 先为显式 operation 和 agent capability 引入稳定抽象 key
- 保留现有 agent-specific capability id 兼容
- 暂不在本批实现更大范围的 capability catalog 规范迁移

阶段出口：

- operation 可用抽象 capability key 选到具体 agent capability
- 自动选路不再强依赖某个 agent-specific capability id

当前状态：已完成。

本批次交付结果：

- capability 已支持 `abstract_capability_key`
- 显式 operation 已可使用抽象 capability key 进入主链
- workspace 自动选路已可把抽象 key 解析成目标 agent 的具体 capability

下一批将进入：human input 资源语义入口。

## 2.11 当前进行中的子阶段

当前正在执行的子阶段：`Human Input 资源语义入口`。

范围说明：

- 新增补充输入的 HTTP 资源提交入口
- 前端优先走资源语义路径
- 保留 websocket `input_response` 兼容路径

阶段出口：

- 补充输入不再必须依赖 websocket action 才能提交
- `input_response` 退化为兼容层

当前状态：已完成。

本批次交付结果：

- 新增 `POST /client/sessions/{session_id}/human-input-response`
- 前端已优先走 HTTP 资源入口提交补充输入
- websocket `input_response` 仍保留兼容

下一批将进入：capability 级 routing / preference policy 第一批。

## 2.12 当前进行中的子阶段

当前正在执行的子阶段：`Capability 级 Routing / Preference Policy 第一批`。

范围说明：

- 先为 workspace 增加按 capability 粒度覆写 agent 选路的策略结构
- 先接到显式 operation 的自动选路链路
- 暂不在本批扩展到更大范围的 procedure/task routing catalog

阶段出口：

- capability 级策略可以覆写 workspace 全局 agent 选路偏好
- 自动选路不再只有 workspace 一层治理

当前状态：已完成。

本批次交付结果：

- workspace 已支持 `capability_routing_overrides`
- capability 级 override 已可覆写 workspace 全局 agent 选路策略
- 显式 operation 的自动选路已优先应用 capability override

下一批将进入：客户端交互资源化收口第一批。

## 2.13 当前进行中的子阶段

当前正在执行的子阶段：`客户端交互资源化收口第一批`。

范围说明：

- 先让 `GatewayConversationClient` 与 CIL 优先走 confirm / human input 的 HTTP 资源入口
- 保留 websocket action 兼容回退
- 暂不在本批处理 Feishu adapter 的同类迁移

阶段出口：

- CIL 不再默认依赖 websocket action 提交 confirm / human input
- websocket action 明确退居兼容层

当前状态：已完成。

本批次交付结果：

- `GatewayConversationClient` 已支持 confirm / human input 的资源语义提交方法
- CIL 已优先走资源语义入口提交交互响应
- websocket `confirm_response` / `input_response` 已退居兼容回退层

下一批将进入：adapter 交互资源化第二批。

## 2.14 当前进行中的子阶段

当前正在执行的子阶段：`Adapter 交互资源化第二批`。

范围说明：

- 先让 Feishu / gateway adapter 优先走 confirm / human input 的资源入口
- 保留 EventBus 直提交通道与 websocket 兼容回退
- 暂不在本批彻底移除本地 adapter 对 EventBus 的依赖

阶段出口：

- Feishu / gateway adapter 不再默认直连 EventBus 完成交互响应
- adapter 层进一步收口到资源语义主链

当前状态：已完成。

本批次交付结果：

- Feishu formal client chain 已优先走 confirm / human input 的资源入口
- CIL 与 Feishu 已共享 `GatewayConversationClient` 的资源语义提交方法
- EventBus 直提交与 websocket action 已进一步退居兼容回退层

下一批将进入：交互响应服务化收口。

## 2.15 当前进行中的子阶段

当前正在执行的子阶段：`交互响应服务化收口`。

范围说明：

- 引入统一交互响应服务层，承接 confirm / human input 的提交语义
- 先替换 gateway route、CLI、本地 Feishu 兼容链路中的直接 `EventBus.submit_*` 调用
- 暂不在本批修改 EventBus 内部等待机制本体

阶段出口：

- 上层 adapter / route 不再直接依赖 `EventBus.submit_*`
- EventBus 的交互提交接口进一步退到服务层后面

当前状态：已完成。

本批次交付结果：

- 新增 `InteractionResponseService`
- gateway route、CLI、本地 Feishu 兼容链路已统一通过服务层提交交互响应
- 服务层已兼容旧测试夹具和较窄签名的 submitter

下一批将进入：EventBus 可见性收口。

## 2.16 当前进行中的子阶段

当前正在执行的子阶段：`EventBus 可见性收口`。

范围说明：

- 先收口 pending 查询和确认状态快照
- 让 `App`、gateway 和本地 adapter 尽量通过服务层访问交互状态
- 暂不在本批修改 EventBus 内部等待机制本体

阶段出口：

- 上层组件不再直接读取 `EventBus` 的 pending 确认内部字段
- EventBus 的交互状态进一步退到服务层后面

当前状态：已完成。

本批次交付结果：

- `InteractionResponseService` 已扩展为 pending 查询/状态快照门面
- `App` runtime debug 不再直接读取 `EventBus` 的确认 pending 内部字段
- gateway route、CLI、本地 Feishu fallback 已统一通过服务层完成交互提交与查询

下一批将进入：Procedure / Task 与 capability routing policy 的衔接第一批。

## 2.17 当前进行中的子阶段

当前正在执行的子阶段：`Procedure / Task 与 Capability Routing Policy 衔接第一批`。

范围说明：

- 先把 Procedure 接入 capability routing 主链
- 先让 procedure_call 真正带上 capability ref 与 routing preference
- 暂不在本批重写 Task 调度器

阶段出口：

- Procedure 不再只是展示层概念，而会进入 capability routing 主链
- procedure_call 可自动继承 procedure 的 capability / routing 偏好

当前状态：已完成。

本批次交付结果：

- `client/procedures` 已公开 procedure 的 capability / routing 偏好
- `procedure_call` 已自动继承 procedure 的 capability ref、执行目标和 routing preference
- Procedure 的 routing preference 已能参与 workspace 自动选路排序

下一批将进入：Task 调度器接入 capability routing policy。

## 2.18 当前进行中的子阶段

当前正在执行的子阶段：`Task 调度器接入 Capability Routing Policy`。

范围说明：

- 先给 scheduled task 记录 capability/routing 偏好字段
- 先让 claim/background/App scheduled task route context 带出这些偏好
- 暂不在本批把 Task 调度器改造成真正的 operation 创建者

阶段出口：

- scheduled task 已开始进入 capability routing 主链语义
- 后台执行上下文已能看到 task routing 偏好

当前状态：已完成。

本批次交付结果：

- scheduled task 已支持 `preferred_capability_ref`、`preferred_agent_ids`、`preferred_agent_types`、`agent_routing_policy`
- `claim_due_tasks()`、background snapshot、`get_task_by_key()` 已带出 task routing 偏好
- `App._handle_scheduled_task()` 已把这些偏好写入 route_context 和执行输入

下一批将进入：scheduled task 产出 operation 第一批。

## 2.19 当前进行中的子阶段

当前正在执行的子阶段：`Scheduled Task 产出 Operation 第一批`。

范围说明：

- 先覆盖 scheduled task 自动执行主链
- 先在 App 执行器侧创建和更新 operation
- 暂不在本批让 Heart 直接创建 operation，也暂不覆盖所有 scheduled reminder 分支

阶段出口：

- scheduled task 运行开始/结束时会形成正式 operation 记录
- task 快照会记录最近一次 operation 标识与状态

当前状态：已完成。

本批次交付结果：

- scheduled task 开始执行时会创建正式 `operation`
- scheduled task 完成或失败时会更新 operation 状态与摘要
- task 快照已记录最近一次 operation 标识与状态

下一批将进入：scheduled reminder 产出 operation。

## 2.20 当前进行中的子阶段

当前正在执行的子阶段：`Scheduled Reminder 产出 Operation`。

范围说明：

- 先覆盖 scheduled reminder 后台处理分支
- 复用 scheduled task 的 operation helper 与快照回写逻辑
- 暂不在本批让 Heart / scheduler 直接创建 operation

阶段出口：

- scheduled reminder 开始/结束时会形成正式 operation 记录
- task 快照会记录最近一次 reminder operation 标识与状态

当前状态：已完成。

本批次交付结果：

- scheduled reminder 开始处理时会创建正式 `operation`
- scheduled reminder 完成后会更新 operation 状态与摘要
- task 快照已记录 reminder 最近一次 operation 标识与状态

下一批将进入：Electron 第一版产品化收口。

## 2.21 当前进行中的子阶段

当前正在执行的子阶段：`Electron 第一版产品化收口`。

范围说明：

- 先聚焦主聊天界面的产品化信息架构收口
- 强化 Core / Local Agent / Workspace 状态与 workspace 治理信息可见性
- 继续压缩主路径里的开发态信息暴露

阶段出口：

- Electron 主界面更接近第一版可用产品，而不是开发态控制台
- 主路径能直接解释“当前连到了谁、在哪个 workspace、有哪些正在执行的事情”

当前状态：已完成。

本批次当前已交付：

- 输入框已允许在未连通时先输入草稿
- 标题栏已移除 `Procedure` 主路径入口
- 标题栏已改为展示 `Core / Agent / Workspace` 状态与当前 workspace 信息
- 主界面已新增 workspace 信息区
- 诊断入口已降到 workspace 卡片中的次级入口
- 主界面已显式展示运行中的 operation、待审批数和待补充输入数

本批次结论：Electron 主界面已基本脱离开发态控制台形态，更接近第一版可用产品。 

## 2.22 当前进行中的子阶段

当前正在执行的子阶段：`Heart / Scheduler 显式 Operation 创建`。

范围说明：

- 先让 scheduler 在 claim due task 后预创建 operation
- 继续保留 scheduler -> control event -> App 执行主链
- 先让 App 复用预创建 operation，而不是立即重写整条后台调度架构

阶段出口：

- Heart 调度器会在 claim 后创建 operation
- App 处理 scheduled task / reminder 时会优先复用该 operation

当前状态：已完成。

本批次交付结果：

- Heart 调度器已在 claim due task 后预创建 operation
- control event 已携带 `operation_id`
- App 已会优先复用 Heart 预创建的 scheduled task / reminder operation

下一批将进入：Electron 第一版产品化收口，以及其余 adapter/channel 服务化迁移评估。

当前状态：已完成。

本批次交付结果：

- scheduled reminder 开始处理时会创建正式 `operation`
- scheduled reminder 完成后会更新 operation 状态与摘要
- task 快照已记录 reminder 最近一次 operation 标识与状态

下一批将进入：其余 adapter/channel 服务化迁移评估，以及 Heart / scheduler 是否演化为显式 operation 创建者的判断。

当前状态：已完成。

本批次交付结果：

- scheduled task 开始执行时会创建正式 `operation`
- scheduled task 完成或失败时会更新 operation 状态与摘要
- task 快照已记录最近一次 operation 标识与状态

下一批将进入：scheduled reminder 是否接入 operation 主链，以及其余 adapter/channel 服务化迁移评估。

## 3. 当前基线

### 3.1 运行时与主链现状

| 领域 | 当前现状 | 结论 |
| --- | --- | --- |
| 运行入口 | 正式入口已统一为 `python main.py service`，service 运行时内置 HTTP / WebSocket gateway | 已完成 |
| 网关 surface | `gateway/routes/client.py`、`agent.py`、`operator.py`、`developer.py` 已拆分，`tests/test_gateway_surface_routes.py` 覆盖关键路由 | 部分完成 |
| 旧聊天主路径 | `POST /inputs`、`POST /controls` 已返回 404；根路径 `/ws` 仅返回 `legacy_websocket_path_removed` | 已完成 |
| 数据与持久化 | `core/db/` 下已具备 Alembic、engine、repository、bootstrap 与主资源模型 | 已完成 |
| Client 主链 | `client/workspaces`、`threads`、`sessions`、`messages`、`operations`、`approvals` 与 `client/ws` 可闭环 | 部分完成 |
| PC 客户端本地后端 | `desktop_agent/` 已具备配置、hello、heartbeat、capabilities snapshot 与 capability call 处理 | 已完成 |
| 本地能力边界 | `exec_sys_cmd`、文档读写、工作区分析与桌面 MCP 已通过 Agent capability 承接 | 已完成 |
| 平台依赖边界 | `platform_layer/` 仅保留运行宿主机平台识别、系统生命体征与上下文感知 | 已完成 |
| 业务状态后端 | memory、task、office、study、source catalog 已接入数据库或 state blob 后端 | 已完成 |
| Workspace / Memory / Procedure | workspace 与 agent、thread、operation 绑定已建立；memory tags 已入库；Procedure 已资源化并支持 thread pin | 部分完成 |

### 3.2 与 `implementation-plan.md` 的阶段映射

| Phase | 目标摘要 | 当前判断 | 依据 | 主要剩余项 |
| --- | --- | --- | --- | --- |
| Phase 0 | 文档与基线 | 已完成 | 目标设计文档、运行迁移文档、当前基线文档已收口 | 后续只需持续与代码同步 |
| Phase 1 | 数据模型与持久化骨架 | 已完成 | `core/db/bootstrap.py`、`core/db/models/*`、相关测试 | 仅剩兼容导入脚本的长期清理 |
| Phase 2 | Core API 分层与新资源骨架 | 部分完成 | `gateway/routes/client.py`、`agent.py`、`operator.py`、`developer.py` 已拆分 | 仍保留部分根路径兼容 surface |
| Phase 3 | Thread / Session / Operation / Approval 主链 | 部分完成 | `client/threads`、`sessions`、`messages`、`operations`、`approvals` 已可用 | approval 仍未真正成为执行主链的一等对象 |
| Phase 4 | PC 客户端内本地后端最小运行时 | 已完成 | `desktop_agent/runtime.py` 与相关测试 | 需要转入更完整的生产级能力治理 |
| Phase 5 | 本地工具剥离到客户端内本地后端 | 已完成 | shell、文件、工作区分析与桌面 MCP 已走 capability 分发 | 仅剩安全级 Core MCP 的长期治理说明 |
| Phase 6 | Frontend 迁移到 Client API | 部分完成 | `useMeetYou.ts` 已切到 `clientApi.ts` + `client/ws` 主链 | UI 仍带明显开发控制台姿态 |
| Phase 7 | 附件通道与对象存储 | 部分完成 | `Attachment` 模型与 `AttachmentService` 已有骨架 | upload ticket、complete、download flow 未完成 |
| Phase 8 | Workspace / Memory / Procedure 收口 | 部分完成 | workspace 资源、agent 绑定、memory records 与 Procedure 已入库 | workspace 治理语义仍未完整落地 |
| Phase 9 | Edge Agent MQTT | 未开始 | 当前仓库无 MQTT bridge、pull.next、edge sample 主链 | 整体待启动 |
| Phase 10 | 清理旧路径与稳定化 | 进行中 | 旧主聊天路径已退出，旧 spec 与兼容文档已开始清理 | 根路径兼容接口、双模型与旧语义仍待收口 |

## 4. 旧功能映射

### 4.1 主能力映射表

| 旧能力 | 当前入口 | 当前持久化归属 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| 聊天主链 | `POST /client/messages` + `GET /client/ws` | thread / session / message / operation 数据库表 | 已迁移 | Electron、CIL、Feishu 都已经通过新主链接入 |
| 配置中心 | `GET/PATCH /operator/config`、`GET /operator/schema/ui` | `config_entries` + state blob | 已迁移 | 前后端不再需要旧配置枚举硬编码 |
| 记忆页 / 记忆快照 | `GET /operator/memory`、`GET /operator/memory/graph` | `memory_records` + `memory_workspace_tags` + `memory_graph` state blob | 已迁移 | 文件只保留一次性导入兼容 |
| 本地文件读写 | Core tool -> capability dispatch -> PC 客户端本地后端 | 操作审计在服务端，文件内容在终端本地 | 已迁移 | `read_local_documents`、`write_local_document`、`rewrite_local_document` 已走终端后端 |
| 本地命令执行 | Core tool -> agent dispatcher -> `shell.exec` | 操作审计在服务端，命令执行在终端本地 | 已迁移 | Core 本地 fallback 默认关闭 |
| 工作区分析 | Core tool -> agent dispatcher -> `workspace.analyze` | 操作审计在服务端，分析执行在终端本地 | 已迁移 | 结果已能回流主链 |
| 本地 MCP | PC 客户端本地后端 MCP runtime + Core 安全级 MCP | 终端能力集 + Core 安全服务 | 已迁移 | `user/mcp_servers.json` 由 Desktop Agent 托管 |
| CIL | `clients/gateway_client.py` -> `client/* + client/ws` | 服务端主链 | 已迁移 | `cil/client.py` 已按 thread/session 方式接入 |
| Feishu 输入输出 | `GatewayConversationClient` -> `client/* + client/ws` | 服务端主链 | 部分迁移 | 正式链路可用，但兼容事件总线分支仍未完全移除 |
| Task | `TaskManager` + 后台调度 | `task_store` state blob + 数据表骨架 | 已迁移 | 运行态主读写已不再依赖 `user/*.json` |
| Office | `OfficeTools` | `office_state` state blob | 部分迁移 | 状态后端已切 DB，但尚未进入 workspace 一等模型 |
| Study | `StudyTools` | `study_progress` state blob | 部分迁移 | 状态后端已切 DB，但尚未进入 workspace 一等模型 |
| 旧 `/inputs`、`/controls`、根 `/ws` | 无业务入口 | 无 | 已下线 | 保留的仅是迁移错误与兼容提示 |

### 4.2 当前验收关注项

| 验收项 | 当前判断 | 说明 |
| --- | --- | --- |
| Core 启动与数据基线 | 通过基础骨架 | migration、bootstrap、operator config/memory 读取链路已存在 |
| 新聊天主链 | 基本通过 | route 与 websocket 主链已齐备，仍需更多 end-to-end 验证 |
| 终端后端基线 | 通过最小运行时 | hello、heartbeat、capabilities snapshot 与 call request 已覆盖 |
| 本地能力基线 | 通过 | 文件、shell、workspace analyze 与桌面 MCP 已走终端后端 |
| 平台依赖边界 | 通过 | Core 仅保留 host sensing 与运行宿主机相关感知 |
| 旧入口对齐 | 基本通过 | CIL 已改走新主链；Feishu 仍有兼容分支待收口 |
| 业务状态基线 | 基本通过 | memory/task/office/study/source catalog 已切 DB 或 state blob |

## 5. 缺口矩阵

| 缺口 | 当前表现 | 影响 | 优先级 | 建议归属阶段 |
| --- | --- | --- | --- | --- |
| 审批模型未真正统一 | 高风险确认仍主要通过 `EventBus` pending request 驱动，而不是 `Approval` 领域对象主链 | 会让跨端审批、审计与权限模型长期分裂 | P1 | Phase 3 / Phase 8 收口 |
| Session 双模型并存 | 数据库 `session` 与运行时 `SessionManager` 同时承担会话职责 | 与“服务器唯一真相源”不一致，也会增加跨端协同复杂度 | P1 | Phase 3 收口 |
| Workspace 仍未成为完整治理中心 | 数据模型已在，但 prompt overlay、capability overlay、执行目标与 UI 体验仍未完整贯通 | 无法支撑你要的设备组 / 情景 / 联动体系 | P1 | Phase 8 收口 |
| 关键枚举与术语分裂 | `mode`、`execution_target`、approval 语义在文档、种子数据和前端间仍不一致 | 容易继续在错误模型上叠加功能 | P1 | 立即收口 |
| 前端仍偏开发壳 | 默认 localhost、自动创建 `Desktop Chat`、保留 `Agent Echo` 调试姿态、状态表达仍偏开发态 | 与真实 Client 产品角色不一致 | P2 | Phase 6 收口 |
| 根路径兼容 surface 仍存在 | `/config`、`/memory`、`/runtime/*` 等根路径接口仍在 | 新开发者容易继续误用旧语义 | P2 | Phase 10 收口 |
| 附件通道未闭环 | 只有入口和模型骨架，缺少 upload/download 主链 | 无法承接截图、文档等真实跨端对象流 | P2 | Phase 7 |
| Edge Agent / MQTT 未启动 | 当前无 bridge、topic 规范、pull 模式样例 | 边缘设备接入无落地路径 | P2 | Phase 9 |

## 6. 推荐后续顺序

### 阶段 A：模型与文档收口

1. 清理 legacy/spec 残留与过期说明
2. 统一 `mode`、`execution_target`、approval、session/thread/operation 术语与枚举
3. 把当前真源文档稳定到 `docs/` 下的目标架构、实施计划、迁移说明和本文档

当前状态：进行中。

### 阶段 B：核心模型一致性

1. 让 approval 真正进入执行主链
2. 收口 session 真相源，压掉 `SessionManager` 的越权职责
3. 让 workspace 真正承担 prompt、capability、执行目标与设备编组治理

### 阶段 C：附件闭环

1. 实现 attachment upload ticket / complete / download flow
2. 在 Desktop Agent 补齐 uploader
3. 在前端补齐下载、回显和操作入口

### 阶段 D：Edge Agent / MQTT

1. 建立 Agent Gateway / MQTT bridge 与 topic 规范
2. 实现 `agent.pull.next` 与 `capability.call.lease`
3. 提供 edge agent 最小样例与集成测试基线

## 7. 当前架构审查结论

- 项目已经具备 `Core + Client API + Desktop Agent` 的主骨架，这部分方向是对的
- `App` 仍然是超大装配点，`Brain`、`Heart`、`Gateway`、`EventBus`、状态后端与运行时控制仍过度耦合
- 运行时虽然声明了 `session_execution / background_jobs / tool_execution / delivery / telemetry` 边界，但实际执行仍是单体内协作，不是清晰的运行时内核分层
- 审批、会话、workspace 三个模型都已经“有表、有接口、有文档”，但还没有完全进入真实主链，这正是现在最需要收口的地方
- 前端已经不再是旧 UI，但仍更像开发控制台，而不是真正面向你的稳定 Client

## 8. 文档使用建议

- 目标架构以 `core-client-agent-architecture.md`、`workspace-capability-model.md`、`core-api-surfaces.md`、`agent-protocol-v1.md` 为准
- 当前执行优先级、缺口判断与架构审查以本文档为准
- 破坏性运行迁移以 `runtime-migration.md` 为准
- 后续每完成一个阶段，应同步更新本文档中的“阶段映射”“旧功能映射”和“缺口矩阵”
