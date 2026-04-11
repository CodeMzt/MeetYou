# 人工启动验收手册

## 1. 目的

本文档用于手工验收 MeetYou 当前“第一版基本可用产品”相关主链，并提供一键启动/检查脚本，方便你自己排查：

- Core Service 是否正常启动
- Desktop Agent 是否在线
- Electron UI 是否连通
- workspace / procedure / operation / approval 等主链是否可见
- 常见问题该从哪里看

当前完成判定以 `docs/implementation-plan.md` 中的“第一版基本可用产品目标 / 完成判定”为准。

## 2. 适用范围

本手册优先覆盖当前第一版最重要的人工验收链路：

1. `service`
2. `desktop-agent`
3. `Electron UI`
4. `client/workspaces`
5. `client/procedures`
6. `operator/agents`
7. 聊天、Procedure、Operation 面板
8. confirm / human input 资源语义入口是否仍可正常工作

## 3. 前置条件

至少确认以下项目已经准备好：

1. 已创建 Python 虚拟环境并安装依赖
2. `meetyou-ui/` 已执行 `npm install`
3. 已准备最小配置文件：
   - `user/config.json`
   - `user/desktop_agent.json`
4. 如启用了 Gateway 鉴权，请先在当前终端设置 `MEETYOU_GATEWAY_ACCESS_TOKEN`

常见初始化参考：

```powershell
copy .env.example .env
copy user\config.example.json user\config.json
copy user\desktop_agent.example.json user\desktop_agent.json
```

## 4. 一键脚本

仓库已补充：

- `scripts\manual-acceptance.ps1`
- `scripts\manual-acceptance.cmd`

### 4.1 启动全部关键组件

```powershell
scripts\manual-acceptance.cmd start
```

默认会：

1. 启动 `python main.py service`
2. 等待 `GET /health` 可用
3. 启动 `python main.py desktop-agent`
4. 在 `meetyou-ui/` 下执行 `npm run dev`

可选参数：

```powershell
scripts\manual-acceptance.cmd start -SkipDesktopAgent
scripts\manual-acceptance.cmd start -SkipUi
scripts\manual-acceptance.cmd start -BaseUrl http://127.0.0.1:8000
```

### 4.2 只做启动后检查

```powershell
scripts\manual-acceptance.cmd check
```

默认会检查：

1. `GET /health`
2. `GET /client/workspaces`
3. `GET /client/procedures`
4. `GET /operator/agents`

如果配置了 `MEETYOU_GATEWAY_ACCESS_TOKEN`，脚本会自动带 `Authorization: Bearer ...`。

### 4.3 查看脚本帮助

```powershell
scripts\manual-acceptance.cmd help
```

## 5. 推荐验收顺序

### 步骤 1：启动

```powershell
scripts\manual-acceptance.cmd start
```

预期：

- 新开 service 窗口
- 新开 desktop-agent 窗口
- 新开 Electron/Vite 开发窗口

### 步骤 2：检查服务主链

```powershell
scripts\manual-acceptance.cmd check
```

预期：

- `/health` 成功
- `workspace` 数量大于 0
- `procedure` 数量大于 0
- 至少能看到一个 agent；如果你启动了 desktop-agent，预期它应为 `online`

### 步骤 3：检查 Electron 主界面

进入 Electron 窗口后，至少检查：

1. 标题栏连接状态不是 `disconnected`
2. `StatusIsland` 可展开，不会报错
3. Workflow 菜单能列出 procedure
4. 输入一条普通消息后，能看到消息流和返回
5. 执行一个 procedure 后，能看到 `OperationPanel` 中出现新的 operation 卡片

建议先尝试这类低风险输入：

```text
请用两句话说明当前系统现在主要由哪些部分组成。
```

Procedure 建议优先点一个 `core_only` 的规程，例如：

- `Code Review`
- `Study Note Synthesis`

### 步骤 4：检查 workspace / procedure / agent 视图

如果你要手工确认接口返回值，可在 PowerShell 中执行：

```powershell
$headers = @{}
if ($env:MEETYOU_GATEWAY_ACCESS_TOKEN) {
  $headers.Authorization = "Bearer $env:MEETYOU_GATEWAY_ACCESS_TOKEN"
}

Invoke-RestMethod -Uri "http://127.0.0.1:8000/client/workspaces" -Headers $headers
Invoke-RestMethod -Uri "http://127.0.0.1:8000/client/procedures" -Headers $headers
Invoke-RestMethod -Uri "http://127.0.0.1:8000/operator/agents" -Headers $headers
```

重点看：

- workspace 是否带出治理字段
  - `base_mode`
  - `prompt_overlay`
  - `default_execution_target`
  - `capability_policy`
  - `preferred_agent_ids`
  - `preferred_agent_types`
  - `agent_routing_policy`
- procedure 是否带出 routing 字段
  - `recommended_capabilities`
  - `preferred_capability_ref`
  - `preferred_agent_ids`
  - `preferred_agent_types`
  - `agent_routing_policy`
- desktop agent 是否 `online`

