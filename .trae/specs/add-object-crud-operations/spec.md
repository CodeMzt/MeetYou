# 统一对象 CRUD 能力层 Spec

## Why
当前助手对任务、定时任务与记忆等核心对象只具备部分高层操作能力，例如任务和定时任务缺少删除，记忆缺少显式详情查看、编辑和删除，导致用户无法像管理真实对象一样完整操作系统状态。  
本次变更聚焦补齐统一对象操作层，为任务、定时任务和记忆提供一致的创建、查看、编辑、删除与状态变更能力，并让这些能力可被助手、安全网关、调试接口与前端统一消费。

## What Changes
- 为任务对象补齐完整 CRUD 能力，支持创建、列表查看、详情查看、编辑、完成、删除与可选恢复
- 为定时任务对象补齐完整 CRUD 能力，支持创建、列表查看、详情查看、编辑、完成、删除，并区分删除、取消、禁用与恢复语义
- 为记忆对象补齐对象化操作能力，支持列表检索、详情查看、编辑、删除、失效与显式忘记
- 建立统一对象操作返回结构，确保助手面对任务、定时任务和记忆时使用一致的对象标识、变更结果和错误语义
- 将对象操作纳入 Authorization Gateway，确保删除、编辑、失效等高风险动作遵循确认流和审计策略
- 为调试接口和前端状态补齐对象操作可见性，支持查看最近对象变更、失败原因与冲突提示
- 增加围绕对象 CRUD、删除恢复、记忆失效、定时任务取消与安全确认的系统级测试
- **BREAKING**：任务与定时任务工具不再仅提供 create / list / update / complete 四类动作，改为完整对象动作集合
- **BREAKING**：记忆不再仅暴露 remember / search 两个高层动作，改为可操作的对象级管理接口

## Impact
- Affected specs: 助手工具能力、任务系统、定时任务系统、记忆系统、授权网关、调试接口、前端对象管理状态、测试体系
- Affected code: `tools/task_manager.py`、`tools/agent_memory.py`、`tools/memory.py`、`tools/memory_layers.py`、`tools/scenario_tools.py`、`core/tools_manager.py`、`core/tool_runtime/authorization.py`、`core/brain.py`、`gateway/api.py`、`gateway/models.py`、`meetyou-ui/src/`、`tests/`

## ADDED Requirements
### Requirement: 任务对象完整操作
系统 SHALL 为普通任务提供完整对象级操作，至少包含创建、列表查看、详情查看、编辑、完成、删除与必要的恢复能力。

#### Scenario: 删除某个任务
- **WHEN** 用户要求删除某个已存在任务
- **THEN** 助手 SHALL 能按任务 ID 或稳定匹配结果定位目标任务并执行删除
- **AND** SHALL 返回被删除任务的关键信息、删除结果与后续可恢复提示（如适用）

### Requirement: 定时任务对象完整操作
系统 SHALL 为定时任务提供完整对象级操作，至少包含创建、列表查看、详情查看、编辑、完成、删除、取消或禁用等能力。

#### Scenario: 删除某个提醒
- **WHEN** 用户要求删除某个已存在的定时任务或提醒
- **THEN** 助手 SHALL 能按对象标识或稳定匹配结果删除目标定时任务
- **AND** SHALL 区分永久删除、取消执行和仅禁用的语义结果

### Requirement: 记忆对象完整操作
系统 SHALL 为记忆提供对象级管理能力，至少包含检索列表、查看详情、编辑、删除、失效和显式忘记。

#### Scenario: 删除某条错误记忆
- **WHEN** 用户要求删除一条指定记忆
- **THEN** 助手 SHALL 能定位目标记忆并执行删除或失效
- **AND** SHALL 返回记忆标识、变更结果以及对后续检索行为的影响

### Requirement: 统一对象操作返回结构
系统 SHALL 为任务、定时任务和记忆的对象操作提供统一的返回结构，至少包含对象类型、对象 ID、动作、状态、是否需要确认、冲突信息和人类可读摘要。

#### Scenario: 编辑对象成功
- **WHEN** 助手成功编辑任一受支持对象
- **THEN** 返回结果 SHALL 使用统一字段表达修改前后状态或等效变更摘要
- **AND** SHALL 允许调试接口和前端稳定消费

### Requirement: 高风险对象操作确认流
系统 SHALL 将删除、失效、批量修改和批量删除等高风险对象操作纳入统一确认流与审计。

#### Scenario: 删除多条记忆
- **WHEN** 助手尝试一次删除多条记忆
- **THEN** 系统 SHALL 触发确认流或等效安全策略
- **AND** SHALL 记录授权决策与操作审计信息

### Requirement: 对象详情与匹配歧义处理
系统 SHALL 在对象操作前提供稳定的对象定位与歧义处理机制，避免错误修改相似名称的任务、提醒或记忆。

#### Scenario: 用户说“删掉明天那个提醒”
- **WHEN** 系统发现存在多个可能匹配的提醒
- **THEN** 系统 SHALL 返回候选对象列表或稳定匹配结果
- **AND** SHALL 不在目标不明确时直接删除错误对象

### Requirement: 调试与前端对象状态可见性
系统 SHALL 向调试接口或前端暴露最近对象操作、失败原因、确认状态与冲突信息。

#### Scenario: 对象删除失败
- **WHEN** 某个任务、定时任务或记忆删除失败
- **THEN** 调试接口或前端 SHALL 能看到失败分类、目标对象信息与可恢复动作建议

## MODIFIED Requirements
### Requirement: 任务管理工具
任务管理工具不再只支持 create、list、update 与 complete。  
系统 SHALL 将普通任务升级为对象级管理接口，支持 CRUD、详情读取与更稳定的对象定位语义。

### Requirement: 定时任务管理工具
定时任务管理工具不再只支持 create、list、update 与 complete。  
系统 SHALL 提供完整对象操作能力，并区分 schedule、execution、delivery 与删除/取消/禁用后的状态变化。

### Requirement: 记忆工具
记忆工具不再只支持 remember 与 search 两类高层动作。  
系统 SHALL 为记忆提供对象级管理接口，使助手能够查看、编辑、删除、失效和忘记特定记忆。

### Requirement: 授权网关
授权网关不再只覆盖命令执行、文档写入等副作用工具。  
系统 SHALL 将对象删除、对象失效、批量修改与批量删除纳入统一风险判断、确认流与审计。

## REMOVED Requirements
### Requirement: 部分对象只支持追加式管理
**Reason**: 仅允许创建、搜索或完成而不支持删除、编辑和详情查看，会让助手难以成为可操作的对象管理器。  
**Migration**: 将任务、定时任务和记忆升级为对象级操作接口，并用统一返回结构承载结果。

### Requirement: 记忆仅可追加不可显式撤销
**Reason**: 记忆若只能新增和检索，用户无法纠错、撤销错误记忆或删除敏感内容。  
**Migration**: 引入记忆对象标识、详情读取、编辑、删除与失效语义，并更新主助手工具暴露策略。
