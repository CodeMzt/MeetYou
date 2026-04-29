# V4 Implementation Plan

本文件只记录当前 V4 推进线。历史 V2 / V3 计划不再作为实现依据。

## 目标状态

- Core-owned Runtime + Endpoint Routing。
- `/runtime/*` 是正式 HTTP facade。
- `/endpoint/ws` 是唯一实时 Endpoint Provider 入口。
- ToolRouter + ExecutionTarget 是唯一工具调度链。
- Scheduler 是唯一系统级调度时钟。
- Procedure 删除，可复用工作流统一由 SKILL 承担。
- 公开 mode 仅保留 `general`、`automation`、`danxi`。

## 阶段

1. Domain Schema / Migration / Bootstrap
   Actor、Endpoint、EndpointConnection、EndpointCapability、Run、RunEvent、ScheduledJob、ScheduledJobRun、EndpointOutbox、Operation target。

2. Endpoint Protocol
   `/endpoint/ws`、`meetyou.endpoint.ws.v4`、Endpoint lifecycle / subscription / delivery / tool frames。

3. Run / Message / Delivery / Streaming
   Thread / Message / Run 归 Core，Streaming 走 RunEventLog + Delivery fan-out，最终回复落 MessageService。

4. `assistant.progress_notice`
   替代 directed tool 版 `short_reply`。它不经过 ToolRouter，不创建 Operation，不进入最终 assistant message。

5. ToolRouter / ExecutionTarget
   移除 ClientToolDispatchService，能力来自 EndpointCapability，权限来自 Actor / Workspace / RunPolicy。

6. Scheduler / Heartbeat
   Scheduler 拥有 `system.heartbeat` 和普通 scheduled jobs。`system.heartbeat` 不可删除、不可手动创建，只能启停和改间隔。

7. Desktop / Edge / UI
   Desktop 和 Edge 是 Endpoint Provider。UI 通过 Thread / Run / Delivery 工作，断线重连继续同一 Thread。

8. External Delivery
   Feishu / WeChatBot 是 external Endpoint / adapter。非流式输出只发送最终 `message.completed`。

## 当前收口要求

- 不保留 `/client/ws`、`source_client_id`、`target_client_id`、`ClientToolDispatchService`。
- `/client/*` 若仍存在，只能返回 removed 响应。
- 不恢复 Procedure 表、API、工具、prompt layer、UI 或 pinned 字段。
- 工具声明必须与底层一致：`manage_tasks` 只管用户 TODO；Scheduler 任务使用 `manage_scheduled_jobs`。
- 文档、测试、示例配置必须使用 Endpoint、Runtime、Scheduler、SKILL 术语。

## 验证

本地必须覆盖：

- Python tests。
- migration / bootstrap tests。
- endpoint protocol tests。
- scheduler tests。
- tool router tests。
- delivery tests。
- frontend typecheck / test / build。
- 本地 Core + Desktop + UI 真实测试。
- 远程 Core 部署后健康检查和 Desktop 远程连接测试。
- Feishu / WeChatBot 唯一标识真实消息，并取得人类确认。

最终测试记录写入 `docs/v4/test-report.md`。
