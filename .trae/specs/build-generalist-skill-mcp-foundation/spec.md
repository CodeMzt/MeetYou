# 助手多面手 SKILL / MCP 能力底座 Spec

## Why
当前项目已经具备 mode、skill、tool、MCP 的中层编排骨架，但项目内的 SKILL 自动激活范围仍偏窄、MCP 能力仍偏“能接入但不善用”、大量学习/办公/科研/信息获取场景缺少成体系的能力包与路由策略。  
本次变更基于现有项目架构，为项目自身建立“会发现、会选择、会组合、会降级”的多面手能力底座，让助手能更稳定地利用 SKILL、MCP 与项目内置 TOOLS 提升学习、工作、生活、科研与信息获取效率。

## What Changes
- 为项目增加“SKILL 可用性感知”能力，让助手在规划阶段主动考虑是否应加载、组合或创建 skill，而不是仅依赖少量硬编码自动激活
- 建立项目侧 MCP 能力引入层，为学习办公辅助、科研检索、信息获取、时政热点追踪等场景配置可治理的 MCP server 分层与启用策略
- 为不值得单独引入 MCP 的轻量场景补充项目内置 TOOLS，并纳入统一 capability registry、授权与路由体系
- 建立覆盖学习、办公、科研、信息获取、热点跟踪、知识整理、内容总结、计划执行等方向的 SKILL 能力包与路由规则
- 扩展 capability registry、semantic router、prompt assembler 与 tool runtime，使其支持按场景、目标、风险和资源可用性选择 skill / MCP / tool
- 引入 MCP 可用性模型，区分已配置、需 API、未启用、不可用、可降级等状态，并让助手在运行时做优先级选择与回退
- 增加项目级一致性校验，验证 skill 声明、MCP 绑定、工具依赖、路由规则、只读边界与降级链路是否完整
- 增加多场景验证，覆盖学习辅导、办公整理、科研研究、网页信息获取、热点追踪与无 API 回退
- **BREAKING**：移除“新增 skill 但默认不会进入通用激活/路由体系”的隐式假设，改为声明式注册与可治理激活
- **BREAKING**：移除“仅按 mode 静态附着 MCP server”的弱绑定方式，改为 skill / scene / policy 联合驱动的能力选择

## Impact
- Affected specs: SKILL 系统、Capability Registry、语义路由、Prompt 装配、MCP 管理、工具注册、授权策略、学习/办公/研究模式、信息源策略、测试体系
- Affected code: `core/assistant_modes.py`、`core/semantic_router.py`、`core/capability_registry.py`、`core/prompt_assembler.py`、`core/tools_manager.py`、`core/tool_runtime/`、`core/config.py`、`core/protocol_schema.py`、`tools/mcp.py`、`tools/scenario_tools.py`、`tools/`、`prompt/SKILL/`、`user/`、`tests/`

## ADDED Requirements
### Requirement: SKILL 可用性感知与优先使用
系统 SHALL 在任务规划与路由阶段显式感知“有哪些 skill 可用、何时应该加载 skill、何时应该优先使用 skill 组合”，并将 skill 作为项目内的一等能力对象参与决策。

#### Scenario: 用户提出复合型学习研究任务
- **WHEN** 用户提出需要分解步骤、检索信息、整理结果与输出结构化结论的复合型任务
- **THEN** 系统 SHALL 优先评估是否存在匹配的 study / research / synthesis skill
- **AND** SHALL 在最终 route 中显式记录已激活 skill 与激活原因

### Requirement: 声明式 MCP 能力目录
系统 SHALL 提供项目侧声明式 MCP 能力目录，描述每个 MCP server 的用途、适用场景、启用条件、风险级别、认证需求、降级策略与可挂接 skill。

#### Scenario: 某个 MCP 需要外部 API
- **WHEN** 某个场景命中了需要 API Key 的 MCP server
- **THEN** 系统 SHALL 识别该 server 为“需配置认证”状态
- **AND** SHALL 在未配置时自动选择降级路径，而不是让主流程失效
- **AND** SHALL 能在结果中说明若要启用完整能力需要补充哪些配置

### Requirement: 多面手 SKILL 能力包
系统 SHALL 提供覆盖学习、生活、工作、办公、科研、信息获取与热点追踪等方向的项目内 skill 能力包，每个 skill 均声明目标、适用触发条件、依赖工具、依赖 MCP、输出形态与回退路径。

#### Scenario: 用户请求追踪时政热点并形成摘要
- **WHEN** 用户请求获取热点事件、交叉来源信息并生成结构化摘要
- **THEN** 系统 SHALL 激活与信息获取和热点跟踪相关的 skill
- **AND** SHALL 优先选择可用的网页 / 检索 MCP
- **AND** SHALL 在 MCP 不可用时退回到项目内置 web/tool 能力完成基础版本

