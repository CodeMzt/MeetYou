# Tasks
- [x] Task 1: 定义回复控制与检查点后端模型：梳理 active turn、控制命令、检查点、可重放输入与流式结束原因的统一数据结构与状态转移。
  - [x] SubTask 1.1: 设计会话控制状态，覆盖 active、canceling、replaying、rolled_back、failed_replay 等关键状态
  - [x] SubTask 1.2: 设计检查点结构，明确 chat history 边界、turn 标识、usage snapshot、runtime metadata 与输入引用的最小恢复集
  - [x] SubTask 1.3: 设计流式结束原因与控制命令响应语义，统一 stop、append guidance、regenerate、rollback 的 accepted / rejected / completed 结果

- [x] Task 2: 建立可取消的回复执行链路：让网关、会话 actor、Brain 与 adapter 能协同中断当前流式回复。
  - [x] SubTask 2.1: 为网关增加回复控制命令入口，并完成会话归属、幂等与状态校验
  - [x] SubTask 2.2: 为 session actor / app 执行链路增加当前 turn cancel handle 或等效取消机制
  - [x] SubTask 2.3: 为 adapter 流式调用增加 cancel signal，并确保中断后不再继续推送正文或推理增量
  - [x] SubTask 2.4: 统一中断后的 stream end、runtime idle、usage 收束与错误分类

- [x] Task 3: 实现回复时追加引导：支持在生成中插入补充要求并基于稳定上下文重放当前回复。
  - [x] SubTask 3.1: 定义追加引导与最近待完成用户意图的合并策略，避免把引导永久写成独立脏历史
  - [x] SubTask 3.2: 在中断当前回复后恢复到起始检查点，并以合并后的输入重新触发回复
  - [x] SubTask 3.3: 暴露追加引导控制结果与新的 turn/stream 标识，保证前端可正确切换显示

- [x] Task 4: 实现重新回复：允许恢复上一轮稳定检查点并重新生成最近一次回复。
  - [x] SubTask 4.1: 保存最近一次可重放回复所需的输入引用与起始检查点
  - [x] SubTask 4.2: 在 regenerate 时清理被替换回复残留的 assistant/tool 历史，并重新发起模型回复
  - [x] SubTask 4.3: 为不满足重放条件的场景返回明确拒绝原因，而不是静默失败

- [x] Task 5: 实现检查点查询与回退：提供显式检查点列表、指定检查点恢复与后续历史裁剪能力。
  - [x] SubTask 5.1: 在关键 turn 边界创建、保存并淘汰检查点，控制数量与生命周期
  - [x] SubTask 5.2: 提供查询当前会话可用检查点的后端接口
  - [x] SubTask 5.3: 提供回退到指定检查点的后端接口，并在恢复后清理失效控制态与后续历史

- [x] Task 6: 扩展协议与可观测性：让回复控制状态、结束原因、检查点与控制结果可被前端和调试接口消费。
  - [x] SubTask 6.1: 扩展 WebSocket / HTTP 协议模型，暴露控制命令、执行结果、stream finish reason 与检查点摘要
  - [x] SubTask 6.2: 为调试接口输出当前 active turn、最近控制动作、可用检查点数量与最近可重放输入状态
  - [x] SubTask 6.3: 确保调试与协议输出脱敏，不泄露完整历史内容、密钥或高敏路径

- [x] Task 7: 完成系统级验证与回归：覆盖中断、追加引导、重新回复、检查点回退、异常回收与幂等行为。
  - [x] SubTask 7.1: 增加单元测试，覆盖状态机、检查点恢复、历史裁剪与结束原因判定
  - [x] SubTask 7.2: 增加集成测试，覆盖 stop、append guidance、regenerate、rollback 的端到端行为
  - [x] SubTask 7.3: 验证中断或回退后不会残留悬挂 stream、错误 runtime 状态或脏 assistant/tool 消息
  - [x] SubTask 7.4: 汇总新增问题；若存在未通过项，追加任务并重新验证

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 1], [Task 2]
- [Task 4] depends on [Task 1], [Task 2]
- [Task 5] depends on [Task 1]
- [Task 6] depends on [Task 2], [Task 3], [Task 4], [Task 5]
- [Task 7] depends on [Task 2], [Task 3], [Task 4], [Task 5], [Task 6]
