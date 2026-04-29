# Desktop Endpoint Fullstack Acceptance V4

Desktop 在 V4 中是 Endpoint Provider，不是 Client / Agent。

## 启动链

1. Core: `python main.py service`
2. UI: `npm run dev` under `meetyou-ui/`
3. Desktop Provider: `python main.py desktop-client`

## 验收点

- Desktop Provider 连接 `/endpoint/ws` 并发送 `endpoint.hello`。
- 能力通过 `endpoint.capabilities.snapshot` 上报。
- UI 通过 `/desktop/*` 访问本地桥，本地桥只代理 `/runtime/*`、`/operator/*`、`/developer/*`。
- 新建 Thread 后发送消息，Core 创建 user Message、Run、RunEvent 和最终 assistant Message。
- Streaming 展示来自 RunEventLog + Delivery fan-out。
- `assistant.progress_notice` 作为进度通知显示，不合入最终回复。
- 本地文件 / Shell / MCP 工具通过 ToolRouter 路由到 Desktop EndpointCapability。
- 断开 Desktop Provider 后重连，仍可继续同一 Thread。
- `/client/ws` 不能连接；`/client/*` 不返回业务数据。
- UI 不出现 Procedure 或“工作区与规程”入口；可复用工作流通过 SKILL。

## 输出记录

将命令、截图或日志摘要写入 `docs/v4/test-report.md`。
