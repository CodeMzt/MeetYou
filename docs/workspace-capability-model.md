# MeetYou Workspace And Capability Model V2

## 1. 文档目的

本文档定义 MeetYou V2 的核心领域模型，回答以下问题：

- Core、Client、客户端内本地后端、边缘节点、Workspace、Thread、Session、Operation 各自是什么。
- Mode、Procedure、Skill、Tool、MCP 的职责边界如何划分。
- 记忆如何组织，尤其是 workspace memory 与 global memory 的关系。
- 多工作空间 Agent、跨会话协作、自动 Procedure 推断与治理如何建模。

## 2. 领域对象

### 2.1 Principal

Principal 表示用户本人。

当前系统默认单用户，但 Principal 仍需显式存在，因为：

- 会话和审批必须绑定到真实主体
- 记忆和任务不能再依赖 `source_id` 伪装身份
- Client 与 Agent 的权限都要最终归属于 Principal

### 2.2 Client

Client 表示交互入口。

示例：

- PC 客户端
- 飞书 Bot
- 未来手机 App

Client 负责交互，不是权威状态源。

补充：

- PC 客户端和未来手机客户端都可以在客户端内部包含“前端 + 本地后端”。
- 飞书通常是轻客户端，不自带完整本地后端。

### 2.3 Client Local Backend

Client Local Backend 表示某个客户端内部的本地执行 / 桥接后端。

示例：

- `desktop-main-agent`
- 未来手机端本地运行时

它属于客户端内部，而不是与 Client 并列的顶层产品角色。

### 2.4 Edge / Bridge Node

Edge / Bridge Node 表示按 workspace 接入的执行节点。

示例：

- `raspi-home-lab-agent`
- `bridge-lan-agent`

客户端内本地后端和边缘节点的关键属性：

- `agent_id`
- `agent_type`
- `workspace_ids[]`
- `capability_ids[]`
- `online_status`
- `host_info`
- `transport_profile`

### 2.5 Workspace

Workspace 表示情景、设备组和能力策略的作用域。

Workspace 适合承载：

- situational prompt overlay
- 可用 capability overlay
- source profile 偏好
- 自动化与定时任务默认执行目标
- 客户端内本地后端 / 节点归属关系

当前已落地的第一批治理字段：

- `base_mode`
- `prompt_overlay`
- `default_execution_target`

当前已生效的第一批治理行为：

- 消息入口缺省 mode 继承 `base_mode`
- operation 入口缺省执行目标继承 `default_execution_target`
- prompt 组装链路会附带 `prompt_overlay`

当前已落地的第二批治理字段：

- `capability_policy`
- `allowed_capability_ids`
- `preferred_agent_ids`

当前已落地的第三批治理字段：

- `preferred_agent_types`
- `agent_routing_policy`

当前已生效的第二批治理行为：

- 显式 capability operation 会校验 workspace allowlist
- 当 `capability_policy=allowlist` 时，缺少 `capability_id` 的 `capability_call` 不再允许进入主链
- `workspace_any_agent` 会按 workspace 首选 agent 列表和 owner-client affinity 进行自动选路
- workspace 默认 `specific_agent` 在客户端未显式给出 target 时也可以自动补出目标 agent

当前已生效的第三批治理行为：

- `agent_routing_policy=balanced` 时，优先看 `preferred_agent_ids`，再看 `preferred_agent_types`，最后看 owner affinity
- `agent_routing_policy=prefer_owner_client` 时，owner affinity 会先于 workspace 首选 agent 列表生效
- `agent_routing_policy=strict_preferred` 时，若配置了 `preferred_agent_ids`，系统不会退回非首选 agent

当前已落地的第四批能力收口：

- agent capability 可声明 `abstract_capability_key`
- operation 可用抽象 capability key 而不是 agent-specific capability id

当前已落地的第五批治理字段：

- `capability_routing_overrides`

当前已生效的第四批能力行为：

- workspace 自动选路会先用抽象 capability key 找到候选 agent，再映射到目标 agent 的具体 capability
- allowlist 既可以存具体 capability id，也可以存抽象 capability key

当前已生效的第五批治理行为：

