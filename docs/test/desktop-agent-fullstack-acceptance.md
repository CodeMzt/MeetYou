# Desktop Agent 本地 Windows 续测记录

## 1. 本轮目标

- 在云端一轮测试与合并后，继续用本地 Windows 环境补齐云端无法覆盖的 Desktop Agent 验收项。
- 本轮不再使用前端截图法，改用真实 API / WebSocket 链路、Desktop Agent 本地日志、前端自动化测试与交互代码检查。
- 同步处理主页面上默认空闲态的“已就绪：随时可以...”状态卡片。

## 2. 环境边界

- 本地 Core 未启用可用 PostgreSQL，因此不再尝试本机 `service` 真链路。
- 本地 `desktop_agent` 通过 [user/desktop_agent.json](/E:/Documents/Project/MeetYou/user/desktop_agent.json) 直接连接云端 Core `https://core.maziteng.cn`。
- 本轮聚焦：
  - Windows 本地 Desktop Agent / 本地桥接是否正常。
  - Agent 原生工具与 Agent 侧注册 MCP 工具是否确实在 Windows 侧执行。
  - 主对话流、本地桥接与前端主页面空闲态展示。
- Danxi 工具与 Danxi 子页面仍不纳入本轮验收。

## 3. 验收方式

### 3.1 替代截图法

- 不使用 `scripts/Capture-Screen.ps1`。
- 改为以下证据源组合：
  - 本地 `/desktop/*` HTTP 接口返回。
  - 本地 `/desktop/ws` 实时事件流。
  - Desktop Agent 本地日志。
  - 前端 `typecheck` / `vitest`。
  - 关键交互代码路径静态检查。

### 3.2 工具执行侧判定标准

- 必须出现 `execution_target: specific_agent` 与 `target_agent_id: desktop-agent-2`。
- `/desktop/ws` 中必须出现 `operation.updated` 从 `dispatching` 到 `succeeded` 的链路。
- 成功结果必须读取/返回 Windows 本地路径或 Agent 本地 MCP 允许目录中的内容，而不是云端 Linux 容器路径。

## 4. 实际执行命令

### 4.1 基础检查

1. `scripts\manual-acceptance.cmd check`
   - 结果：失败，本地 `service /health` 不可达。
2. 前台与后台方式尝试 `python main.py service`
   - 结果：本轮放弃；原因是本地 Core 缺少可用 PostgreSQL，不再继续卡在本机 Core 启动。

### 4.2 改用云端 Core + 本地 Windows Desktop Agent

1. 启动本地 `desktop_agent`
2. `GET http://127.0.0.1:38951/desktop/status`
3. `GET http://127.0.0.1:38951/desktop/workspaces`
4. `GET http://127.0.0.1:38951/desktop/procedures`
5. `POST /desktop/threads`
6. `POST /desktop/sessions`
7. `GET /desktop/workspaces/desktop-main/agents`

### 4.3 本地真实链路验证

1. 通过 `/desktop/ws?thread_id=...` 订阅实时事件。
2. 发送 Agent 原生 `utility.echo`：
   - `capability_id=agent.desktop-agent-2.utility.echo`
3. 发送 Agent 原生 `file.read`：
   - 目标路径：`C:\Users\19243\Documents\MeetYouAgentLocalReadTest.txt`
4. 发送 Agent 侧注册 MCP 工具 `read_file`：
   - `capability_id=agent.desktop-agent-2.mcp.filesystem_tools.read_file`
   - 目标路径：`E:\Documents\Project\MeetYou\AGENTS.md`
5. 通过 `/desktop/messages` 发送普通消息并在 `/desktop/ws` 上观察主对话流。
6. 创建 fresh session 后调用：
   - `GET /desktop/runtime/debug?session_id=...`
   - `GET /desktop/runtime/usage?session_id=...`

### 4.4 附件、审批工具与子页面数据面验证

1. 附件链路：
   - `POST /desktop/attachments/upload-ticket`
   - `PUT upload_url`
   - `POST /desktop/attachments/{attachment_id}/complete`
   - `GET /desktop/threads/{thread_id}/attachments`
   - `GET /desktop/attachments/{attachment_id}/download-ticket?client_id=desktop-app-2`
   - `GET download_url`
   - `DELETE /desktop/attachments/{attachment_id}`
2. 审批工具链路：
   - `POST /desktop/operations` 触发 `agent.desktop-agent-2.file.write`
   - `POST /desktop/operations` 触发 `agent.desktop-agent-2.shell.exec`
   - `POST /desktop/approvals/{approval_id}/decision` 批准后继续观察 `/desktop/ws`
