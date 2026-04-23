# MeetYou V3 桌面一体化验收

## 1. 目标

本手册只覆盖当前已经落地的桌面端主链：

- Electron UI 负责交互
- Electron main 负责托管本地 desktop backend
- `desktop_agent` 同时承担本地能力、Core 连接与 UI 的 `/desktop/*` 后端

## 2. 推荐启动方式

```powershell
scripts\manual-acceptance.cmd check -BaseUrl https://your-remote-core.example
```

对于当前桌面一体化与 Desktop API 收口任务，推荐优先直接连已经在运行中的远程 Core 做验收，而不是为了非 Core 改动额外在本机再拉一份 `service`。

远程 Core 验收时，默认顺序：

1. 远程 Core 已在目标环境中运行
2. 本机启动 Electron UI
3. 由 Electron main 自动拉起 desktop backend
4. renderer 创建 desktop session 后，再由 backend 启动 `/agent/ws` runtime

只有在仓库内做全链路本地联调时，才推荐使用：

```powershell
scripts\manual-acceptance.cmd start
```

该模式会尝试在本机拉起 `service`、Electron UI 与 desktop backend，主要用于开发联调，不是 Phase 2 非 Core 验收的默认前提。

如果只想单独调 backend，可使用：

```powershell
scripts\manual-acceptance.cmd start -SkipUi
```

## 3. API / 状态检查

```powershell
scripts\manual-acceptance.cmd check -BaseUrl https://your-remote-core.example
```

至少确认：

1. `/health` 正常
2. `/desktop/workspaces` 正常
3. 在 UI 尚未创建 desktop session 前，`/operator/agents` 不应提前出现在线 `desktop-agent`
4. 本地 backend `http://127.0.0.1:38951/desktop/status` 可访问
5. 进入主窗口完成 thread/session 初始化后，再确认 `/operator/agents` 可看到在线 `desktop-agent`

## 4. UI / 链路验收

进入桌面 UI 后，至少验证：

1. 聊天主窗口能建立连接并创建线程/会话
2. `desktop-agent` 会在 session 建立后上线，且 capability 可被发现
3. 桌面端连接注入消息只出现一次，不再因 session bootstrap 再重复一条
4. 发送一条普通消息，确认 renderer 只升级本地 `/desktop/ws`，再由 desktop backend 转接到 Core `GET /client/ws`
5. 关闭 Electron UI 后，本地 `desktop backend` 进程应随之退出，不继续残留监听 `38951`
6. 上传一个小附件，确认 upload ticket、上传、complete、列表与 proxy 下载都收口在 `/desktop/attachments/*`
7. 如 download ticket 返回对象存储 presigned URL，确认 renderer 只对该对象地址做浏览器直下；这属于附件内容直下例外，不应出现直连 Core 附件路径
8. 打开 runtime debug / workspace / attachments / Danxi 子窗口，确认这些窗口仍可工作
9. 如需检查 token 注入，renderer 只应持有本地 `local_bridge_access_token` 用于 `/desktop/*` 与 `/desktop/ws`，不应把 Core gateway token 暴露给 UI 请求链路

## 5. 失败排查

- 如果 UI 打开但始终无法连接，先检查本地 backend 状态接口
- 如果 backend 存活但 Agent 不在线，先确认是否已经创建 desktop session，再检查 `desktop_agent` 到 Core 的 `/agent/ws` 握手
- 如果关闭 UI 后 `38951` 仍被占用，检查 Electron `before-quit` 是否触发以及 backend 子进程是否已退出
- 如果当前是远程 Core 验收，优先确认 `-BaseUrl` 指向的是可访问的远程地址，而不是默认的本地 `http://127.0.0.1:8000`
- 如果聊天或 Danxi 页失败，优先检查本地 `/desktop/*` API 是否通、以及 backend 到 Core 的 client surface 是否正常

## 6. 非 Windows 说明

- 当前桌面主链的首选验收平台仍是 Windows
- 如果在 Linux / macOS 上拉起 `desktop-agent`，文件读写、Shell、workspace 分析仍应可用
- 但 `platform_layer` 的 UI 焦点/控件感知在 Linux / macOS 下属于显式禁用能力，不应把缺失 UI Automation 视为缺陷回归
- 因此非 Windows 验收重点应放在 `/desktop/*` API、`/agent/ws` 握手和本地文件/Shell capability，而不是 Windows 专属桌面感知
## Packaged Windows Acceptance Addendum

For F324, run `scripts\build-desktop-backend.ps1` before `cd meetyou-ui && npm run build`. The build script creates the PyInstaller one-dir backend under `meetyou-ui\resources\desktop-backend` and prepares `meetyou-ui\resources\runtime-template`; Electron Builder includes both as `extraResources` payloads.

Installed packaged mode should start the backend from `process.resourcesPath`, not from the source repository. On first run it copies the runtime template into `app.getPath('userData')\meetyou-runtime\user`; if an older packaged default still points at loopback Core while the bundled template points at a remote Core, Electron main migrates the Core URL forward. `MEETYOU_DESKTOP_AGENT_CONFIG` can override the config path for debugging.

Pass criteria: a Windows installer copied away from the repository can start the local `/desktop/status` backend, proxy `/desktop/health` to the configured remote Core, create a desktop session, and connect the packaged desktop agent to Core. macOS/Linux installers remain out of this acceptance scope.
