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
13. 不保留 `/client/ws`、`source_client_id`、`target_client_id`、`ClientToolDispatchService` 兼容路径。

## 测试阶梯

1. 先运行本地基础测试：Python tests、前端 typecheck/build/test、migration tests、endpoint protocol tests、scheduler tests、tool router tests、delivery tests。
2. 再启动本地 Core + Desktop + UI 做真实测试：Thread、Streaming、`assistant.progress_notice`、ToolRouter、Scheduler、`system.heartbeat`、断线重连。
3. 本地真实测试通过后，提交、推送、合并到 `main`。
4. 等待 GitHub Actions CI 和 Deploy 两者都通过。两者都通过后才说明远程 Core 已成功更新代码。
5. Deploy 通过后，确认远程 Core `/health` 和版本 / commit sha。
6. 拉起本地 Desktop，连接远程 Core，做真实测试：对话、Streaming、`assistant.progress_notice`、本地工具、Scheduler、Heartbeat、断线重连。
7. 最后测试 Feishu 和 WeChatBot。发送带唯一标识的真实消息，并使用人类提问工具询问是否收到，不能自行假设收到。
8. 写 `docs/v4/test-report.md`，记录 commit sha、CI/Deploy 状态、远程 Core 状态、本地 Desktop -> 远程 Core 测试、Feishu/WeChatBot 人类反馈。
