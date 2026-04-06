# 服务优先运行时重构 Spec

## Why
当前项目已经具备完整产品骨架，但核心运行时仍以单进程超级编排器、共享可变状态、字符串化错误和本地开发态部署为主，难以支撑高稳定性、高鲁棒性、强可观测性和长期服务化演进。  
本次变更采用服务优先、允许彻底重做的策略，对运行时内核、协议、配置、安全、调度、工具执行和前端接入进行系统重构。

## What Changes
- 重建服务优先运行时内核，拆分会话执行、后台作业、工具执行、投递和遥测边界
- 引入结构化 command / event / error / health 协议，替代字符串化错误与隐式运行时约定
- 将统一入口从单一全局队列升级为按 session / job 分片的 actor 式执行模型
- 为配置、记忆、任务与后台状态建立正式 repository 层与事务化写入机制
- 重做 Gateway 安全模型，加入鉴权、收紧 CORS，并升级 HTTP / WebSocket 协议
- 重做工具执行链路，统一权限、风险、结果、超时和重试语义
- 重建可观测性体系，补齐结构化日志、健康检查、遥测事件和系统退化状态
- 重构前端接入层，使其适配新协议、新错误模型和长会话性能要求
- 清理旧兼容层、失效配置和遗留流程
- **BREAKING**：移除旧的宽松配置写入与无鉴权网关访问方式
- **BREAKING**：移除旧的字符串化工具错误契约，改为结构化结果
- **BREAKING**：移除旧的 gateway-only 运行时假设与失效配置项
- **BREAKING**：移除旧的兼容保留项与 legacy 迁移代码，只保留本次重构定义的新运行时主路径

## Impact
- Affected specs: 运行时内核、Gateway 协议、WebSocket 协议、配置治理、工具执行、后台调度、任务系统、记忆持久化、前端接入、安全模型、可观测性、部署方式
- Affected code: `core/app.py`、`core/brain.py`、`core/event_bus.py`、`core/status.py`、`core/tools_manager.py`、`core/config.py`、`core/heart.py`、`core/session_manager.py`、`gateway/`、`tools/`、`sensors/`、`adapters/`、`meetyou-ui/src/`、`main.py`、`launcher.py`、`tests/`

## ADDED Requirements
### Requirement: 服务优先运行时内核
系统 SHALL 提供独立的服务优先运行时内核，并将会话执行、后台作业、工具执行、消息投递与遥测收敛到明确的运行时边界中。

#### Scenario: 启动运行时服务
- **WHEN** 系统启动核心运行时
- **THEN** 运行时 SHALL 初始化会话执行器、后台作业执行器、工具执行器、投递层和遥测层
- **AND** 各层之间 SHALL 通过显式协议交互而不是直接共享内部可变状态

### Requirement: 会话 Actor 执行模型
系统 SHALL 以 session 为单位提供独立执行队列，保证单会话内顺序一致、跨会话间可并行执行。

#### Scenario: 多会话同时请求
- **WHEN** 两个不同 session 同时收到输入
- **THEN** 系统 SHALL 将它们路由到不同的会话执行器
- **AND** 一个会话阻塞时 SHALL 不影响另一个会话继续处理

### Requirement: 后台作业统一模型
系统 SHALL 将定时任务、heartbeat、housekeeping 和后台 agent 统一建模为 job，并提供统一生命周期、错误语义和投递语义。

#### Scenario: 后台任务执行失败
- **WHEN** 某个后台 job 执行失败
- **THEN** 系统 SHALL 记录结构化失败结果
- **AND** SHALL 明确区分可重试失败、不可重试失败和需要人工干预的失败

### Requirement: 结构化错误协议
系统 SHALL 为运行时、工具、网关、后台任务和外部依赖统一使用结构化错误协议。

#### Scenario: 工具调用失败
- **WHEN** 工具因超时、参数错误或外部依赖异常而失败
- **THEN** 返回值 SHALL 包含稳定的错误代码、错误分类、是否可重试、对用户安全的消息和运维诊断信息
- **AND** SHALL 不再以普通字符串 `"Error: ..."` 作为主错误契约

### Requirement: 事务化配置治理
系统 SHALL 以事务方式处理配置更新，并在持久化前完成类型校验、语义校验和风险校验。