- capability 级 routing override 可以覆写 workspace 全局 `preferred_agent_ids`
- capability 级 routing override 可以覆写 workspace 全局 `preferred_agent_types`
- capability 级 routing override 可以覆写 workspace 全局 `agent_routing_policy`

当前已落地的第六批衔接：

- Procedure 已公开 capability / routing 偏好字段
- `procedure_call` 已可继承 procedure 的 capability / routing 偏好

当前已生效的第六批行为：

- procedure 的 preferred capability ref 可以直接进入 capability routing 主链
- procedure 的 agent 偏好与 routing policy 会叠加到 workspace 自动选路之上

当前已落地的第七批衔接：

- scheduled task 已支持 capability / routing 偏好字段

当前已生效的第七批行为：

- task 调度输出会显式带上 preferred capability ref 与 routing preference
- scheduled task 的 route context 已能读取这些偏好，供后台执行路径消费

当前已落地的第八批治理字段：

- `preferred_source_profiles`
- `memory_ranking_policy`

当前已生效的第八批行为：

- workspace 可公开声明来源偏好，并进入统一 workspace governance surface
- message 路由会把 workspace 的来源偏好注入 route context；procedure 推荐来源仍高于 workspace 偏好
- workspace 记忆排序策略已公开为治理字段；当前实现固定为 `workspace_first`

Workspace 不是：

- 多租户组织
- 单纯聊天标签页
- 单个终端实例

### 2.6 Thread

Thread 表示逻辑上的连续对话主题，可跨多个 session。

用途：

- 飞书发起请求
- 桌面端继续查看进度
- 手机稍后补充信息

这些 session 可以属于同一个 thread。

### 2.7 Session

Session 表示某个 Client 上的一次实际交互会话。

Session 绑定：

- `principal_id`
- `thread_id`
- `workspace_id`
- `client_id`

Session 是运行态交互容器，不是长期协作主键。

### 2.8 Operation

Operation 表示一次独立执行请求或跨端动作。

示例：

- 让桌面修改某个文件
- 请求桌面截图并回传
- 调用树莓派采集传感器数据

Operation 绑定：

- `operation_id`
- `thread_id`
- `workspace_id`
- `target_agent_id` 或 `execution_target`
- `requested_by_client_id`
- `attachments[]`

Operation 是跨 session 联动的核心对象。

### 2.9 Capability

Capability 是统一的能力对象。

它不直接等于某个 Python 函数，而是治理层的稳定能力声明。

Capability 可来自：

- Core 内建能力
- 客户端内本地后端或边缘节点上报能力
- MCP 映射能力
- Procedure
- Skill

## 3. Workspace 与客户端本地后端 / 节点的关系

V2 明确采用多对多关系。

- 一个 workspace 可包含多个客户端内本地后端或边缘节点
- 一个客户端内本地后端或边缘节点可加入多个 workspace

例如：

- `desktop-main-agent` 作为 PC 客户端内本地后端，同时加入 `personal`、`desktop-main`、`study`
- `raspi-home-lab-agent` 同时加入 `personal`、`home-lab`

原因：

- 同一设备可能既服务于日常使用，也服务于特定场景
- 不应为了切换 workspace 而人为复制设备节点

## 4. 作用域模型

V2 采用三层作用域：

- `global`
- `workspace`
- `session`

### 4.1 Global Scope

适合：

- 长期个人记忆
- 全局偏好
- 全局 Procedure / Skill
- 全局任务

### 4.2 Workspace Scope

适合：

- prompt overlay
- capability overlay
- source profile 偏好
- 自动化与执行目标策略
- workspace 关联的任务和设备编组

### 4.3 Session Scope

适合：

- 当前轮上下文
- 回复控制状态
- 临时检查点
- 当前会话的交互附件引用

## 5. 记忆模型

### 5.1 总体原则

V2 不再把 global memory 与 workspace memory 设计成两套彼此隔离的数据库，而是采用：

- 一个统一的全局记忆库
- 每条记忆带来源标签和作用域标签

也就是说：

- `global memory` 是统一全集
- `workspace memory` 是其中带有 `origin_workspace_id`、`workspace_tags` 等标签的子集

### 5.2 Memory 记录建议字段

