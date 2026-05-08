# MeetYou V4 不可违反原则

V4 是开发期大换血，不做 V3 兼容。实现、测试、文档和发布流程都必须遵守以下原则。

1. Core owns Thread / Message / Run / Scheduler / Heartbeat / Memory / Operation / Delivery。
2. Client is only Endpoint Provider。
3. Core is not Client；`core.local` 是 in-process `ExecutionTarget`，不是 Client。
4. Scheduler 是唯一系统级调度时钟。
5. `system.heartbeat` 是 Scheduler 内不可删除、可启停、可修改间隔的系统预设 Job。
6. `endpoint.heartbeat` 只是连接保活，不触发 `system.heartbeat`。
7. `short_reply` 不再作为 directed tool；替换为 `assistant.progress_notice` RunEvent / Runtime Action。
8. Delivery 负责投递 `message` / `run_event` / `notice` / `operation_update`，不负责生成回复。
9. Final assistant reply 必须是 MessageService 持久化的 assistant message。
10. Streaming 必须走 RunEventLog + Delivery fan-out。
11. Tool 调度必须走 ToolRouter + ExecutionTarget。
12. 权限挂在 Actor / Workspace / RunPolicy；执行能力挂在 EndpointCapability。
13. `exec_core_cmd` 是显式 Core-host shell 例外，只能在 Core Service 主机通过 `core.local` 执行，并且必须受 Core 白名单策略约束；`exec_sys_cmd` 仍代表 Endpoint shell。
14. V4 HTTP facade 是 `/runtime/*`；桌面本地 `/desktop/*` 只能代理到 `/runtime/*`、`/operator/*`、`/developer/*`，不得代理旧 `/client/*`。
15. 不保留 `/client/ws`、`source_client_id`、`target_client_id`、`ClientToolDispatchService` 兼容路径。
16. 运行态 assistant mode 只能是 `general` / `automation` / `danxi`；旧 `normal` / `auto` / `documents` / `research` / `study` / `office` 只能在边界归一化，不能作为运行态模式保存或暴露。
17. Procedure 已删除。不得恢复 Procedure 表、API、工具、pinned 字段、prompt layer 或 UI；可复用工作流统一使用 SKILL。
18. SKILL 是唯一可复用工作流指导层；`list_skills` / `load_skill` / `create_skill` 是公开入口，SKILL 查询必须匹配标题、摘要、场景和推荐工具，能力暴露必须继续走 CapabilityRegistry / SemanticRouter / ToolRouter / ExecutionTarget。

## 测试阶梯

## 调度补充

- `App.scheduler_processor()` 是 V4 唯一系统级调度入口。
- Heart 只保留被 `system.heartbeat` Job 调用的一次性 heartbeat 执行能力；不得恢复 Heart 自有 scheduler loop 或 heartbeat loop。
- `service_runtime` 兼容路径也必须启动 `App.scheduler_processor()`，不得绕回 Heart 调度。

1. 先运行本地基础测试：Python tests、前端 typecheck/build/test、migration tests、endpoint protocol tests、scheduler tests、tool router tests、delivery tests。
2. 再启动本地 Core + Desktop + UI 做真实测试：Thread、Streaming、`assistant.progress_notice`、ToolRouter、Scheduler、`system.heartbeat`、断线重连。
3. 本地真实测试通过后，提交、推送、合并到 `main`。
4. 等待 GitHub Actions CI 和 Deploy 两者都通过。两者都通过后才说明远程 Core 已成功更新代码。
5. Deploy 通过后，确认远程 Core `/health` 和版本 / commit sha。
6. 拉起本地 Desktop，连接远程 Core，做真实测试：对话、Streaming、`assistant.progress_notice`、本地工具、Scheduler、Heartbeat、断线重连。
7. 最后测试 Feishu 和 WeChatBot。发送带唯一标识的真实消息，并使用人类提问工具询问是否收到，不能自行假设收到。
8. 写本地忽略报告 `docs/_local/v4-test-report.md`，记录 commit sha、CI/Deploy 状态、远程 Core 状态、本地 Desktop -> 远程 Core 测试、Feishu/WeChatBot 人类反馈，除非明确要求发布报告。
