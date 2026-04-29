# Desktop To Remote Core Acceptance V4

远程验收必须在本地测试、提交、推送、合并 main、CI 和 Deploy 全部通过之后执行。

## 准备

- 确认远程 Core `/health` ready。
- 确认远程版本或 commit sha 与 main 最新提交一致。
- 本地 Desktop Provider 使用远程 Core 地址和 token 启动；不要修改真实 `.env`，用当前进程环境覆盖。

## 验收点

- Desktop Provider 连接远程 `/endpoint/ws`。
- UI 可新建 Thread 并发送普通对话。
- Streaming 正常显示，最终回复由远程 Core 持久化。
- `assistant.progress_notice` 可见且不进入最终回复。
- 本地工具调用通过 ToolRouter 到本地 Desktop Endpoint。
- Scheduler 普通 Job 可创建、触发并产生 Run / RunEvent。
- `system.heartbeat` 可启停和改间隔，不可删除。
- 断线重连后继续同一 Thread。

## 外部端点

最后测试 Feishu 和 WeChatBot。每条消息使用唯一标识，并要求人类确认收到内容。结果写入 `docs/v4/test-report.md`。
