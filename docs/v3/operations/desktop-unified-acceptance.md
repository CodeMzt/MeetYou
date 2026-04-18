# MeetYou V3 桌面一体化验收

## 1. 目标

本手册只覆盖当前已经落地的桌面端主链：

- Electron UI 负责交互
- Electron main 负责托管本地 desktop backend
- `desktop_agent` 同时承担本地能力、Core 连接与 UI 的 `/desktop/*` 后端

## 2. 推荐启动方式

```powershell
scripts\manual-acceptance.cmd start
```

默认顺序：

1. 启动 `service`
2. 启动 Electron UI
3. 由 Electron main 自动拉起 desktop backend

如果只想单独调 backend，可使用：

```powershell
scripts\manual-acceptance.cmd start -SkipUi
```

## 3. API / 状态检查

```powershell
scripts\manual-acceptance.cmd check
```

至少确认：

1. `/health` 正常
2. `/desktop/workspaces` 正常
3. `/operator/agents` 可看到在线 `desktop-agent`
4. 本地 backend `http://127.0.0.1:38951/desktop/status` 可访问

## 4. UI / 链路验收

进入桌面 UI 后，至少验证：

1. 聊天主窗口能建立连接并创建线程/会话
2. `desktop-agent` 已在线，且 capability 可被发现
3. 发送一条普通消息，确认 `/desktop/ws -> Core /client/ws` 实时链路正常
4. 上传一个小附件，确认 UI 只访问 `/desktop/attachments/*`，而不是 Core 附件路径
5. 打开 runtime debug / workspace / attachments / Danxi 子窗口，确认这些窗口仍可工作

## 5. 失败排查

- 如果 UI 打开但始终无法连接，先检查本地 backend 状态接口
- 如果 backend 存活但 Agent 不在线，检查 `desktop_agent` 到 Core 的 `/agent/ws` 握手
- 如果聊天或 Danxi 页失败，优先检查本地 `/desktop/*` API 是否通、以及 backend 到 Core 的 client surface 是否正常
