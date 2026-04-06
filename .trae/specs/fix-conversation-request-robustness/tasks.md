# Tasks
- [x] Task 1: 复现并分类对话请求失败：定位 DeepSeek 400、上下文超限、字段不兼容与流式边界错误的真实触发路径。
  - [x] SubTask 1.1: 审计 OpenAI 兼容适配器、DeepSeek 配置与 source catalog，确认 provider 路径、上下文上限与请求参数构造
  - [x] SubTask 1.2: 增加最小复现测试，覆盖长上下文、多轮工具调用、provider_items 续接与 400 分类
  - [x] SubTask 1.3: 为 400 错误建立结构化分类与诊断字段，区分超限、非法字段、鉴权、网络等失败类型
  - [x] SubTask 1.4: 验证日志与调试接口可准确反映失败来源

- [x] Task 2: 统一上下文预算口径：让估算值、真实请求体与 provider 限额一致。
  - [x] SubTask 2.1: 扩展预算估算，纳入 provider_items、tool_calls、tool 输出、压缩摘要与结构化消息
  - [x] SubTask 2.2: 对齐 Context Planner、Length Policy 与实际请求体构造逻辑
  - [x] SubTask 2.3: 为 DeepSeek / OpenAI 兼容路径校准 provider limit 与预算保留策略
  - [x] SubTask 2.4: 验证长上下文与多轮工具调用场景下不会再因预算低估导致请求异常

- [x] Task 3: 修复自动压缩链路：保留结构化上下文并保证压缩后仍可继续多轮对话。
  - [x] SubTask 3.1: 重构历史压缩输入，纳入 assistant tool_calls、tool 输出、provider_items 与必要元数据
  - [x] SubTask 3.2: 为压缩结果建立结构化摘要格式，保留函数名、关键参数、工具结果摘要与推理续接线索
  - [x] SubTask 3.3: 将压缩状态写入运行时上下文与调试接口，暴露是否压缩、压缩前后预算与压缩层级
  - [x] SubTask 3.4: 验证压缩后上下文连续、记忆/工具链路不失真

- [x] Task 4: 修复流式推理生命周期：确保 reasoning、answer、tool phase 和 round 边界一致。
  - [x] SubTask 4.1: 梳理 adapter、brain、app 三层的 round 状态，建立单轮模型执行边界
  - [x] SubTask 4.2: 在进入 tool phase、round end 或下一轮执行前主动结束当前 reasoning
  - [x] SubTask 4.3: 校正前端事件顺序，避免答案已输出而 reasoning 仍悬挂
  - [x] SubTask 4.4: 验证 reasoning-only、reasoning+tool、tool 后续答复、无 reasoning 四类场景

- [x] Task 5: 提升前端与调试可见性：暴露上下文压缩、预算状态、provider 限额与失败分类。
  - [x] SubTask 5.1: 扩展运行时调试接口与前端状态模型，展示本轮 provider、context limit、预算使用、是否压缩与失败分类
  - [x] SubTask 5.2: 为长上下文降级或自动压缩提供前端可见提示
  - [x] SubTask 5.3: 对调试输出进行脱敏，避免泄露完整请求内容、密钥或高敏路径
  - [x] SubTask 5.4: 验证前端展示与后端调试快照一致

- [x] Task 6: 完成系统级验证与回归：覆盖 DeepSeek 兼容路径、长上下文、工具调用与流式顺序。
  - [x] SubTask 6.1: 增加适配器、Context Planner、Brain、App、Gateway 与前端状态的单元/集成测试
  - [x] SubTask 6.2: 验证 DeepSeek 兼容接口在长上下文、自动压缩和工具调用场景下不再返回不可诊断 400
  - [x] SubTask 6.3: 验证推理流结束时机正确，前端不会再出现“正文已出但思考仍继续”的错乱状态
  - [x] SubTask 6.4: 汇总新增发现；若存在未通过项，追加任务并重新验证

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 2]
- [Task 4] depends on [Task 1]
- [Task 5] depends on [Task 2], [Task 3], [Task 4]
- [Task 6] depends on [Task 2], [Task 3], [Task 4], [Task 5]
