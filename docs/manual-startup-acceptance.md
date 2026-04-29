# Manual Startup Acceptance V4

本检查面向 Windows 本地开发链。注意：仓库 `.env` 可能主要用于连接远程 Core；本地验收时应通过当前进程环境覆盖地址、token 和端口，不要修改真实 `.env`。

## 启动

1. 启动本地 Core：`python main.py service`
2. 启动 UI：在 `meetyou-ui/` 运行 `npm run dev`
3. 启动 Desktop Provider：`python main.py desktop-client`

也可以使用 `scripts\manual-acceptance.cmd start` 拉起本地链，再用 `scripts\manual-acceptance.cmd check` 做基础探测。

完整 V4 本地主链验收可直接运行：

```powershell
.venv\Scripts\python.exe scripts\v4_real_acceptance.py --base-url http://127.0.0.1:8000 --ui-url http://127.0.0.1:5173 --desktop-tool-endpoint desktop.<provider-id>.executor --json-out logs\v4-local-acceptance.json
```

`--desktop-tool-endpoint` 用于验证真实 Desktop Provider 的 `utility.echo` 能力确实通过 ToolRouter + ExecutionTarget 执行；如果只验证合成 Endpoint，可省略该参数。

## 必查项

- `GET /health` 返回 ready。
- `GET /runtime/workspaces` 可返回工作区。
- `/client/ws` 不能建立 V4 连接。
- `/endpoint/ws` 完成 `endpoint.hello`、capability snapshot、ready、subscription。
- UI 空会话显示中文连接状态，不出现“等待后端服务启动后即可使用”这类误导远程 Core 的文案。
- 新建 Thread 后，断开并重连 Desktop / UI 可继续同一 Thread。
- 普通对话产生 Run、RunEvent、最终 assistant Message。
- Streaming 通过 RunEventLog + Delivery fan-out 展示。
- `assistant.progress_notice` 只作为进度通知出现，不进入最终回复文本。
- 本地工具调用通过 ToolRouter + ExecutionTarget 到达 Desktop Endpoint。
- `manage_scheduled_jobs` 可 list/detail/create/update/enable/disable/trigger 普通 Job。
- `system.heartbeat` 可启停和改 `interval_seconds`，不可删除、不可手动创建、不可改 action_ref/name/run_template。
- `endpoint.heartbeat` 只维持连接，不触发 `system.heartbeat`。
- Feishu / WeChatBot 非流式输出只发送最终 `message.completed`。

## 外部确认

Feishu 和 WeChatBot 测试必须使用唯一标识消息，并由人类确认收到内容。不能仅凭日志推断送达。

## 记录

验收结果写入 `docs/v4/test-report.md`，至少包含：

- commit sha
- 本地测试命令与结果
- 本地真实测试结果
- CI / Deploy 状态
- 远程 Core `/health` 和版本 / commit sha
- Desktop 连接远程 Core 真实测试
- Feishu / WeChatBot 人类反馈