3. 非 Danxi 子页面数据面：
   - `GET /desktop/config/schema`
   - `GET /desktop/config`
   - `GET /desktop/source-profiles`
   - `GET /desktop/memory?source_id=desktop-app-2&session_id=...`
   - `GET /desktop/memory/graph?source_id=desktop-app-2&session_id=...`
   - `GET /desktop/threads/{thread_id}/procedure-context`

### 4.5 自动化回归

1. `cd meetyou-ui && npm run typecheck`
2. `cd meetyou-ui && npm run test`
3. `.venv\Scripts\python.exe -m unittest tests.test_desktop_agent_runtime tests.test_desktop_agent_mcp_runtime tests.test_desktop_agent_ui_bridge tests.test_local_tool_agent_proxy`

## 5. 本轮结果

### 5.1 本地桌面桥接与 Agent 在线

- `GET /desktop/status` 成功，返回：
  - `local_bridge_base_url = http://127.0.0.1:38951`
  - `core_base_url = https://core.maziteng.cn`
- `GET /desktop/workspaces` 成功。
- `GET /desktop/procedures` 成功。
- `POST /desktop/sessions` 成功后，`GET /desktop/workspaces/desktop-main/agents` 返回在线 Agent：
  - `agent_id = desktop-agent-2`
  - `agent_type = desktop`
  - `status = online`
  - `transport_profile = desktop_wss`

### 5.2 Agent 原生工具验收

#### `utility.echo`

- `/desktop/ws` 收到完整链路：
  - `queued`
  - `dispatching`
  - `accepted`
  - `running`
  - `succeeded`
- 关键证据：
  - `execution_target = specific_agent`
  - `target_agent_id = desktop-agent-2`
  - `capability_id = agent.desktop-agent-2.utility.echo`
- 结果：通过。

#### `file.read`

- 本地先创建测试文件：
  - `C:\Users\19243\Documents\MeetYouAgentLocalReadTest.txt`
- `/desktop/ws` 收到完整链路：
  - `queued`
  - `dispatching`
  - `accepted`
  - `running`
  - `succeeded`
- 成功结果直接返回 Windows 本地路径与本地文件内容：
  - `path = C:\Users\19243\Documents\MeetYouAgentLocalReadTest.txt`
  - `content = local-agent-read-proof-20260424`
- 关键结论：
  - 文件读取确实发生在 Windows 本地 Desktop Agent 侧，不是云端 Core Linux。
- 结果：通过。

### 5.3 Agent 侧注册 MCP 工具验收

#### `mcp.filesystem_tools.read_file`

- Desktop Agent 本地日志显示：
  - `MCP server [filesystem_tools] initialized with 14 tools`
  - 允许目录来自 Windows 本地配置：`E:\Documents`
- `/desktop/ws` 收到完整链路：
  - `queued`
  - `dispatching`
  - `accepted`
  - `running`
  - `succeeded`
- 关键证据：
  - `capability_id = agent.desktop-agent-2.mcp.filesystem_tools.read_file`
  - 返回内容来自 `E:\Documents\Project\MeetYou\AGENTS.md`
- 关键结论：
  - Agent 侧注册工具确实在本地 Windows Agent 环境执行，而不是在云端 Core Linux 执行。
- 结果：通过。

### 5.4 正常对话流

- 通过本地 `/desktop/messages` 成功创建用户消息。
- `/desktop/ws` 收到：
  - `message.created`
  - `runtime.state(thinking -> answering -> idle)`
  - `reasoning.delta`
  - `message.delta`
  - `message.completed`
- 关键结论：
  - 本地 `/desktop/ws -> 云端 Core /client/ws` 实时主链正常可用。
- 结果：通过。

### 5.5 交互、主页面与非 Danxi 子页面检查

#### 已由代码确认的交互

- [meetyou-ui/src/components/input/ChatInput.tsx](/E:/Documents/Project/MeetYou/meetyou-ui/src/components/input/ChatInput.tsx)
  - 设置浮层已加入 click-outside 自动关闭。
- [meetyou-ui/src/components/status/StatusIsland.tsx](/E:/Documents/Project/MeetYou/meetyou-ui/src/components/status/StatusIsland.tsx)
  - 状态岛展开面板已加入 click-outside 自动关闭。
- [meetyou-ui/src/components/chat/MessageList.tsx](/E:/Documents/Project/MeetYou/meetyou-ui/src/components/chat/MessageList.tsx)
  - 已具备流式输出期间的自动追踪解锁与“回到底部继续追踪输出”按钮。

#### 本轮新增调整

- [meetyou-ui/src/components/status/StatusStrip.tsx](/E:/Documents/Project/MeetYou/meetyou-ui/src/components/status/StatusStrip.tsx)
  - 已移除主页面默认空闲态的“已就绪：随时可以...”状态卡片。
