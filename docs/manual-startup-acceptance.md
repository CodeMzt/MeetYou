﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿# 人工启动验收手册

## 1. 目的

本文档用于手工验收 MeetYou 当前“第一版基本可用产品”相关主链，并提供一键启动/检查脚本，方便你自己排查：

- Core Service 是否正常启动
- Desktop Agent 是否在线
- Electron UI 是否连通
- workspace / procedure / operation / approval 等主链是否可见
- 独立“工作区与规程”管理页是否能承接治理编辑与聚合状态
- 独立“附件管理”页是否能承接附件浏览、下载与删除
- Danxi 二阶段子页面、自动恢复登录、凭证加密与低风险用户操作是否符合口径
- 状态反馈是否符合 `StatusIsland` + operation 细粒度反馈的新模型
- `Core Heart` 时间编排、agent heartbeat 协商与任务分域是否能被一致解释
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
9. 附件工具化回传、管理页和状态反馈模型是否一致
10. 附件管理页是否可查看时间戳、执行下载与删除，且上传成功不再向聊天流注入提示
11. 可选的 `edge-agent` / `F93` 验收路径是否可跑通，包括 heartbeat 协商与最小 capability 样例
12. 可选的 Danxi / `F102` 二阶段路径是否可跑通，包括紧凑布局、自动恢复登录、回复编辑删除、AI 摘要与 WebVPN 记录

## 3. 前置条件

至少确认以下项目已经准备好：

1. 已创建 Python 虚拟环境并安装依赖
2. `meetyou-ui/` 已执行 `npm install`
3. 已准备最小配置文件：
   - `user/config.json`
   - `user/desktop_agent.json`
   - 如需验收边缘链路，再准备 `user/edge_agent.json`
4. 如启用了 Gateway 鉴权，请先在当前终端设置 `MEETYOU_GATEWAY_ACCESS_TOKEN`
5. 如需验收 Danxi 二阶段安全链路，请确认 `.env` 中存在 `MEETYOU_CREDENTIAL_SECRET`；未单独配置时可回退到 `MEETYOU_GATEWAY_ACCESS_TOKEN` / `MEETYOU_AGENT_ACCESS_TOKEN`，但不建议在文档和部署中长期省略专用密钥

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
3. 标题栏的 `上下文与用量` 按钮可打开独立窗口，并能看到当前会话的上下文 / token 面板
4. 标题栏的 `工作区与规程` 按钮可打开独立窗口，并能看到 workspace 概览、procedure 目录、procedure 详情以及当前上下文
5. `工作区与规程` 窗口左侧应同时显示当前 workspace 状态、运行中 operation 数、待处理审批数、待补充输入数
6. `工作区与规程` 窗口里的治理编辑区可加载 source profile 目录，并可保存当前 workspace 的来源偏好与记忆排序
7. 在 `工作区与规程` 窗口里可以把某个 procedure 固定到当前 thread，也可以取消固定
8. 主窗口的 `StatusIsland` 在空闲、思考中、错误态之间切换时不应报错；operation 卡片应能展示与其区分开的 `summary`
9. 标题栏或菜单中的“附件管理”入口可打开独立页面，并能看到 attachment 列表与关键时间戳
10. 输入一条普通消息后，能看到消息流和返回
11. 不要求从前端手动执行 procedure；如果消息被系统路由到某个 procedure，上下文展示不应报错

建议先尝试这类低风险输入：

```text
请用两句话说明当前系统现在主要由哪些部分组成。
```

如需确认 Procedure 数据面，可优先检查 `GET /client/procedures` 返回，并确认至少包含一个内置 procedure，例如：

- `代码审查`
- `学习笔记整理`

### 步骤 4：检查管理页与 workspace / procedure / agent 视图

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
- 如果管理页已打开，workspace 保存后页面状态是否刷新，且不需要回退到 debug 面

### 步骤 4.5：检查附件主链与工具化回传

当前前端附件按钮已升级为最小可用上传入口；agent / tool 产出的附件也已走 `attachment_outputs -> attachment object view` 主链。

建议检查：

1. 在主界面点击回形针按钮
2. 选择一个小文件，例如 `txt/png`
3. 观察消息区或 operation 卡片是否出现附件对象，而不是只出现临时文本链接
4. 点击附件对象，确认能下载文件
5. 如果下载走预签名 URL，不要求 URL 长得像 `client/attachments/content/*`；如果走兼容代理，则允许回退到 Core 内容路由

如果你想直接走 HTTP 验证，可按以下顺序手工测试：

```powershell
$headers = @{}
if ($env:MEETYOU_GATEWAY_ACCESS_TOKEN) {
  $headers.Authorization = "Bearer $env:MEETYOU_GATEWAY_ACCESS_TOKEN"
}

$ticket = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/client/attachments/upload-ticket" -Headers $headers -ContentType "application/json" -Body '{"owner_type":"thread","owner_id":"manual-thread","kind":"file","mime_type":"text/plain","file_name":"manual.txt","client_id":"desktop-app"}'
```

后续可再用 `PUT $ticket.upload_url` 上传内容，并调用 complete / download-ticket。

### 步骤 4.6：检查 Agent 附件回传（工具化模型）

当前如果某个 agent capability 回传了 `attachment_outputs`，主界面 `最近操作` 卡片和相关消息对象会出现统一附件列表与下载按钮。

建议检查：

