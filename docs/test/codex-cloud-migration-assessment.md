# MeetYou -> Codex 云端模式迁移确认

## 1. 结论

本项目不能把“当前整条桌面验收链路”原样迁到 Codex 云端。

可以迁到 Codex 云端的是：

- Core Service 相关开发与测试
- `client/ws` / `agent/ws` 协议面开发与回归
- `desktop_agent` 中不依赖本机 Windows 桌面能力的逻辑测试
- `meetyou-ui/` 的 `npm run typecheck`、`npm run test`
- 文档、配置、协议、后端逻辑、前端非 GUI 代码修改

不能直接迁到 Codex 云端的是：

- Electron 多窗口真实 UI 验收
- `desktop-agent` 的本地 Windows 文件、Shell、UIAutomation、截图链路验收
- `scripts\Capture-Screen.ps1` 驱动的屏幕验收
- Windows 打包产物验证

原因不是仓库结构，而是 Codex 云端任务运行在隔离容器里，不会继承当前这台 Windows 机器的桌面会话、本地回环服务或本地文件系统。

## 2. OpenAI 官方约束

参考：

- [Cloud environments](https://developers.openai.com/codex/cloud/environments)
- [Agent internet access](https://developers.openai.com/codex/cloud/internet-access)

官方确认的关键点：

- Codex 云端任务会创建容器，并把 Git 仓库 checkout 到选定分支或 commit。
- Setup script 在 agent phase 之前运行，并且 setup script 阶段默认有网络。
- Agent phase 默认关闭外网，需要按 environment 单独开启。
- Environment variables 会持续到整个任务；Secrets 只在 setup script 阶段可用，进入 agent phase 前会被移除。
- 云端环境默认是 Linux 容器，支持 Bash setup script。

对本项目的直接影响：

- 不能指望云端任务访问当前本机 `http://127.0.0.1:38951`
- 不能指望云端任务操作当前 Windows 的 Electron 窗口
- 不能把只存在于 setup script 的密钥，拿来做 agent 阶段的运行态调用

## 3. 仓库能力边界

仓库当前边界已经很清楚：

- Core Service 是服务端主链，适合 Linux / 云端运行
- `desktop-agent` 是用户设备侧本地后端，承接本地文件、Shell、本地 MCP 与桌面能力
- `meetyou-ui/` 是 Electron 桌面端，不是服务器侧主链

对应文件：

- [AGENTS.md](/E:/Documents/Project/MeetYou/AGENTS.md)
- [README.md](/E:/Documents/Project/MeetYou/README.md)
- [architecture-baseline.md](/E:/Documents/Project/MeetYou/docs/v3/design/architecture-baseline.md)
- [deployment-and-platform.md](/E:/Documents/Project/MeetYou/docs/v3/design/deployment-and-platform.md)

## 4. 云端必须具备的能力

### 4.1 运行时与工具链

最低要求：

- Python `3.10+`
- Node.js `18+`
- `npm`
- `git`
- `bash`

仓库依据：

- [requirements-core.txt](/E:/Documents/Project/MeetYou/requirements-core.txt)
- [requirements-desktop-agent.txt](/E:/Documents/Project/MeetYou/requirements-desktop-agent.txt)
- [meetyou-ui/package.json](/E:/Documents/Project/MeetYou/meetyou-ui/package.json)

### 4.2 Python 依赖

云端做 Core 开发至少要安装：

- `pip install -r requirements-core.txt`

如果还要做前端：

- `cd meetyou-ui && npm ci`

如果要做 `desktop_agent` 纯逻辑测试：

- `pip install -r requirements-desktop-agent.txt`

注意：

- `requirements-desktop-agent.txt` 里的 `pywin32`、`uiautomation` 已经通过平台 marker 限定到 Windows；Linux 云容器不会装这些包，也不具备这些能力。

### 4.3 数据库

这是当前云端迁移的硬依赖，不是可选项。

原因：

- Core 正式持久化已经切到 PostgreSQL
- service 启动会跑 Alembic migration
- 大量后端测试直接假定本地 PostgreSQL 在 `127.0.0.1:5432`

涉及文件：

- [core/db/engine.py](/E:/Documents/Project/MeetYou/core/db/engine.py)
- [tests/test_gateway_surface_routes.py](/E:/Documents/Project/MeetYou/tests/test_gateway_surface_routes.py)
- [tests/test_agent_release_compatibility.py](/E:/Documents/Project/MeetYou/tests/test_agent_release_compatibility.py)
- [tests/test_attachment_service.py](/E:/Documents/Project/MeetYou/tests/test_attachment_service.py)

因此在 Codex 云端至少要满足二选一：

1. 云容器内自带并启动 PostgreSQL
2. 提供一个从云容器可达的 PostgreSQL，并相应调整测试/验证策略

如果不提供 PostgreSQL，云端最多只能做不触库的静态检查、部分单测和代码修改。

### 4.4 密钥与环境变量

云端最少需要确认这些运行态变量：

- `MEETYOU_DATABASE_URL`
- `MEETYOU_GATEWAY_ACCESS_TOKEN`：如果要访问受保护的 HTTP / WebSocket surface
- `MEETYOU_API_KEY`：如果要跑真实消息链路

按测试范围可能还需要：

- `MEETYOU_HEARTBEAT_API_KEY`
- `MEETYOU_EMBEDDING_API_KEY`
- `MEETYOU_AGENT_WS_ACCESS_TOKEN` 或 `MEETYOU_AGENT_ACCESS_TOKEN`
- `MEETYOU_CREDENTIAL_SECRET`

注意：

- 按 Codex 官方规则，Secrets 只在 setup script 有效；真正 agent phase 还要用的配置，必须放 Environment variables，而不是只放 Secrets。

### 4.5 外网访问

默认 setup script 有外网，agent phase 默认没有。

对本项目的推荐：

- setup script：允许依赖安装
- agent phase：默认 `Off`
- 只有在确实需要联网测试时再开启，并优先使用 allowlist

最低常见 allowlist：

- `github.com`
- `githubusercontent.com`
- `pypi.org`
- `pypa.io`
- `pythonhosted.org`
- `npmjs.com`
- `npmjs.org`
- `nodejs.org`

如果云端任务要直接连你的线上 Core，还要加：

- 你的 Core 域名

如果要测 Danxi，再按实际链路追加：

- `forum.fduhole.com`
- `auth.fduhole.com`
- 对应 WebVPN 域名

## 5. 云端无法直接覆盖的部分

### 5.1 Desktop Agent 本地能力

`desktop-agent` 的职责本来就在“用户设备侧”：

- 本地文件
- 本地 Shell
- 本地 MCP
- 桌面能力

对应实现：

- [desktop_agent/desktop_api.py](/E:/Documents/Project/MeetYou/desktop_agent/desktop_api.py)
- [desktop_agent/runtime.py](/E:/Documents/Project/MeetYou/desktop_agent/runtime.py)
- [desktop_agent/execution.py](/E:/Documents/Project/MeetYou/desktop_agent/execution.py)

这些能力如果迁到 Codex 云端容器，语义会变成“容器内 Linux 文件/Shell”，不再是“用户 Windows 本机文件/Shell”。这会直接改变产品边界，不能把它当成同一种验收。

### 5.2 Electron UI 真机验收

当前桌面产品是：

- Electron main process
- renderer
- 本地 `desktop_agent` backend

对应入口：

- [meetyou-ui/electron/main.ts](/E:/Documents/Project/MeetYou/meetyou-ui/electron/main.ts)
- [meetyou-ui/src/main.tsx](/E:/Documents/Project/MeetYou/meetyou-ui/src/main.tsx)

Codex 云端可以改这些文件，也可以跑前端类型检查和单测，但不能替代：

- Windows 实机 Electron 多窗口行为
- 窗口层级/吸附/透明窗口行为
- 屏幕截图验收
- 真实鼠标交互体感验收

### 5.3 Windows 专属脚本

这些都不属于云端主链：

- [scripts/manual-acceptance.cmd](/E:/Documents/Project/MeetYou/scripts/manual-acceptance.cmd)
- `Capture-Screen.ps1`
- PowerShell / `.cmd` 拉起流程

它们仍然适用于本地 Windows 验收，不适合直接搬进 Codex 云端容器。

## 6. 适合的迁移拆分

推荐拆成两个执行面：

### A. Codex 云端面

负责：

- Core Service 代码修改
- 协议层、路由层、状态层、文档层开发
- 后端单测
- 前端 `typecheck` / `vitest`
- 不依赖 Windows 桌面的逻辑测试

### B. 本地 Windows 面

负责：

- Electron UI 真实功能验收
- `desktop-agent` 本机文件/Shell/MCP/桌面能力验收
- `Capture-Screen.ps1` 截图验收
- Windows 打包产物验收

这是当前仓库边界下唯一稳定的拆法。

## 7. 当前结论对应的配置建议

如果你现在就要迁到 Codex 云端做本轮开发，建议把目标限定为：

1. 云端只承担 Core + 非 GUI 前端开发
2. 真实桌面验收继续留在本地 Windows
3. 云端 environment 里补齐 Python、Node、npm、git、bash、PostgreSQL 与必要环境变量
4. 把 agent phase 外网默认关掉，需要时按 allowlist 精准放行

不建议现在做的事：

1. 试图把 `desktop-agent` 的“本机文件/Shell”验收直接改成云容器验收
2. 试图把 Electron 实机 UI 验收完全迁到云端
3. 在没有 PostgreSQL 的情况下，声称 Core 云端测试链路已经完整

## 8. 仓库内辅助检查

已补充一个就绪检查脚本：

- [scripts/check_codex_cloud_readiness.py](/E:/Documents/Project/MeetYou/scripts/check_codex_cloud_readiness.py)

用法：

```bash
python scripts/check_codex_cloud_readiness.py
python scripts/check_codex_cloud_readiness.py --json
```

它会检查：

- Python / Node / npm / git / bash
- 关键仓库文件是否存在
- 当前平台是否具备 Windows 桌面能力
- `MEETYOU_DATABASE_URL` 等关键环境变量是否齐备
- `psql` / `tesseract` 等补充能力是否存在

## 9. 下一步

如果按上面的拆分推进，下一步应做两件事：

1. 为 Codex 云端 environment 写一份正式 setup script
2. 再决定是给云端补本地 PostgreSQL，还是改成连接外部 PostgreSQL

只有这两件事定下来，后面的云端开发链路才算真正可用。
