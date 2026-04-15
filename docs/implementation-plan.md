﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿# MeetYou V2 Implementation Plan

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
- 为未来 Edge Agent / workspace 协调打通统一执行节点模型

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

1. `Client`

- Electron 可通过 `client/* + client/ws` 完成聊天、审批、任务查看，并至少展示当前 workspace / operation / procedure 上下文
- Electron 已提供独立“工作区与规程”管理页，用于承接 workspace 治理编辑、procedure 上下文浏览，以及运行中 operation / approval / human input 聚合状态
- 主窗口状态反馈已收口为 `StatusIsland` 顶层连接/思考态 + operation `tone/summary` 细粒度执行态的双层模型
- 主要交互 pending 已优先走资源语义入口

1. `Agent`

- Desktop Agent 可完成 capability 上报、调用、结果回传
- 本地文件/命令/MCP 已不再要求 Core 直接执行

1. `Workspace 治理`

- 已具备默认 mode、默认执行目标、capability allowlist、agent routing policy、capability routing override
- 这些治理字段确实参与主链，而不只是展示配置

1. `后台任务`

- `Core Heart` 已成为服务端时间编排中枢：`scheduler loop` 负责 claim / pre-create operation / control event，`heartbeat reasoning loop` 负责判断时间压力并驱动后台提醒推理
- `assistant_schedule` 域下的 scheduled task / scheduled reminder 已进入 operation 主链；`user_todo` 继续作为用户待办域，不参与 Heart 的自动 claim
- task 快照可追踪最近一次 operation 标识与状态

1. `可验证性`

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