#### Scenario: 提交非法配置
- **WHEN** 用户提交非法配置或导致运行时刷新失败的配置
- **THEN** 系统 SHALL 拒绝该变更
- **AND** SHALL 保证持久化配置、环境密钥和运行时状态保持一致

### Requirement: 安全网关
系统 SHALL 为所有敏感 API 与 WebSocket 入口提供鉴权与最小权限访问控制。

#### Scenario: 未授权访问配置接口
- **WHEN** 未授权客户端请求配置、记忆或运行态接口
- **THEN** 系统 SHALL 拒绝请求
- **AND** SHALL 记录安全相关遥测事件

### Requirement: 协议单源化
系统 SHALL 维护 HTTP、WebSocket、运行态状态与配置 schema 的单一事实来源，并为前端生成一致类型。

#### Scenario: 新增运行态字段
- **WHEN** 后端新增字段或事件类型
- **THEN** 前端消费类型与文档 SHALL 由统一 schema 同步更新
- **AND** SHALL 避免前后端手工重复定义

### Requirement: 正式持久化仓储层
系统 SHALL 为配置、记忆、任务与运行态快照提供正式仓储层，支持原子写入、版本化迁移和一致性约束。

#### Scenario: 进程在写入过程中异常退出
- **WHEN** 系统在持久化过程中中断
- **THEN** 仓储层 SHALL 保证数据文件或数据库处于可恢复且一致的状态

### Requirement: 可观测性与健康度
系统 SHALL 区分用户可见状态与运维可见遥测，并提供结构化日志、健康检查、退化状态与关键指标。

#### Scenario: 后台调度停滞
- **WHEN** scheduler 或 housekeeping 长时间未推进
- **THEN** 健康检查 SHALL 报告 degraded 状态
- **AND** 遥测 SHALL 包含定位该问题所需的上下文标识

### Requirement: 前端协议适配与长会话性能
系统 SHALL 使前端完整消费新协议中的确认、错误、状态与遥测事件，并控制长会话 UI 的渲染成本。

#### Scenario: 长会话持续流式输出
- **WHEN** 会话持续接收消息、状态和活动事件
- **THEN** 前端 SHALL 保持可响应
- **AND** SHALL 支持消息裁剪、增量更新或等效性能策略

## MODIFIED Requirements
### Requirement: Gateway 接入
Gateway 不再只是本地开发态入口，而是服务优先运行时的正式接入层。  
它 SHALL 提供经过鉴权的 HTTP 和 WebSocket 接口，并返回结构化成功、失败、确认与健康结果。  
旧的无鉴权、宽松 CORS、弱校验写入方式不再属于合规实现。

### Requirement: 工具执行
工具执行不再通过混合型管理器直接返回自由文本结果。  
系统 SHALL 通过统一执行器完成权限判断、风险评估、超时控制、结果封装和错误分级，并为会话与后台作业提供一致的执行语义。

### Requirement: 配置管理
配置管理不再允许先落盘后刷新。  
系统 SHALL 先完成校验与预演，再原子提交，并明确返回已应用项、未应用项、失败原因和后续动作要求。

### Requirement: 后台调度
后台调度不再依赖隐式共享状态和散落的运行循环约定。  
系统 SHALL 使用统一 job 模型管理调度、执行、失败恢复、补发和运行诊断。

## REMOVED Requirements
### Requirement: 旧的 gateway-only 运行时假设
**Reason**: 旧模型将网关、运行时和产品形态绑死，无法支撑服务优先与多部署目标。  
**Migration**: 以新运行时服务为中心，桌面端、CLI 与第三方接入全部改为外层客户端或适配器。

### Requirement: 旧的字符串化错误契约
**Reason**: `"Error: ..."` 无法提供稳定错误语义、恢复策略与监控能力。  
**Migration**: 所有调用方改为消费结构化错误对象，并基于错误代码与分类处理。

### Requirement: 旧的失效配置与兼容保留项
**Reason**: 失效配置和 legacy 迁移代码会放大维护成本并降低系统可理解性。  
**Migration**: 删除失效配置项与兼容分支，仅保留本次重构后的正式配置与迁移脚本。
