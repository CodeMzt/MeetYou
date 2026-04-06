# Tasks
- [x] Task 1: 建立统一 Capability Registry：收敛 mode、skill、tool、prompt、MCP server、风险与副作用策略的单一事实来源。
  - [x] SubTask 1.1: 设计 capability registry 数据模型与加载入口，明确 mode、skill、tool、bundle、policy 的声明结构
  - [x] SubTask 1.2: 将现有 assistant mode、skill registry、tool bundle 与 prompt 资源迁移到统一注册中心
  - [x] SubTask 1.3: 为 registry 增加启动期一致性校验，覆盖缺失工具、缺失 prompt、非法 MCP 引用与策略漂移
  - [x] SubTask 1.4: 验证 mode / skill / tool / prompt 的声明与运行态装配一致

- [x] Task 2: 建立统一 Authorization Gateway：统一能力可见性、风险控制、确认流、可信写路径与只读策略。
  - [x] SubTask 2.1: 设计统一的授权决策模型，包含 visibility、risk、confirmation、write boundary 与 side-effect audit
  - [x] SubTask 2.2: 将 system_tools、document_tools 与 tool executor 的权限逻辑迁移到统一网关前置决策
  - [x] SubTask 2.3: 为只读 mode / skill 建立强约束，禁止绕过 bundle 的写入副作用
  - [x] SubTask 2.4: 验证权限拒绝、确认流、可信写入与危险命令策略行为一致

- [x] Task 3: 建立统一 Route Runtime 与无缝模式切换：让 mode、skill、prompt、tool 面和上下文计划以原子方式重建。
  - [x] SubTask 3.1: 抽取 Route Runtime，承接 semantic route、preferred mode、loaded skill 与 capability set 的标准对象
  - [x] SubTask 3.2: 扩展路由结果，完整保留 should_preload_context、prefer_live_web、confidence 等信号
  - [x] SubTask 3.3: 重构中途切模逻辑，移除“单独一轮只做切模”的硬性主路径
  - [x] SubTask 3.4: 验证模式切换后 prompt、工具面和能力边界同步更新且不会丢失当前意图

- [x] Task 4: 建立统一 Context Planner 与 Length Policy：统一预加载、预算分配、历史裁剪与 provider 适配。
  - [x] SubTask 4.1: 设计 context plan 数据结构，统一管理 memory recall、conversation summary、history compaction、session preload 与 live web 偏好
  - [x] SubTask 4.2: 设计 provider 无关的 Length Policy，并将其映射到 OpenAI、Anthropic、Gemini 等适配器
  - [x] SubTask 4.3: 将历史裁剪改为分层裁剪策略，避免将摘要作为普通 system message 回灌
  - [x] SubTask 4.4: 验证不同 provider、长上下文与高工具噪音场景下的长度治理稳定性

- [x] Task 5: 重构记忆系统为显式分层模型：拆分 episode、durable memory、conversation summary 与 memory graph。
  - [x] SubTask 5.1: 设计并实现新的记忆分层接口与存储结构，明确各层职责和访问路径
  - [x] SubTask 5.2: 为显式记忆写入增加同步 durable upsert 或等效强一致路径
  - [x] SubTask 5.3: 修复 session-aware recall，让调试接口与主执行链路使用一致的检索语义
  - [x] SubTask 5.4: 验证显式记忆写后可读、会话检索正确、partial consolidation 不会漏记

- [x] Task 6: 重构任务、定时任务与补发状态模型：显式拆分 schedule、execution、delivery 与 orchestration 状态。
  - [x] SubTask 6.1: 设计结构化任务状态对象与稳定状态转移规则
  - [x] SubTask 6.2: 将 claim、execute、retry、deliver、redeliver、completion 改为显式状态更新接口
  - [x] SubTask 6.3: 清理混合字段拼接主路径，并保留必要的数据迁移或兼容读取逻辑
  - [x] SubTask 6.4: 验证一次性任务、循环任务、自动执行、提醒任务、补发与失败重试的状态正确性

- [x] Task 7: 重构 Heartbeat 与健康聚合：统一候选问题集、信号类型、冷却判定和调度规则。
  - [x] SubTask 7.1: 对齐 heartbeat 与 service health 的退化问题集合，补齐 pending consolidation 等漏项
  - [x] SubTask 7.2: 清理无效或未实现的 signal kind，或完整实现其候选构造与路由策略
  - [x] SubTask 7.3: 将 heartbeat 决策输入切换为新的后台状态快照与任务状态模型
  - [x] SubTask 7.4: 验证 heartbeat、health、task orchestration 对同一故障场景的判断一致

- [x] Task 8: 迁移 Prompt / SKILL 装配与中层接口：减少硬编码、缩短 prompt 并统一调试观测。
  - [x] SubTask 8.1: 将 prompt 组装从 assistant_modes 拆分为独立 assembler，并接入 capability registry 与 route runtime
  - [x] SubTask 8.2: 将 skill 从 prompt-only 机制升级为 capability object，并支持 prompt-only enhancement 的兼容语义
  - [x] SubTask 8.3: 为中层编排提供统一调试快照，展示 route、context plan、memory scope、task state 与 authorization decision
  - [x] SubTask 8.4: 验证 Prompt 长度下降、调试信息完整且不暴露敏感信息

- [x] Task 9: 完成兼容迁移与清理：移除旧主路径、过时字段和策略分裂点。
  - [x] SubTask 9.1: 清理 assistant_modes、context、memory、task、heartbeat 中失效的 legacy 分支与过时字段
  - [x] SubTask 9.2: 为 registry、memory store 与 task store 提供必要的迁移逻辑或一次性升级路径
  - [x] SubTask 9.3: 更新示例配置、示例 memory 文件与调试接口输出，使其与新 schema 一致
  - [x] SubTask 9.4: 验证仓库主路径仅保留新的中层编排实现

- [x] Task 10: 完成系统级验证与回归：覆盖模式切换、工具授权、记忆、任务、心跳、长度治理与调试接口。
  - [x] SubTask 10.1: 增加单元测试、契约测试、状态机测试与 provider 适配测试
  - [x] SubTask 10.2: 完成模式切换、研究只读、记忆写入、定时任务补发、heartbeat 通知与长上下文的集成验证
  - [x] SubTask 10.3: 完成中层调试快照、启动期一致性校验与迁移路径的回归验证
  - [x] SubTask 10.4: 汇总新增发现的中层问题；如有失败项，继续追加任务并再次验证

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 1]
- [Task 4] depends on [Task 1], [Task 3]
- [Task 5] depends on [Task 4]
- [Task 6] depends on [Task 1]
- [Task 7] depends on [Task 6]
- [Task 8] depends on [Task 1], [Task 3], [Task 4]
- [Task 9] depends on [Task 2], [Task 5], [Task 6], [Task 7], [Task 8]
- [Task 10] depends on [Task 2], [Task 3], [Task 4], [Task 5], [Task 6], [Task 7], [Task 8], [Task 9]
