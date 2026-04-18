# MeetYou V3 架构基线

## 1. 目的

本文档收口当前仓库已经证实的运行边界，并把它作为 V3 的起点。V3 应该在这条基线上继续演进，而不是回退到已经淘汰的入口、协议或职责划分。

## 2. 当前已证实的运行形态

### 2.1 发布单元

- `Core Service`：运行在服务器侧，持有 Gateway、数据库 migration、会话与状态真相源
- `desktop-agent`：运行在用户设备侧，承接本地文件、Shell、本地 MCP 与桌面能力
- `edge-agent`：运行在远端节点侧，按 workspace 接入并承接该节点能力

这三个单元当前已经按独立依赖清单拆分：

- `requirements-core.txt`
- `requirements-desktop-agent.txt`
- `requirements-edge-agent.txt`

### 2.2 真实入口

开发态统一入口：

- `python main.py service`
- `python main.py cil`
- `python main.py desktop-agent`
- `python main.py edge-agent`
- `python main.py` / `python main.py launcher`

生产态可分离入口：

- `python -m service_runtime`
- `python -m desktop_agent`
- `python -m edge_agent`

### 2.3 正式连接口径

- 客户端实时入口：`GET /client/ws`
- Agent 实时入口：`WSS /agent/ws`
- Agent 协议：`meetyou.agent.v1`
- 根路径 `GET /ws` 仅保留兼容性错误，不再承载正式聊天流

### 2.4 当前边界约束

- 本地文件、Shell、本地 MCP 生命周期属于 Agent 边界，不要重新塞回 Core
- `desktop_agent/` 与 `edge_agent/` 统一走 `WSS /agent/ws`，差异主要体现在 `agent_type` 与 `transport_profile`
- 正式持久化已经切到 PostgreSQL，service 启动会执行 Alembic migration

### 2.5 当前已落地的桌面端收口

- `desktop_agent/` 现在除了 `WSS /agent/ws` runtime 外，还承载本地 Desktop UI backend
- Electron main process 会优先拉起本地 desktop backend；renderer 默认改连 loopback 地址 `http://127.0.0.1:38951`
- UI 不再直接调用 Core surface，而是改调本地 `/desktop/*` 与 `/desktop/ws` API
- Desktop backend 内部继续负责连接 Core 的 `client/* + GET /client/ws` 与 `WSS /agent/ws`
- 这次收口只改变桌面端内部拓扑，不改变 Core 的正式 surface 契约

## 3. V3 继续沿用的约束

V3 默认继续沿用以下约束：

- 不重新引入 `python main.py gateway` 或 launcher `start gateway`
- 不把 `/ws` 重新当成正式聊天路径
- 不把本地能力绕过 Agent dispatch 重新塞回 Core
- 不把 `user/*.json` 重新当成正式唯一真相源

## 4. 当前仓库已经具备的基础

- Core / Desktop Agent / Edge Agent 已有独立依赖清单与独立运行入口
- Core 官方 `Dockerfile` 与 `deploy/docker/compose.core-postgres.yml` 已提供最小容器化基线
- `deploy/systemd/` 与 `scripts/linux/` 已提供 Linux 部署模板
- `meetyou-ui/package.json` 已具备 Electron 构建脚本，桌面端可通过 `electron-builder` 打包
- `requirements-desktop-agent.txt` 已通过平台 marker 将 `pywin32`、`uiautomation` 限定在 Windows

## 5. 当前仓库尚未提供的能力

截至当前，仓库内仍未提供以下资产：

- `.github/workflows/*`
- Python 可执行文件打包脚本，例如 `PyInstaller` 方案

这意味着 V3 仍可继续推进自动化与打包方向，但不能把它们写成“已经存在的能力”。

## 6. V3 文档关系

- 本文档负责描述当前可依赖的架构事实
- 部署与跨平台设计见 `deployment-and-platform.md`
- 桌面一体化设计见 `desktop-unified-agent.md`
- Core 部署操作基线见 `../operations/core-deployment.md`
- QQBot / WeChatBot 接入设计见 `bot-integration.md`
- 执行顺序与 feature 拆分见 `../plan/implementation-plan.md`

## 7. 历史参考

V2 的详细设计、协议与迁移资料已移到 `docs/archive/v2/`。当 V3 需要追溯历史设计决策时，可按需查阅归档，而不是继续在归档文档上直接追加新计划。