### 步骤 4.5：检查附件主链（第二版第一批）

当前前端附件按钮已升级为最小可用上传入口。

建议检查：

1. 在主界面点击回形针按钮
2. 选择一个小文件，例如 `txt/png`
3. 观察消息区是否出现一条系统提示，包含：
   - `attachment_id=...`
   - `download=...`
4. 复制该 `download` 链接到浏览器，确认能下载文件

如果你想直接走 HTTP 验证，可按以下顺序手工测试：

```powershell
$headers = @{}
if ($env:MEETYOU_GATEWAY_ACCESS_TOKEN) {
  $headers.Authorization = "Bearer $env:MEETYOU_GATEWAY_ACCESS_TOKEN"
}

$ticket = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/client/attachments/upload-ticket" -Headers $headers -ContentType "application/json" -Body '{"owner_type":"thread","owner_id":"manual-thread","kind":"file","mime_type":"text/plain","file_name":"manual.txt","client_id":"desktop-app"}'
```

后续可再用 `PUT $ticket.upload_url` 上传内容，并调用 complete / download-ticket。

### 步骤 4.6：检查 Agent 附件回传（第二版第二/三批）

当前如果某个 agent capability 回传了 `attachment_outputs`，主界面 `最近操作` 卡片会出现附件列表和下载按钮。

建议检查：

1. 触发一个会产生附件输出的 capability（如果当前环境已有）
2. 观察 operation 卡片底部是否出现 `Attachments`
3. 点击附件按钮，确认浏览器能打开下载链接或直接下载文件

如果当前环境暂时没有会产生附件的 capability，这一步可以等你后续接入截图/导出类 capability 后再验。 

### 步骤 5：检查 confirm / human input

这部分当前已经是“资源语义优先”，但是否触发取决于具体场景。

你可以用两种方式验：

1. 通过 UI 正常触发
2. 观察 service 日志、operation 面板和 action card 是否工作正常

如果当前场景没有自然触发，可以先跳过，等你在真实使用中遇到 confirm/human input 再按下述排障表回看。

### 步骤 6：检查后台任务 / 提醒

这部分已经接入 `operation` 主链，但人工验收通常依赖你已有 scheduled task / reminder。

推荐两种方式：

1. 如果你已有现成定时任务
   - 等待其触发
   - 观察 service 日志
   - 观察 UI 中 operation 是否更新
2. 如果你想主动造一个场景
   - 在 Electron 或 CIL 中让系统创建一个几分钟后的提醒/自动执行任务
   - 到点后观察是否出现后台执行和 operation 更新

当前这部分最关键的观察点：

- task / reminder 触发时不应直接静默消失
- service 日志里应能看到后台运行
- 若主链完整，应该能在 operation 侧看到对应运行记录

## 6. 常见排障

### 6.1 `scripts\manual-acceptance.cmd check` 里 `/health` 失败

优先检查：

1. service 窗口是否已启动并无异常退出
2. `user/config.json` 是否存在且 `gateway_host/gateway_port` 正常
3. 端口 `8000` 是否被别的进程占用

### 6.2 `service` 正常，但 `/operator/agents` 没有在线 agent

优先检查：

1. `desktop-agent` 窗口是否已启动
2. `user/desktop_agent.json` 是否存在
3. Desktop Agent 是否能连到 `http://127.0.0.1:8000`

### 6.3 Electron 一直 `connecting`

优先检查：

1. `service` 是否已健康
2. `desktop-agent` 是否异常刷错
3. `meetyou-ui/` 的 `npm run dev` 是否报 Vite/Electron 启动错误
4. 如果启用了 access token，当前客户端是否能拿到正确鉴权

### 6.4 procedure 菜单为空

优先检查：

1. `GET /client/procedures` 是否有返回
2. service 启动时数据库 bootstrap 是否正常
3. 当前 workspace / principal 是否异常

### 6.5 operation 有创建，但不继续推进

优先检查：

1. 这是 `core_only` 还是 `specific_agent/workspace_any_agent`
2. 若走 agent 路径，`/operator/agents` 是否在线
3. 是否触发了 approval、human input 或 confirm
4. service / desktop-agent 日志里是否有 capability resolution 或 dispatch 错误

### 6.6 后台任务 / 提醒没反应

优先检查：

1. service 日志里是否有 scheduler tick
2. 任务是否真的到了 `due_at/next_run_at`
3. UI / client 是否在线，是否具备 delivery target
4. 如果你看到 task 有 `last_operation_id` / `last_operation_status` 变化，说明后台主链已经跑过，问题可能在投递而不是调度

## 7. 建议你记录的信息

如果你要自己排查，建议每次验收至少记录：

1. service 是否健康
2. desktop-agent 是否在线
3. 当前 workspace 列表
4. 当前 procedure 列表
5. Electron 是否能正常发消息
6. operation 面板是否有新增项
7. 如有失败，失败发生在：
   - 路由解析
   - approval
   - human input
   - agent dispatch
   - 后台调度

这样你后面继续让我排查时，可以直接带着这些信息回来。 
