# Desktop Agent 回归测试总纲

本文件用于后续本地与云端回归，不再采用前端截图验收。所有可自动化项目优先用 HTTP / WebSocket 真链路、前端组件测试、后端单测和构建验证完成；Danxi 仍按单独验收口径处理。

## 1. 功能主链

- 普通对话：创建 thread/session，经 `/desktop/messages` 发送消息，并在 `/desktop/ws` 观察 `message.created -> runtime.state -> message.delta -> message.completed`。
- Thinking 输出：开启 thinking 后必须能收到 reasoning stream；如果同一轮产生 tool call，后续请求必须带回该 assistant 消息的 `reasoning_content`。
- 失败恢复：provider 400/401/429/上下文超限需要记录结构化 `last_failure`，UI 不应卡死在 thinking 状态。
- Runtime 诊断：fresh session 的 `/desktop/runtime/debug` 返回 bootstrap debug；缺失 session 返回结构化 404。

## 2. 工具边界

- Core 工具：确认 `execution_target=core_only` 的工具不会被错误派发到 Agent。
- Desktop Agent 原生工具：覆盖 `utility.echo`、`file.read`、审批后的 `file.write`、审批后的 `shell.exec`。
- Agent MCP 工具：覆盖本地 `mcp.filesystem_tools.read_file`，返回路径必须来自 Windows 允许目录。
- 工具审批：审批前状态必须是 `waiting_approval`，批准后继续执行，拒绝后给出可读失败结果。
- 工具日志：`/desktop/ws` 必须包含 `queued -> dispatching -> accepted -> running -> succeeded/failed`。

## 3. 记忆管理

- 记忆展示：记忆图谱窗口能加载概览、记录列表、时间线、图视图。
- 清空全部：顶部“清空全部记忆”需要确认词，执行后记录、边、会话摘要和运行态对话上下文都被清理。
- 单条失效：记录列表每条 active 记忆可设为 `invalidated`，默认列表和召回不再返回。
- 单条恢复：`invalidated` 记忆可恢复为 `active`。
- 单条删除：删除后记录和相关 graph edge 不再暴露；缺失 ID 返回结构化 404。

## 4. 子页面与入口

- 标题栏入口：设置、记忆图谱、工作区与规程、附件、上下文与用量、开发工具、Danxi 都能打开对应窗口。
- 非 Danxi 子页面：设置、记忆、工作区、附件、上下文、开发工具至少覆盖数据面加载和主要操作按钮。
- 工作区页：最近操作仅在工作区/调试相关页面展示，不占用主聊天页面。
- 附件页：上传 ticket、complete、list、download ticket、download、delete 全链路通过。

## 5. 主页面交互

- 主页面只保留灵动岛作为状态入口，不再渲染非灵动岛状态卡片。
- 流式输出时，用户上滚必须解除自动贴底；点击回到底部后恢复追踪。
- 输入框设置浮层、灵动岛浮层点击外部区域会自动关闭。
- 空会话、服务降级、运行错误、人工确认、人类输入等待都要有可读反馈。

## 6. 自动化验证

- 后端最小相关：`tests.test_openai_adapter tests.test_brain_runtime tests.test_memory_redesign tests.test_gateway_memory_api tests.test_desktop_agent_ui_bridge`。
- Agent 边界：`tests.test_desktop_agent_runtime tests.test_desktop_agent_mcp_runtime tests.test_local_tool_agent_proxy`。
- 前端：`npm run typecheck`、`npm run test`。
- 构建：涉及 Electron、Vite、入口或发布资源时必须跑 `npm run build`。

## 7. 发布后复测

- 涉及 Core 的变更合并到 `main` 后，等待 GitHub Action 完成云端更新，再用本地 Windows `desktop_agent` 连接云端 Core 复测。
- 发布后至少复测：普通对话、thinking+tool、记忆清空/单条删除、Agent 文件工具、附件链路、审批工具链路、runtime debug。
- 如果云端部署窗口出现 `/agent/ws` 短暂 502，需要等待自动重连后再判断 steady state。
