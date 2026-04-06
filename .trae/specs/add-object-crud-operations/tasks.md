# Tasks
- [x] Task 1: 为任务与定时任务补齐对象级 CRUD 动作。
  - [x] SubTask 1.1: 扩展任务工具动作集合，支持 detail、delete，以及必要的 restore 或等效恢复路径
  - [x] SubTask 1.2: 扩展定时任务工具动作集合，支持 detail、delete、cancel/disable 与必要的恢复语义
  - [x] SubTask 1.3: 为任务与定时任务补齐统一对象返回结构，包含对象类型、对象 ID、动作、状态与摘要
  - [x] SubTask 1.4: 验证助手可通过自然语言删除、查看详情与编辑指定任务或提醒

- [x] Task 2: 为记忆补齐对象级管理能力。
  - [x] SubTask 2.1: 为记忆建立稳定对象标识与列表/详情读取接口
  - [x] SubTask 2.2: 增加记忆 edit、delete、invalidate/forget 动作
  - [x] SubTask 2.3: 将记忆对象操作接入主助手暴露工具，并保持与现有检索/写入链路兼容
  - [x] SubTask 2.4: 验证助手可定位、编辑与删除指定记忆

- [x] Task 3: 建立统一对象操作协议与歧义处理。
  - [x] SubTask 3.1: 定义任务、定时任务、记忆共享的对象操作返回模型
  - [x] SubTask 3.2: 为相似名称对象增加稳定匹配与候选返回策略
  - [x] SubTask 3.3: 为 detail、edit、delete 等动作补齐冲突与未找到错误语义
  - [x] SubTask 3.4: 验证对象定位不明确时不会误删或误改

- [x] Task 4: 将对象高风险动作纳入授权网关与确认流。
  - [x] SubTask 4.1: 为删除、失效、批量修改和批量删除定义风险等级与确认策略
  - [x] SubTask 4.2: 将任务删除、定时任务删除、记忆删除/失效接入统一授权审计
  - [x] SubTask 4.3: 为对象操作失败、拒绝与确认中状态补齐调试信息
  - [x] SubTask 4.4: 验证高风险对象操作会触发正确确认流

- [x] Task 5: 扩展调试接口与前端对象状态可见性。
  - [x] SubTask 5.1: 扩展运行时调试接口，暴露最近对象操作、失败分类、确认状态与候选匹配信息
  - [x] SubTask 5.2: 扩展前端状态模型，展示对象操作结果、失败原因与确认提示
  - [x] SubTask 5.3: 确保调试输出脱敏，不暴露高敏记忆内容或危险请求细节
  - [x] SubTask 5.4: 验证前端和调试接口对对象 CRUD 状态展示一致

- [x] Task 6: 完成系统级测试与回归。
  - [x] SubTask 6.1: 增加任务、定时任务、记忆对象 CRUD 的单元与集成测试
  - [x] SubTask 6.2: 验证删除、详情查看、编辑、失效、歧义处理与确认流场景
  - [x] SubTask 6.3: 验证对象操作与现有任务调度、记忆检索、前端展示不会互相破坏
  - [x] SubTask 6.4: 汇总新增发现；如有失败项，追加任务并重新验证

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 1], [Task 2]
- [Task 4] depends on [Task 1], [Task 2], [Task 3]
- [Task 5] depends on [Task 3], [Task 4]
- [Task 6] depends on [Task 1], [Task 2], [Task 3], [Task 4], [Task 5]