```json
{
  "memory_id": "mem_123",
  "principal_id": "self",
  "content": "桌面主机代码仓库位于 D:/Projects",
  "scope": "global",
  "origin_workspace_id": "desktop-main",
  "workspace_tags": ["desktop-main"],
  "memory_type": "project_state",
  "visibility": "shared_with_all_workspaces"
}
```

### 5.3 检索原则

所有 workspace 都可以查询全局记忆全集，但 Core 需要按优先级排序：

1. 当前用户消息
2. 当前 session working context
3. 当前 workspace tag 命中的记忆
4. 未标记 workspace 的全局记忆
5. 其他 workspace 来源的全局记忆

这样既满足“global 包含 workspace”，又保留当前 workspace 相关记忆的优先性。

### 5.4 冲突处理

若多条记忆冲突：

- 当前用户消息优先
- 当前 workspace 来源记忆优先于其他 workspace 来源记忆
- 其他 workspace 来源记忆仍可见，但需带来源标记

结论：不是强硬覆盖，而是“统一全集 + 检索排序 + 来源可见”。

## 6. Mode / Procedure / Skill / Tool / MCP

### 6.1 Mode

Mode 是用户可见的工作风格。

Mode 负责：

- 默认行为风格
- 默认 source profile 偏好
- 默认 capability 偏好
- 默认 UI affordance

Mode 不负责：

- 最终授权
- 最终审批
- 低层执行细节

建议长期保留有限集合：

- `general`
- `research`
- `documents`
- `study`
- `automation`

兼容说明：

- `normal`、`auto`、`office` 视为 legacy mode 名称，不再作为公开产品枚举继续扩散
- 当前代码在迁移期允许把公开 mode 映射到 legacy 内核，但对外只返回上述 5 个 mode

### 6.2 Procedure

Procedure 是高层 workflow profile，是 V2 的一等公民，用来承接原来 rich workflow skill 的那部分职责。

Procedure 比 Skill 更强，原因在于它不是一段临时 prompt 提示，而是会进入正式资源主链的工作流画像：

- 有稳定 `procedure_id` 与数据库资源模型
- 可直接影响 `execution_target`、capability ref 与 agent routing
- 可被 thread、task、scheduler 长期继承
- 可进入审计、回放与调试链路

设计定位上，Procedure 默认由 AI / Core 根据当前 thread、workspace、task、历史 route context 自动推断；它不是要求用户每轮手动挑选的前端菜单。

示例：

- `daily_research_digest`
- `code_review`
- `desktop_fix_loop`
- `study_note_synthesis`

Procedure 应声明：

- `procedure_id`
- `prompt_overlay`
- `applicable_modes`
- `recommended_capabilities`
- `recommended_source_profiles`
- `default_execution_target`
- `risk_profile`
- `preferred_capability_ref`
- `preferred_agent_ids`
- `preferred_agent_types`
- `agent_routing_policy`

### 6.3 Procedure 推断与生命周期

V2 默认不要求用户显式选择 Procedure。

默认链路应为：

- AI / Core 自动推断当前消息、任务或线程更适合挂哪个 Procedure
- 当某个 Procedure 需要跨多轮稳定生效时，可把当前推断固化为 thread 级 pinned procedure
- 前端不需要把 Procedure 做成主路径执行器；最多提供当前 Procedure、可用 Procedure 列表与内容的只读展示

持久化变更治理应为：

- 新建 Procedure
- 更新 Procedure
- 删除 Procedure
- 将自动推断结果固化为 thread 级 pin
- 取消 thread 级 pin

以上会改变持久化 catalog 或 thread 上下文绑定，因此都需要先通过回调 / 审批向用户询问，再执行变更。

结论：用户通过确认或拒绝参与 Procedure 治理，而不是自己承担 Procedure 的主动编辑工作。

### 6.4 Skill

Skill 是可复用的知识/策略片段。

Skill 更轻量，适合：

- 特定回答风格
- 特定注意事项
- 某类输入的处理策略

Skill 不再承担复杂工作流职责，也不再作为用户面 workflow identity。

复杂、可复用、需要长期审计和路由控制的 workflow，应逐步从 Skill 上移到 Procedure；Skill 保留为运行时 prompt / tool 策略装配材料。

### 6.5 Tool

Tool 是最小执行单元，必须声明：