### Requirement: 轻量原生 TOOLS 补位
系统 SHALL 为简单、通用、无需额外外部集成的场景提供项目内置 TOOLS，并将这些工具纳入统一注册、授权和路由，不以 MCP 替代所有能力。

#### Scenario: 简单文本整理任务
- **WHEN** 用户只需要轻量级的文本提炼、结构化整理、学习笔记重排或待办拆分
- **THEN** 系统 SHALL 优先选择项目内置 TOOLS 或已有基础工具
- **AND** SHALL 避免为了低复杂度任务引入不必要的 MCP 依赖

### Requirement: 场景化能力选择与回退
系统 SHALL 根据用户目标、任务类型、上下文、风险边界与资源可用性，在 SKILL、MCP 和项目内置 TOOLS 之间进行场景化选择，并保持稳定回退链路。

#### Scenario: 首选 MCP 不可用
- **WHEN** 某个首选 MCP server 不可用、未启用或初始化失败
- **THEN** 系统 SHALL 自动切换到同类备选 MCP 或项目内置 TOOLS
- **AND** SHALL 不中断主任务
- **AND** SHALL 保留“当前能力已降级”的结构化说明供上层使用

### Requirement: 项目侧学习办公科研能力分层
系统 SHALL 将学习办公辅助、科研研究、信息获取、热点跟踪等能力组织为可治理的场景层，支持 mode、skill、tool、MCP 的组合复用，而不是为每个任务单独硬编码路径。

#### Scenario: 同一任务跨场景复用能力
- **WHEN** 用户请求“查资料 + 提炼学习笔记 + 生成办公汇报提纲”
- **THEN** 系统 SHALL 允许 research、study、office 等能力层协同装配
- **AND** SHALL 保持统一的只读/写入边界和工具可见性

### Requirement: MCP 可用性与配置诊断
系统 SHALL 维护项目内 MCP 的可用性状态，并为每个 server 提供已启用、未启用、需认证、缺依赖、不可用、已降级等诊断结果。

#### Scenario: 启动期检查 MCP 配置
- **WHEN** 系统启动或刷新能力注册时检查 MCP 配置
- **THEN** 系统 SHALL 输出结构化诊断结果
- **AND** SHALL 标记哪些能力可立即使用，哪些能力仍需用户补充 API 或本地依赖

### Requirement: 一致性校验与回归验证
系统 SHALL 在启动期和测试期校验 skill、MCP、tool、prompt、路由规则与降级链路的一致性，防止出现“声明存在但运行不可达”的伪能力。

#### Scenario: skill 引用了不存在的 MCP
- **WHEN** 某个 skill 声明了未注册、未配置或未授权的 MCP server
- **THEN** 系统 SHALL 在校验阶段报告可定位错误
- **AND** SHALL 阻止该 skill 以完整可用状态进入运行时

## MODIFIED Requirements
### Requirement: Capability Registry
Capability Registry 不再只负责 mode、tool bundle、prompt bundle 与静态 skill 组合。  
系统 SHALL 将 skill 激活策略、MCP 能力目录、场景层能力分组、轻量原生工具与降级策略统一纳入声明式 capability 模型。

### Requirement: Semantic Router
语义路由不再只依据 mode 和少量硬编码 skill 关键字决定能力面。  
系统 SHALL 基于任务目标、场景标签、skill 触发规则、MCP 可用性和授权边界生成可解释的 route 决策。

### Requirement: Prompt / SKILL 装配
Prompt / SKILL 装配不再仅把 skill 视为附加文本片段。  
系统 SHALL 在 prompt、工具面、MCP 绑定、输出要求与降级提示之间保持一致装配。

### Requirement: MCP 集成
MCP 集成不再只提供“server 已接入即可暴露工具”的弱治理模型。  
系统 SHALL 以项目侧能力目录控制 MCP 的可见性、场景适配、认证状态、回退策略与风险边界。

### Requirement: 项目工具体系
项目工具体系不再默认“能用 MCP 就不新增原生工具”。  
系统 SHALL 按复杂度与收益决定是引入 MCP 还是补充项目内置 TOOLS，并保证两类能力遵守同一套注册与授权规则。

## REMOVED Requirements
### Requirement: 硬编码自动激活技能名单
**Reason**: 仅依赖少量硬编码 skill 名单会导致新增 skill 无法稳定进入主流程，能力扩展成本高且与“多面手”目标冲突。  
**Migration**: 改为声明式 skill 激活规则，支持按场景、关键词、任务标签、模式偏好与可用资源进行注册和决策。

### Requirement: Mode 静态绑定 MCP
**Reason**: 仅按 mode 静态挂接 MCP server 无法表达“同一 mode 下按任务目标选不同外部能力”的需求，也不利于细粒度降级。  
**Migration**: 改为由 capability registry 统一声明 skill / scene / tool / MCP 的关系，再由路由运行时选择具体可用能力。