- [meetyou-ui/src/components/status/StatusStrip.test.tsx](/E:/Documents/Project/MeetYou/meetyou-ui/src/components/status/StatusStrip.test.tsx)
  - 已补测试，确保默认 ready 态隐藏，但连接中等非空闲态仍保留。
- 非 Danxi 子页面对应的数据面接口全部返回 `200`：
  - `/desktop/config/schema`
  - `/desktop/config`
  - `/desktop/source-profiles`
  - `/desktop/memory`
  - `/desktop/memory/graph`
  - `/desktop/threads/{thread_id}/procedure-context`
  - `/desktop/runtime/usage`
  - `/desktop/runtime/debug`
- 结果：通过。

### 5.6 附件链路验收

- `upload-ticket -> 上传 -> complete -> list -> download-ticket -> 下载 -> delete` 全链路完成。
- 下载内容与上传内容一致：
  - `desktop-attachment-proof-20260424`
- 删除后附件状态返回 `deleted`。
- 结果：通过。

### 5.7 需审批写入/执行工具验收

#### `file.write`

- 初次触发后进入 `waiting_approval`。
- 经 `/desktop/approvals/{approval_id}/decision` 批准后继续执行。
- `/desktop/ws` 收到：
  - `queued`
  - `dispatching`
  - `accepted`
  - `waiting_approval`
  - `running`
  - `succeeded`
- 实际写入 Windows 本地路径：
  - `C:\Users\19243\Documents\MeetYouAgentWriteTest.txt`
- 文件内容复核：
  - `local-agent-write-proof-20260424`
- 结果：通过。

#### `shell.exec`

- 初次触发后进入 `waiting_approval`。
- 批准后执行命令：
  - `echo runtime-shell-proof-20260424`
- `/desktop/ws` 收到完整成功链路并返回标准输出：
  - `runtime-shell-proof-20260424`
- 结果：通过。

### 5.8 云端 Core 复测结论

- fresh session 下 `GET /desktop/runtime/debug?session_id=...` 现在返回 `200`，且为 bootstrap debug，不再是 `500`。
- 缺失 session 的 runtime debug 现在返回结构化 `404`，不再是裸 `500`。
- fresh session 下再次触发 `agent.desktop-agent-2.utility.echo`，`/desktop/ws` 收到 `queued -> dispatching -> accepted -> running -> succeeded` 全链路。
- 云端 Core 部署滚动窗口内曾短暂出现 `/agent/ws` `502` 握手失败，但 Desktop Agent 自动重连后恢复；steady state 复测未再复现。
- 本地最新日志未再看到此前那条 `provider_bad_request` 作为稳定复现问题。
- 结果：通过。

## 6. 自动化验证结果

- `npm run typecheck`：通过
- `npm run test`：通过，`14` 个文件、`63` 个测试通过
- `npm run build`：通过，产物位于 `meetyou-ui/release/MeetYou Setup 1.0.0.exe` 与 `meetyou-ui/release/win-unpacked/`
- `tests.test_desktop_agent_runtime`：通过
- `tests.test_desktop_agent_mcp_runtime`：通过
- `tests.test_desktop_agent_ui_bridge`：通过
- `tests.test_local_tool_agent_proxy`：通过
- 后端最小相关 `unittest` 共 `27` 项通过

## 7. 当前边界说明

1. 本轮不再采用截图法，也未引入桌面级鼠标自动化；Electron 多窗口“点击体感”属于人工主观走查项，不再作为当前阻塞。
2. 非 Danxi 子页面本轮按“数据面接口 + 关键交互代码路径 + 自动化回归”完成验收，而不是逐页截图比对。
3. 直接访问云端 `/operator/agents` 的 `401` 不再视为功能缺陷；当前验收以本地 `/desktop/workspaces/desktop-main/agents` 能正确枚举在线 Agent 为准。

## 8. 阶段性结论

- 本地 Windows 侧最关键的 Agent 边界已经得到正向证据：
  - Agent 原生 `file.read` 在 Windows 本地执行。
  - Agent 侧注册 MCP `filesystem_tools.read_file` 也在 Windows 本地执行。
- Agent 原生 `file.write`、`shell.exec` 已在审批后完成真实链路验收，确认仍由本地 Windows Agent 执行。
- 附件上传、下载、删除完整链路通过。
- 本地桌面桥接到云端 Core 的正常对话主链、runtime debug / usage 与非 Danxi 子页面数据面可用。
- 主页面默认“已就绪：随时可以...”卡片已去除，前端回归通过。
- 按本轮“本地 Windows Desktop Agent + 云端 Core + 无截图”口径，当前验收已完成，可进入构建产物阶段。