- `tool_name`
- `execution_location`
- `risk_level`
- `input_schema`
- `output_schema`
- `requires_confirmation`
- `audit_required`

### 6.6 MCP

MCP 是 Tool Provider，不是业务层独立能力模型。

Core 或 Agent 可以挂载 MCP，但在 Capability 层只体现为能力来源。

## 7. Capability 命名

V2 采用清晰的能力命名约定：

### 7.1 Core 能力

- `core.memory.search`
- `core.research.topic`
- `core.tasks.manage`

### 7.2 Agent 直接能力

- `agent.desktop-main.file.read`
- `agent.desktop-main.file.write`
- `agent.desktop-main.shell.exec`

### 7.3 Bridge 子设备能力

此前提过的“agent 二级 capability namespace”，这里改成更直白的说法：

- `bridge 子设备能力命名`

含义是：某个 bridge agent 下面可能还代管多个子设备或模块，需要在 capability ID 上体现出来。

示例：

- `agent.bridge-home.camera-01.capture`
- `agent.bridge-home.sensor-02.read`
- `agent.bridge-home.tv-01.power.toggle`

这不是第二套协议，只是能力命名更细，便于 Core 区分“一个 agent 下的多个被代理设备”。

## 8. Capability 结构建议

```json
{
  "capability_id": "agent.desktop-main.file.write",
  "kind": "tool",
  "provider_type": "agent",
  "provider_id": "desktop-main-agent",
  "title": "Write Local File",
  "tags": ["documents", "write", "desktop"],
  "risk_level": "write",
  "requires_confirmation": true,
  "workspace_ids": ["desktop-main", "study"],
  "availability": "online"
}
```

## 9. Task 与 Automation

任务模型需要显式声明执行目标。

### 9.1 Task 字段建议

```json
{
  "task_id": "task_123",
  "task_type": "automation",
  "workspace_id": "home-lab",
  "execution_target": "workspace_any_agent",
  "preferred_agent_id": "raspi-home-lab-agent",
  "procedure_id": "daily_research_digest",
  "status": "active"
}
```

### 9.2 Execution Target

- `core_only`
- `specific_agent`
- `workspace_any_agent`
- `prefer_agent_fallback_core`

兼容说明：

- `assistant`、`core` 统一映射到 `core_only`
- `desktop` 统一映射到 `specific_agent`
- 这些旧值只允许在兼容层短暂存在，不再作为正式存储和正式接口返回值

### 9.3 Workspace Any Agent 选路原则

当 `execution_target=workspace_any_agent` 时，Core 的默认选路策略为：

1. 先按 capability 是否满足、workspace binding 是否启用、当前在线状态进行筛选
2. 在候选集内优先 capability 匹配质量和绑定优先级
3. 若仍有多个候选，再以 owner-client affinity 作为次级排序因素

结论：默认是“能力优先，owner-client 亲和性次之”，而不是默认偏向当前桌面端。

## 10. 降级与离线

### 10.1 Desktop Agent 离线缓存

Desktop Agent 支持局部离线任务缓存，但仅限允许离线执行的能力。

本地缓存对象包括：

- 待执行离线 operation
- 本地执行结果收据
- 待上传附件
- 待回放到 Core 的事件摘要

### 10.2 回连后补同步

一旦 Desktop Agent 回连 Core：

- 上传待同步结果
- 上传待同步附件
- 让 Core 补落审计和操作状态

Core 仍然是最终真相源。

## 11. 对当前代码的收敛建议

### 11.1 保留

- 高层 chain tool 思路
- source catalog
- mode 概念本身
- 任务与定时任务

### 11.2 收敛

- `scene` 降级为内部 route label
- Procedure 升级为 AI 管理的一等 workflow profile
- Skill 从 prompt 文件型存储迁出
- rich workflow skill 逐步迁入 Procedure
- Capability 统一注册与治理

### 11.3 禁止继续放大耦合

- 不再让 `source_id` 承担身份语义
- 不再让真正授权写在 mode/skill/scenes 上
- 不再让前端默认依赖 developer debug 数据面

## 12. 待决问题

- 某些 workspace 是否允许完全隐藏其他 workspace 来源记忆；默认建议不隐藏，只降权排序。
- Bridge agent 下的子设备是否需要独立健康状态资源；默认建议需要。
