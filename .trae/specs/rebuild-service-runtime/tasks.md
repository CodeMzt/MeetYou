# Tasks
- [x] Task 1: 建立服务优先运行时骨架
  - [x] SubTask 1.1: 定义新的运行时模块边界，拆分会话执行、后台作业、工具执行、投递与遥测职责
  - [x] SubTask 1.2: 引入统一 command / event / error / health 数据模型
  - [x] SubTask 1.3: 让主入口切换到新运行时骨架，同时保留最小可启动能力
  - [x] SubTask 1.4: 验证服务可以启动并返回基础健康状态

- [x] Task 2: 重构配置治理与仓储层
  - [x] SubTask 2.1: 为配置、记忆、任务建立正式 repository 接口
  - [x] SubTask 2.2: 为配置更新增加类型校验、语义校验、事务提交与失败回滚
  - [x] SubTask 2.3: 为持久化写入增加原子写、版本标记与恢复策略
  - [x] SubTask 2.4: 验证非法配置不会污染持久化状态

- [x] Task 3: 建立 session actor 执行模型
  - [x] SubTask 3.1: 将统一入口拆为按 session 分片的执行器
  - [x] SubTask 3.2: 保证单会话内顺序一致、跨会话间可并行
  - [x] SubTask 3.3: 将会话运行态、usage 与执行上下文绑定到新执行器
  - [x] SubTask 3.4: 验证多会话并发不会互相阻塞

- [x] Task 4: 建立统一后台 job 运行时
  - [x] SubTask 4.1: 将 scheduler、heartbeat、housekeeping 与后台 agent 统一到 job 模型
  - [x] SubTask 4.2: 为 job 增加统一状态、重试、失败分类与投递结果
  - [x] SubTask 4.3: 收敛待补发、失败摘要与后台状态来源
  - [x] SubTask 4.4: 验证后台任务失败、重试与补发行为

- [x] Task 5: 重构工具执行链路
  - [x] SubTask 5.1: 拆分工具注册、权限策略、风险分级与执行器
  - [x] SubTask 5.2: 为内建工具与 MCP 工具提供统一结果与错误协议
  - [x] SubTask 5.3: 移除主路径中的字符串化错误返回
  - [x] SubTask 5.4: 验证工具超时、参数错误和权限拒绝均能返回稳定错误对象

- [x] Task 6: 升级 Gateway 与 WebSocket 协议
  - [x] SubTask 6.1: 为敏感接口与 WebSocket 引入鉴权
  - [x] SubTask 6.2: 收紧 CORS 与暴露面
  - [x] SubTask 6.3: 让 HTTP / WS 返回结构化 ack、error、health 与 runtime 结果
  - [x] SubTask 6.4: 验证未授权访问被拒绝，合法访问协议完整可用

- [x] Task 7: 建立协议单源与前端适配层
  - [x] SubTask 7.1: 抽取统一 schema 来源，收敛 runtime status、provider 列表与配置字段定义
  - [x] SubTask 7.2: 重构前端连接层，完整消费 connection、event、ack、error 与 health 事件
  - [x] SubTask 7.3: 拆分前端状态管理，补长会话裁剪或等效性能策略
  - [x] SubTask 7.4: 验证长会话、确认流与错误流在 UI 中可见且可用

- [x] Task 8: 建立可观测性与健康体系
  - [x] SubTask 8.1: 引入结构化日志上下文，统一 trace_id、session_id、turn_id、job_id、tool_call_id
  - [x] SubTask 8.2: 增加 live / ready / degraded 健康状态与关键指标
  - [x] SubTask 8.3: 将后台停滞、工具失败、网关投递失败纳入统一遥测
  - [x] SubTask 8.4: 验证关键故障场景下的健康状态和日志信息

- [x] Task 9: 清理遗留与破坏性迁移
  - [x] SubTask 9.1: 删除失效配置项、legacy 分支和过期兼容逻辑
  - [x] SubTask 9.2: 移除旧的 gateway-only 假设与字符串错误主路径
  - [x] SubTask 9.3: 更新示例配置、运行说明与迁移说明
  - [x] SubTask 9.4: 验证仓库主路径只剩新运行时实现

- [x] Task 10: 完成系统级验证
  - [x] SubTask 10.1: 补齐单元测试、契约测试、并发测试与故障注入测试
  - [x] SubTask 10.2: 完成前后端关键流转的端到端验证
  - [x] SubTask 10.3: 完成服务启动、鉴权、配置更新、后台任务、工具调用与 UI 接入的回归验证
  - [x] SubTask 10.4: 汇总新增优化点，必要时继续追加任务并再次验证
  - 验证记录（2026-04-05）：已执行 `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`、`npm run test`、`npm run typecheck`；后端 199 项测试、前端 7 项测试与类型检查全部通过，本轮未发现需追加到任务清单的失败修复项。
  - 观察记录：测试期间出现 Vite CJS / alias 弃用告警与 Python `asyncio` `ResourceWarning`，均未导致失败，暂记为后续工程优化信息。

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 1]
- [Task 4] depends on [Task 1]
- [Task 5] depends on [Task 1]
- [Task 6] depends on [Task 1], [Task 2], [Task 5]
- [Task 7] depends on [Task 6]
- [Task 8] depends on [Task 1], [Task 3], [Task 4], [Task 5], [Task 6]
- [Task 9] depends on [Task 2], [Task 3], [Task 4], [Task 5], [Task 6], [Task 7]
- [Task 10] depends on [Task 2], [Task 3], [Task 4], [Task 5], [Task 6], [Task 7], [Task 8], [Task 9]