- Edge Agent 能力集全量落地
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
Phase 9  Edge Agent transport 收口
Phase 10 清理旧路径与稳定化
```

当前已确认的下一阶段推进顺序补充如下：

1. 先执行 legacy/spec 文档清理，并统一 `mode`、`execution_target`、审批与会话相关术语，避免继续在错误模型上叠加实现
2. 再收口 Phase 3 与 Phase 8 之间仍未统一的核心模型，重点是 approval 主链、session 真相源、workspace 治理边界
3. 在核心模型一致后推进 Phase 7 附件闭环，补齐 upload ticket / complete / download 主链
4. 最后再启动 Phase 9 Edge Agent transport 收口，避免边缘接入与主链收口交叉放大复杂度

### 4.3 当前已冻结决策

当前实施阶段已经冻结以下公开语义，后续开发默认按此执行：

- 用户态 mode 固定为：`general`、`research`、`documents`、`study`、`automation`、`danxi`
- `auto`、`normal`、`office` 不再作为公开产品枚举继续扩散；现阶段仅允许作为内部 legacy 映射存在
- `execution_target` 固定为：`core_only`、`specific_agent`、`workspace_any_agent`、`prefer_agent_fallback_core`
- `assistant`、`core`、`desktop` 不再作为正式执行目标枚举继续扩散；仅允许在兼容层做一次性映射
- Feishu 旧 event bus fallback 进入待删除路径，不再视为正式主链
- 正式服务端持久化依赖为 PostgreSQL，不再把文件型状态视为正式运行选项

### 4.4 执行说明

- 本文档现在只保留稳定的 `Phase -> Feature -> Task` 计划结构，不再展开历史“当前执行批次”正文
- 已完成工作的判断，以 feature 状态、Phase 验收条件与当前实现/测试为准
- Feature 清单中的 `关联批次` 仅作为历史回溯标签，便于对照旧提交脉络；正文不再要求保留同编号批次段落
- 如果后续需要再次记录短周期执行节奏，只保留“当前批次”或“下一批”两类简短说明，不再把全文写成施工日志

### 4.5 当前优先特性

默认推进顺序如下；若用户当轮有明确目标，以用户目标优先：

1. `F102` Danxi 二阶段收口：正式子页面、自动恢复登录态、凭证加密与验证口径
2. `F92` / `F93` Edge Agent transport 稳定化与能力扩展
3. `F100` / `F101` 旧路径清理与稳定化文档收口
4. 继续收口附件与 workspace 相关文档尾差

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
- Feature 清单中的 `关联批次` 仅作历史回溯标签；正文不再维护完整批次日志

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
- `F78` Attachment 工具化与统一对象回传模型。范围：Agent / Tool 通过 `attachment_outputs` 声明附件产物，Desktop Agent 负责 upload-ticket / upload / complete 收口，Core 统一归一化为 attachment object view 并挂接到 operation / message。边界：`desktop_agent/runtime.py`、`gateway/routes/agent.py`、`core/services/attachment_service.py`、`meetyou-ui/src/hooks/core/useOperations.ts`。状态：已完成。
- `F76` 对象存储产品化收口。已完成内容：`s3_compatible` backend 下 attachment 下载已优先返回预签名 URL，并保留 Core 代理下载作为兼容回退；部署配置说明与 S3-compatible 验收口径已同步收口。边界：`core/storage/`、`gateway/routes/client.py`、`docs/`。状态：已完成。
- `F77` 短生命周期截图附件与清理策略。已完成内容：截图类 attachment 默认归入 `ephemeral` 生命周期，写入短 TTL，并由后台清理过期资源；Desktop Agent 对临时截图/`ephemeral` 附件上传成功后会清理本地缓存文件。边界：`desktop_agent/`、`core/services/attachment_service.py`、后台清理任务。状态：已完成。
- `F79` Attachment 治理入口与用户面收口。已完成内容：Core 提供附件列出/读取/删除能力及对应助手工具；前端上传成功反馈移出聊天流并收口到状态反馈区；新增独立“附件管理”页面，支持查看关键时间戳、下载和删除。边界：`core/services/attachment_service.py`、`gateway/routes/client.py`、`tools/attachment_tools.py`、`meetyou-ui/src/App.tsx`、`meetyou-ui/src/AttachmentsWindow.tsx`、`components/status/`。状态：已完成。

##### Phase 8

###### Workspace Governance

- `F80` Workspace 作用域默认值与 prompt policy 主链化。范围：让 `base_mode`、`prompt_overlay`、`default_execution_target` 成为真实治理输入，而不是静态展示字段。边界：`core/services/workspace_service.py`、`core/prompt_assembler.py`、`gateway/routes/client.py`。关联批次：`4.8`。状态：已完成。
- `F81` Workspace capability 准入策略。范围：allowlist / overlay 对显式 capability operation 生效。边界：`core/services/workspace_service.py`、`gateway/routes/client.py`、`core/services/capability_service.py`。关联批次：`4.9`。状态：已完成。
- `F82` Workspace agent 成员关系与默认选路。范围：workspace 绑定的 agent、`workspace_any_agent`、默认 `specific_agent` 补目标 agent。边界：`core/services/agent_service.py`、`core/services/workspace_service.py`、`gateway/routes/client.py`、`meetyou-ui/src/hooks/core/useClientContext.ts`。关联批次：`4.10`、`4.12`。状态：已完成。
- `F83` Workspace capability 级 routing policy。范围：抽象 capability key、capability routing override、workspace 全局 routing preference 的统一决策。边界：`core/services/workspace_service.py`、`core/services/capability_service.py`、`gateway/routes/client.py`。关联批次：`4.13`、`4.15`。状态：已完成。
- `F87` Workspace memory ranking 与 source-profile policy。范围：workspace 记忆排序、来源标记、source profile 偏好进入统一治理层。边界：`core/memory/`、workspace 查询服务、相关前端 workspace 视图。状态：已完成。
  已交付：workspace `preferred_source_profiles` / `memory_ranking_policy` 正式进入 governance surface、消息 metadata 与 route context；procedure 推荐来源优先于 workspace 偏好；`GET /operator/source-profiles` 与 `PATCH /operator/workspaces/{workspace_id}` 已提供受控目录与校验；Electron 独立“工作区与规程”窗口已提供只读展示与受控编辑 UI。
- `F94` 管理页与状态反馈模型收口。范围：独立“工作区与规程”窗口承接 workspace 概览、治理编辑、procedure catalog/detail、运行中 operation / approval / human input 聚合状态；主窗口状态反馈统一为 `StatusIsland` 顶层状态 + operation `tone/summary` 细粒度状态。边界：`meetyou-ui/src/WorkspaceWindow.tsx`、`components/workspace/`、`components/status/`、`hooks/core/useOperations.ts`、`docs/`。状态：已完成。

###### Procedure / Task / Scheduler Integration

- `F84` Procedure 执行画像与 routing integration。范围：让 `procedure_call` 继承 procedure 的 capability ref、执行目标与 agent routing 偏好。边界：`core/services/procedure_service.py`、`gateway/routes/client.py`。关联批次：`4.20`。状态：已完成。
- `F85` Task routing preference integration。范围：让 scheduled task 记录并输出 capability / routing 偏好。边界：`tools/task_manager.py`、`core/app.py`、`core/services/operation_service.py`。关联批次：`4.21`。状态：已完成。
- `F86` Scheduler operation 审计主链与 Heart 时间编排收口。范围：让 `Core Heart` 成为服务端时间编排中枢，明确 Heart 内部 `scheduler loop` 与 `heartbeat reasoning loop` 的职责边界；确保 scheduled task / reminder / scheduler 进入统一 operation 记录与状态流；让 heartbeat reasoning 显式消费 `pending_redelivery`、`awaiting_completion`、逾期 follow-up 等调度时间压力，而不是只保留 `system_issue` / `idle_poke`。边界：`core/heart.py`、`core/app.py`、`tools/task_manager.py`、`core/background_status.py`。关联批次：`4.22`、`4.23`、`4.25`。状态：已完成。
- `F89` Task domain split and semantic isolation。范围：将 `manage_tasks` / `manage_scheduled_tasks` 明确分域为 `user_todo` / `assistant_schedule`，收口对象类型、持久化表示、完成语义、调度行为与后台统计，避免共享语义继续扩散。边界：`tools/task_manager.py`、相关测试、任务快照输出。关联批次：`4.24`、`4.25`。状态：已完成。
- `F88` Procedure 自动推断与生命周期治理。范围：自动 procedure 推断、thread 级固化 / 取消固化、AI 发起的 Procedure create / update / delete 回调确认，以及只读 procedure catalog / 内容视图。边界：`core/db/models/procedure.py`、`core/db/models/thread.py`、`core/services/procedure_service.py`、`core/services/thread_service.py`、`core/interaction_response_service.py`、`core/services/approval_service.py`、`gateway/models.py`、`gateway/routes/client.py`、`core/brain.py`、`core/prompt_assembler.py`、Procedure 只读视图。状态：已完成。
  已交付：deterministic procedure 自动推断、thread 级 `latest_inferred_procedure` / `pinned_procedure` 上下文、AI 可通过 callback confirmation 驱动 `manage_procedures` 进行 create / update / delete、`GET /client/procedures` / `GET /client/procedures/{procedure_id}` / `GET /client/threads/{thread_id}/procedure-context` / `PUT|DELETE /client/threads/{thread_id}/pinned-procedure`、以及 Electron 独立“工作区与规程”窗口中的 procedure catalog / detail / pin / unpin 浏览与操作。

##### Phase 9

- `F90` Edge Agent 协议骨架与统一 websocket transport。边界：`edge_agent/protocol.py`、`edge_agent/runtime.py`。关联批次：`4.30`。状态：已完成。
- `F91` Edge Agent 正式运行目标。边界：`edge_agent/main.py`、`main.py`。关联批次：`4.33`。状态：已完成。
- `F92` Edge Agent transport 稳定化。范围：统一 `WSS /agent/ws` 心跳、重连、注册与 capability call 基线，并确保 `agent.hello.ack` 下发的新 heartbeat interval 能立即作用到当前连接。边界：`edge_agent/`、`gateway/routes/agent.py`、相关测试。状态：已完成。
- `F93` Edge Agent 能力扩展与稳定性测试。范围：补齐 Edge Agent 的协议/运行时稳定性测试、heartbeat 协商回归、最小 capability 样例与验证路径文档；当前 `tests/test_edge_agent_protocol.py`、`tests/test_edge_agent_runtime.py` 已覆盖 schema、`agent.hello.ack` 心跳重排与最小 echo capability，`tests/test_gateway_agent_api.py` 可补 Gateway 侧注册/调用联调。边界：`edge_agent/`、`tests/test_edge_agent_*`、边缘 capability 样例、`docs/`。状态：进行中。

##### Phase 10

- `F100` Legacy path cleanup。范围：旧 `session + /inputs + /ws` 主路径、Core 直执行本地工具、过期兼容入口，以及非端侧 integration-style tools / MCP 到 `Core MCP` 的边界收口。边界：`gateway/`、`core/`、`desktop_agent/`、`docs/`。状态：已完成。
- `F101` 稳定化与验收文档收口。范围：README、启动手册、手工验收、回归命令统一，以及以下四类边界同步到计划/设计/验收文档：1）Heart 时间编排与 Heart 时间感信号；2）agent heartbeat 协商与重排行为；3）`user_todo` / `assistant_schedule` 的术语、职责与实现边界；4）附件工具化、独立管理页与双层状态反馈模型。边界：`README.md`、`docs/`、`scripts/`。状态：已完成。
- `F102` Danxi 模式与工具套件。范围：新增公开 `danxi` 模式与“旦夕”前端文案；引入 Danxi 普通用户工具套件（论坛浏览、帖子/楼层搜索、发帖、回帖、编辑、删除、收藏/订阅、消息读取）；通过可选 WebVPN 路由支持非校园网访问；同步前端模式枚举、workspace `base_mode` 治理编辑、计划/设计/验收文档与 `AGENTS.md`；新增 Electron 内嵌 WebVPN 登录窗与 Danxi 独立面板，并在二阶段把该面板从只读原型收口为紧凑三栏正式子页面，补齐用户信息、回复/编辑/删除回复、AI 摘要与状态反馈；Danxi JWT / WebVPN cookie 会经加密后持久化到服务端状态后端并在重启后自动恢复，会话失效时自动清理；Electron main 进程会在 `client/danxi/session/login` 与 `client/danxi/session/webvpn-cookie` 两条入口前使用共享密钥对敏感载荷做 `aes-256-gcm` 加密封装，Gateway 仅在对应 purpose 下解密。边界：`core/public_contract.py`、`core/assistant_modes.py`、`core/credential_transport.py`、`tools/danxi_tools.py`、`gateway/routes/client.py`、`gateway/routes/operator.py`、`meetyou-ui/src/`、`meetyou-ui/electron/`、`docs/`。状态：进行中（实现与文档已落地，待最终回归与人工验收）。

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

1. 固定公开 mode 枚举为 `general | research | documents | study | automation | danxi`
2. 固定 `execution_target` 枚举为 `core_only | specific_agent | workspace_any_agent | prefer_agent_fallback_core`
3. 清理 Procedure、前端类型、API 请求响应中的旧枚举值
4. 在 Core 输入侧增加 public-to-legacy 过渡映射

### 验收

- 前端不再发送 `normal`、`auto`、`office`、`desktop`、`assistant` 等旧公开值
- Client API 输出的 Procedure 和 Operation 枚举为新值
- 旧内核仍可通过过渡映射运行

## 6. Danxi Feature 说明

### 6.1 范围

- 新增公开模式 `danxi`，前端产品文案显示为“旦夕”
- Danxi 工具只在 `danxi` 模式下暴露；其他模式保持不可见
- 首批 Danxi 工具只覆盖普通用户、低风险论坛能力：登录、浏览、检索、发帖、回帖、编辑、删除、收藏、订阅、消息读取
- 非校园网场景下，Danxi 客户端支持按 PDF 文档口径进行 1 秒直连探测，失败后通过 WebVPN URL 代理访问论坛 API
- Danxi 独立窗口二阶段目标是“正式可用子系统”，不再停留在只读面板：保留三栏信息架构，同时收口为更紧凑的桌面布局，并补齐用户信息、回复、编辑回复、删除回复、AI 摘要与明确的成功/失败状态反馈
- Danxi 会话二阶段需要支持安全自动恢复：Danxi JWT、refresh token、WebVPN cookie 与必要用户信息会以加密封装形式写入状态后端，下次启动时自动尝试恢复；恢复态必须先做一次低风险有效性校验，再决定保留或清理
- Danxi 凭证跨进程链路二阶段需要默认加密：Electron main 负责在发起 Danxi 登录与 WebVPN cookie 更新前，使用共享密钥与 purpose 派生 key 对 email/password/cookie 等敏感字段做 `aes-256-gcm` 封装；Gateway 只接受对应 `encrypted_credentials`，缺少时直接拒绝，不再保留明文跨边界 fallback，并且只在 purpose 匹配时解密

### 6.2 非范围

- 不接入管理员接口、批量删改、审计/封禁、敏感内容治理等高权限能力
- 不做高并发压测、批量回灌或其他可能影响论坛稳定性的测试
- 当前已支持 Electron 内嵌 WebVPN 登录窗，由用户手动完成 WebVPN/CAS 登录后自动提取 cookie；仍不做高脆弱度的自动表单提交
- 不在日志、调试输出、测试快照或错误对象中保留明文 Danxi/WebVPN 凭证；文档与实现都不应再鼓励通过未加密 payload 直接跨边界传输这些字段，Danxi 登录与 WebVPN 更新接口也不再接受这类明文请求
- Danxi 前端虽然已具备独立窗口中的普通用户操作，但仍不追求替代全部聊天工作流；复杂写作、组合任务和高风险操作仍以助手工具与顺序化人工校验为主

### 6.3 验收约束

- 真实验收必须低频、顺序化，行为节奏应接近正常用户
- 写操作只做最小必要验证，优先选择可控测试内容并避免破坏性删改
- 若在校外网络联调，必须明确记录是否走直连或 WebVPN 路由
- 二阶段最小回归顺序固定为：`tests/test_danxi_tools.py`、`tests/test_assistant_modes.py`、`tests/test_gateway_surface_routes.py`，然后执行前端 `npm run typecheck` 与 `npm run test`
- 二阶段人工验收至少覆盖：子页面布局在窄窗/常规窗/宽窗下无异常；自动恢复登录成功或会话失效后自动清理；帖子回复、编辑回复、删除回复、AI 摘要与状态反馈闭环可用；若使用 WebVPN，记录登录窗提取 cookie 是否成功

### 6.4 当前阶段目标与状态

- 当前阶段目标：把 Danxi 从“模式 + 工具 + 只读面板”推进到“正式桌面子页面 + 安全会话恢复 + 默认加密传输 + 明确验证口径”
- 当前状态：二阶段实现与文档口径已收口，尚待执行最小相关回归与低风险人工验收

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
   - workspace\_agent\_memberships
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
- richer Client 本阶段已补齐 connection / session / operation 状态分层、approval / human input 一等 UI、附件入口占位以及 devtools debug 迁移；Procedure 不再作为主路径执行入口
- 当前产品化信息架构已收口为“主窗口 + 独立管理页”双面：主窗口负责聊天和即时反馈，独立“工作区与规程”窗口负责 workspace / procedure 管理和状态聚合
- 状态反馈采用双层模型：`StatusIsland` 负责连接/思考中的顶层反馈，operation 列表负责 `tone/summary` 级别的执行态反馈
- `/runtime/debug` 的迁移目标是独立 devtools 调试面；上下文 / token 用量面仍保持独立 stats / usage 窗口，不应被折叠进 workspace / procedure 面板
- 下一步重点改为 Phase 7 的附件闭环，而不是继续在主窗口补零散占位

### 输入依赖

- Phase 2
- Phase 3
- `core-api-surfaces.md`

### 主要任务

1. 建立前端 connection store
2. 重构 `useMeetYou` 为多 store / 多 hook 结构
3. 引入 thread/session/operation 概念到 UI 状态
4. 把审批与附件入口做成一等 UI 对象，并为 Procedure 预留只读状态 / 内容展示位
5. 把 workspace / procedure 治理与状态聚合收口到独立管理页，而不是继续堆叠在主聊天面
6. 将 `/runtime/debug` 移到 devtools 面

### 测试

- typecheck
- 组件测试
- 断线重连与 operation 状态同步测试

### 验收

- 前端主路径只依赖 Client API
- 跨 session operation 可在 UI 中正常展示
- approval / human input / attachment 入口已作为主路径显式对象出现；Procedure 不要求主路径可执行，只需能承接状态展示
- “工作区与规程”管理页可展示 workspace 概览、治理编辑、procedure catalog/detail，以及运行中 operation / approval / human input 聚合状态
- 主窗口状态反馈已区分顶层连接/思考态与 operation 细粒度执行态，避免只剩开发态日志式反馈
- `/runtime/debug` 已迁到独立 devtools 面
- 上下文 / token 用量面保留独立窗口入口，不与 workspace / procedure 面板混用

## Phase 7 附件通道与对象存储

### 目标

- 附件脱离主消息流
- 建立 upload ticket / complete / download ticket
- 将当前主窗口附件入口占位升级为真实可上传、可回显、可下载的 attachment reference 主链

### 当前状态补记

- `client` 与 `agent` 两侧的 upload ticket / complete / download ticket 主链已经可用
- object store 抽象与 `s3_compatible` backend 已落地，且 `F76` 已补齐预签名下载 URL 与兼容回退
- attachment 下载当前优先走对象存储预签名 URL；不支持直链时回退到 Core 代理下载内容
- 截图类 attachment 的短生命周期与清理策略已由 `F77` 收口，包含后台过期清理与 Desktop Agent 本地缓存回收
- Agent 侧附件输出已收口为工具化模型：tool / capability 只声明 `attachment_outputs`，由 Desktop Agent 完成上传，再由 Core 统一归一化为 attachment object view 挂到 operation / message
- Core 与助手现已支持附件列出、读取、删除三类治理能力，返回带关键时间戳的结构化附件记录
- 主窗口上传成功反馈已移出聊天流，改由状态反馈区承接；独立“附件管理”页负责查看、下载、删除附件

### 输入依赖

- Phase 1
- Phase 4
- `storage-and-binary-transfer.md`

### 主要任务

1. Core 中实现附件元数据与 ticket 服务
2. 在客户端内本地后端实现 attachment uploader，并把 tool / capability 的 `attachment_outputs` 收口为统一 attachment object
3. 前端中实现 attachment download flow 与统一对象视图回显
4. 支持截图类短生命周期附件

### 测试

- ticket 签发测试
- 上传完成测试
- 下载权限测试
- 短生命周期清理测试

### 验收

- 桌面截图可上传并回传 attachment reference
- 飞书或前端可下载查看
- tool / capability 产生的附件可通过 `attachment_outputs -> attachment object view` 主链在 operation / message 中稳定回显

## Phase 8 Workspace / Memory / Procedure 收口

### 目标

- 让 workspace 成为真实作用域
- 收口 global memory + workspace tags
- 让 Procedure 成为 AI 管理的一等 workflow profile，并支持自动推断与 thread 级固化

### 输入依赖

- Phase 1
- Phase 3
- `workspace-capability-model.md`

### 主要任务

1. memory records 改为服务端统一存储
2. 引入 workspace tags 检索排序
3. Procedure 服务化与 routing metadata 收口
4. 引入自动 Procedure 推断与 thread 级 pinned procedure
5. 为 Procedure 的 create / update / delete / pin / unpin 增加回调确认链路
6. 前端如需呈现 Procedure，仅提供只读列表 / 内容 / 当前上下文展示

### 测试

- memory 检索排序测试
- workspace 优先级测试
- procedure inference 测试
- procedure pin / unpin 测试
- procedure catalog mutation callback 测试

### 验收

- 当前 workspace 的记忆优先显示
- 其他 workspace 来源记忆可见且带来源标记
- 系统可在合适任务上自动带出当前 procedure
- Procedure 的持久化变更必须先经过回调确认
- 前端不要求手动执行 Procedure；如有 Procedure 视图，仅需展示目录、内容和当前上下文

## Phase 9 Edge Agent transport 收口

### 目标

- 让边缘 Agent 与桌面 Agent 共享同一套 `/agent/ws` transport
- 清理 transport 语义与文档分裂

### 输入依赖

- Phase 2
- `agent-protocol-v1.md`

### 主要任务

1. 统一 Edge Agent 到 `WSS /agent/ws` + `meetyou.agent.v1`
2. 补齐 edge agent 最小运行时与 capability call 基线
3. 更新文档、测试与配置模板

### 当前状态补记

- `F92` 已完成：`agent.hello.ack` 下发的 `heartbeat_interval_seconds` 会立即重排当前 heartbeat loop，而不是等旧间隔耗尽
- `F93` 当前为进行中：仓库已具备 Edge Agent protocol/runtime 测试与最小 `utility.echo` capability 样例，但边缘能力集、样例覆盖面与人工验收口径仍需继续扩展
- transport heartbeat 只负责 agent 在线状态与运行指标协商，不等同于 `Core Heart` 的服务端时间编排

### 测试

- edge agent 运行时测试
- hello / heartbeat / capability call 测试
- 边缘 capability 样例测试

当前推荐验证路径：

1. 最小协议与运行时回归：`.venv\Scripts\python.exe -m unittest tests.test_edge_agent_protocol tests.test_edge_agent_runtime`
2. Gateway 侧注册与调用联调：`.venv\Scripts\python.exe -m unittest tests.test_gateway_agent_api`
3. 人工链路验收：按 `docs/manual-startup-acceptance.md` 的 Edge Agent / F93 验收步骤，手动启动 `python main.py edge-agent` 并检查 `/operator/agents`、`agent.hello.ack` heartbeat 协商与最小 capability 调用

### 验收

- Edge Agent 与 Desktop Agent 使用同一套 transport 与协议主链
- `agent.hello.ack` 的 heartbeat interval 协商可立即作用到当前连接
- 最小边缘 capability 样例与相关稳定性测试可重复通过

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
- Edge Agent -> Core -> `/agent/ws` heartbeat 协商与最小 capability call

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
- 当前 Edge Agent 最小验证已落在主 `tests/`：
  - `.venv\Scripts\python.exe -m unittest tests.test_edge_agent_protocol tests.test_edge_agent_runtime`
  - `.venv\Scripts\python.exe -m unittest tests.test_gateway_agent_api`

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
- 优先只落一个 feature；如果必须跨 feature，必须在变更说明里显式写清原因

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