1. 触发一个会产生附件输出的 capability（如果当前环境已有）
2. 观察 operation 卡片底部是否出现 `Attachments`
3. 观察 operation 的 `summary` 先反映执行结果，再由附件列表承接文件产物，不要求把下载链接直接拼进摘要文本
4. 点击附件按钮，确认浏览器能打开下载链接或直接下载文件

如果当前环境暂时没有会产生附件的 capability，这一步可以等你后续接入截图/导出类 capability 后再验。 

### 步骤 4.7：检查可选 Edge Agent / F93 路径

如果你本轮还要验证 `F93`，建议额外开一个终端手动启动：

```powershell
python main.py edge-agent
```

建议检查：

1. `GET /operator/agents` 能看到 `agent_type=edge` 的 agent，且状态会随连接恢复为 `online`
2. Edge Agent 首次连接后，`agent.hello.ack` 返回的 `heartbeat_interval_seconds` 会被当前连接立即采用，而不是等旧间隔耗尽
3. 如果你修改了 `user/edge_agent.json` 的 `workspace_ids`，`/operator/agents` 中的 workspace 绑定会同步更新
4. 当前最小 capability 样例至少应保留 `utility.echo` 或等价低风险边缘能力，便于验证 capability call 主链

如只想做最小自动验证，可执行：

```powershell
.venv\Scripts\python.exe -m unittest tests.test_edge_agent_protocol tests.test_edge_agent_runtime
```

### 步骤 4.8：检查可选 Danxi / F102 二阶段路径

Danxi 二阶段验收应优先走低风险、顺序化路径，并显式记录本次走的是直连还是 WebVPN。

建议顺序：

1. 从 Electron 标题栏或菜单打开 Danxi 独立窗口
2. 检查子页面在当前窗口尺寸下是否保持紧凑三栏布局，标题区、滚动区、空态区和操作区无裁切或错位
3. 如在校内网络，优先尝试直连登录；如在校外网络，打开 Electron 内嵌 WebVPN 登录窗，由用户手动完成登录后让程序自动提取 cookie
4. 登录成功后检查会话区是否展示当前账号、transport、WebVPN 状态、用户信息、分区、帖子、楼层与消息
5. 选择一个可控测试帖，依次验证回复、编辑回复、删除回复和 AI 摘要；每步都确认详情区、楼层列表和状态提示同步刷新
6. 关闭并重新打开 Electron 或重启 service 后再次进入 Danxi 页面，确认系统会自动尝试恢复会话；若已保存会话失效，应看到“已清理并要求重新登录”的明确提示，而不是反复失败

最小自动验证命令：

```powershell
.venv\Scripts\python.exe -m unittest tests.test_danxi_tools tests.test_assistant_modes tests.test_gateway_surface_routes
cd meetyou-ui
npm run typecheck
npm run test
```

重点观察：

- Danxi 登录与 WebVPN cookie 更新只允许 `encrypted_credentials`；缺少密文字段时应直接失败，而不是回退到明文 email/password/cookie 直传
- 日志、错误提示和开发者输出中不应出现明文凭证
- 如果本次走 WebVPN，需要在验收记录里写明“WebVPN 登录窗 + 自动提取 cookie”是否成功
- 写操作仅做最小必要验证，避免对真实帖子做批量或破坏性修改

### 步骤 5：检查 confirm / human input

这部分当前已经是“资源语义优先”，但是否触发取决于具体场景。

你可以用两种方式验：

1. 通过 UI 正常触发
2. 观察 service 日志、operation 面板和 action card 是否工作正常

如果当前场景没有自然触发，可以先跳过，等你在真实使用中遇到 confirm/human input 再按下述排障表回看。

### 步骤 6：检查后台任务 / 提醒

这部分已经接入 `operation` 主链，但人工验收通常依赖你已有 scheduled task / reminder。

先统一术语：

- `user_todo`：用户自己的待办，允许有 deadline，但不会因为自然语言时间描述而被 `Core Heart` 自动 claim
- `assistant_schedule`：助手拥有的定时编排对象，必须有 trigger 语义，会被 `Core Heart` 的 `scheduler loop` claim，并产出 operation

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
- `scheduler loop` 负责 claim / pre-create operation / control event，`heartbeat reasoning loop` 负责把 `pending_redelivery`、`awaiting_completion`、逾期 follow-up 等时间压力整理成 Heart 时间感信号
- 不要把上面的 Heart 时间编排和 `/agent/ws` 上的 agent heartbeat 混为一谈；后者只负责在线状态与运行指标

## 6. 常见排障

### 6.0 状态反馈看起来不一致

优先检查：

1. `StatusIsland` 是否只负责连接/思考中的顶层状态，而不是试图替代 operation 细节
2. operation 卡片是否拿到了最新 `status/phase/detail/result.summary`
3. 如果附件来自 tool / capability，是否已经完成 `attachment_outputs` 上传并被 Core 归一化
4. 如管理页计数不刷新，检查主窗口到 `workspace-panel-updated` 的同步是否正常

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

### 6.7 Edge Agent 心跳或 F93 验收异常

优先检查：

1. `user/edge_agent.json` 是否存在，且 `core_base_url`、`agent_id`、`workspace_ids`、`transport_profile` 正确
2. service 日志或 agent 日志里是否能看到 `agent.hello.ack`，以及其中的 `heartbeat_interval_seconds`
3. 如果心跳间隔被协商修改，当前连接是否立即按新间隔发送 `agent.heartbeat`
4. 如自动测试失败，先单独运行 `tests.test_edge_agent_protocol` 与 `tests.test_edge_agent_runtime`，再决定是否继续联调 `tests.test_gateway_agent_api`

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
