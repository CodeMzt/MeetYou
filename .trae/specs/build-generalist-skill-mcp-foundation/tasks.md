# Tasks
- [x] Task 1: 盘点并统一项目侧 SKILL / MCP / TOOL 能力声明，建立本次多面手能力改造所需的能力目录与分层模型。
  - [x] SubTask 1.1: 梳理现有 mode、skill、tool bundle、MCP server、基础工具与场景工具的入口和约束
  - [x] SubTask 1.2: 定义多面手能力目录的数据结构，覆盖场景层、skill 声明、MCP 声明、原生工具补位与降级策略
  - [x] SubTask 1.3: 明确哪些能力继续复用现有项目工具，哪些能力引入 MCP，哪些能力应新增项目内置 TOOLS

- [x] Task 2: 重构 SKILL 感知与激活机制，让助手在规划和路由阶段主动发现、选择并组合 skill。
  - [x] SubTask 2.1: 将自动激活 skill 的逻辑从硬编码名单迁移到声明式规则
  - [x] SubTask 2.2: 让 route 结果保留激活 skill、激活原因、能力来源与回退链路
  - [x] SubTask 2.3: 调整 prompt / skill 装配逻辑，使 skill 的提示、工具面和 MCP 绑定保持一致

- [x] Task 3: 为项目引入可治理的 MCP 能力层，覆盖学习办公辅助、科研、信息获取与热点追踪等方向。
  - [x] SubTask 3.1: 设计并接入 MCP 能力目录，声明每个 server 的用途、风险、认证要求、适用场景与回退路径
  - [x] SubTask 3.2: 将适合项目目标的 MCP server 绑定到对应场景层或 skill，而不是仅按 mode 静态附着
  - [x] SubTask 3.3: 为需要 API 或外部依赖的 MCP 输出结构化配置诊断，便于后续补充配置

- [x] Task 4: 补充项目内置 TOOLS，用于替代不值得单独引入 MCP 的轻量能力。
  - [x] SubTask 4.1: 识别学习、整理、提炼、结构化输出等可由原生工具覆盖的低复杂度场景
  - [x] SubTask 4.2: 实现必要的项目内置 TOOLS，并纳入统一工具注册、授权与 schema
  - [x] SubTask 4.3: 为这些工具补充与 skill / route 兼容的调用约定和输出格式

- [x] Task 5: 建立多面手 SKILL 能力包，覆盖学习、生活、工作、办公、科研、信息获取与热点追踪等关键方向。
  - [x] SubTask 5.1: 设计并创建一组场景 skill，明确触发条件、目标、输出与依赖能力
  - [x] SubTask 5.2: 将 skill 与 MCP / 原生 TOOLS / 现有基础工具建立声明式绑定
  - [x] SubTask 5.3: 校准各 skill 的只读边界、写入边界、信息源偏好与回退路径

- [x] Task 6: 扩展 capability registry、tool runtime 与授权链路，支持场景化能力选择、可用性诊断与稳定降级。
  - [x] SubTask 6.1: 在 capability registry 中纳入场景层能力分组、MCP 可用性与降级说明
  - [x] SubTask 6.2: 在工具可见性与授权阶段区分“已启用、需认证、不可用、已降级”等能力状态
  - [x] SubTask 6.3: 确保只读能力不会因新增 MCP 或原生工具而绕过安全边界

- [x] Task 7: 增加启动期一致性校验与诊断输出，防止 skill、MCP、tool 与路由声明漂移。
  - [x] SubTask 7.1: 校验 skill 引用的 prompt、tool、MCP、场景层与授权策略是否存在且兼容
  - [x] SubTask 7.2: 校验 MCP 声明与本地配置、认证状态、工具 schema 与可见性策略是否一致
  - [x] SubTask 7.3: 生成面向项目运行时的结构化诊断结果，便于识别仍需用户补充 API 的能力

- [x] Task 8: 完成系统级验证与回归，确认多面手能力在学习、办公、科研与信息获取场景下可稳定工作。
  - [x] SubTask 8.1: 为 skill 激活、MCP 选择、原生工具补位与降级链路补充单元测试或契约测试
  - [x] SubTask 8.2: 覆盖学习辅导、办公整理、科研研究、信息获取、热点追踪等代表性集成场景
  - [x] SubTask 8.3: 验证无 API、MCP 初始化失败、只读约束等异常分支下系统仍可给出可用结果
  - [x] SubTask 8.4: 汇总仍需用户后续配置的 MCP 能力，并以诊断结果输出而非阻塞主流程

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 1]
- [Task 4] depends on [Task 1]
- [Task 5] depends on [Task 2], [Task 3], [Task 4]
- [Task 6] depends on [Task 2], [Task 3], [Task 4]
- [Task 7] depends on [Task 3], [Task 5], [Task 6]
- [Task 8] depends on [Task 5], [Task 6], [Task 7]
