# MeetYou V3 桌面一体化 Agent 设计

## 1. 目的

V3 需要把当前“Desktop UI 直连 Core、desktop-agent 独立连 Core”的并行结构，收口成一个真正的桌面 Agent 产品：

- Electron UI 负责交互、窗口与用户输入
- `desktop_agent` 负责本地能力、与 Core 的握手通信，以及 UI 到 Core 的本地代理

目标不是把本地能力塞回 Core，而是把桌面端前后端合并成一个清晰的本地运行时。

## 2. 当前问题

当前仓库里已经存在三条独立链路：

1. UI 直接调用 `client/*` 和 `GET /client/ws`
2. `desktop-agent` 独立通过 `WSS /agent/ws` 握手、上报能力与执行 capability
3. Electron main process 只负责窗口与少量 IPC，不负责桌面后端生命周期

这个结构会带来几类问题：

- 桌面端对 Core 暴露了两套并行连接面，边界难以解释
- renderer 直接持有服务地址与访问令牌，安全边界过薄
- 附件、Danxi、workspace、operator/debug 等窗口能力都能绕过本地后端
- 桌面端验收、启动与打包时，UI 和 `desktop-agent` 的归属关系不清晰

## 3. 目标架构

```text
Electron Renderer
        |
        | HTTP / WS (loopback)
        v
Desktop Backend (`desktop_agent`)
  |- Local UI Bridge
  |- Agent Runtime (/agent/ws)
  |- Local File / Shell / MCP / Attachments
        |
        | HTTP client + client/ws + agent/ws
        v
Core Service
```

### 3.1 职责划分

UI 只负责：

- 聊天、审批、过程反馈、窗口状态与页面交互
- 通过本地 bridge 调用桌面后端
- 不再直接访问 Core 的 `client/*`、`operator/*`、`developer/*` 或 `GET /client/ws`

Electron main process 负责：

- 启动与托管桌面后端进程
- 管理窗口、Danxi 认证窗口和少量本地 IPC
- 向 renderer 提供本地 bridge 所需的最小运行时信息

`desktop_agent` 负责：

- 通过 `WSS /agent/ws` 接入 Core，承接本地 capability
- 通过 loopback bridge 代理 UI 所需的 HTTP / WS 调用
- 统一处理 Core 访问令牌、附件 ticket URL 重写、重连和本地依赖性操作

## 4. 本次收口保留的外部契约

这次桌面一体化不先改 Core 的正式协议面：

- Client 实时入口仍是 `GET /client/ws`
- Agent 实时入口仍是 `WSS /agent/ws`
- 根路径 `GET /ws` 仍不恢复为正式聊天入口
- 本地文件、Shell、本地 MCP 仍留在 Agent 边界

变化发生在桌面端内部：renderer 不再直接命中这些 Core surface，而是改经本地 backend。

## 5. 本地 bridge 设计

### 5.1 本地地址

- 默认 loopback 地址：`http://127.0.0.1:38951`
- Electron UI 默认改连这个本地地址
- 本地 bridge 对外只绑定 loopback，不作为公网入口

### 5.2 代理范围

本地 bridge 至少需要覆盖：

- `/health`
- `/client/*`
- `/operator/*`
- `/developer/*`
- `/runtime/*`
- `GET /client/ws`

### 5.3 附件链路

附件不能只做透明转发；否则 upload/download ticket 仍会把 renderer 直接带回 Core。

因此 bridge 必须：

- 重写 `client/attachments/upload-ticket` 返回的 `upload_url`
- 重写 `client/attachments/*/download-ticket` 中指向 Core 的 proxy URL
- 保留对象存储 presigned URL 这类非 Core 直连地址

### 5.4 鉴权边界

- renderer 到本地 bridge 的访问令牌由 Electron main 管理
- bridge 到 Core 的访问令牌由 `desktop_agent` 持有并注入
- renderer 不再需要知道 Core Gateway token

## 6. 迁移原则

### 6.1 不做半收口

只改聊天主链而保留大量 operator/debug/Danxi 直连，会继续留下双路访问问题。

因此桌面一体化要按“全部 renderer 出口统一走本地 backend”推进，而不是只改一两个 hook。

### 6.2 先改桌面内部，不先改 Core 正式 surface

桌面产品内聚化是当前目标；Core 的 `client/*` 与 `/agent/ws` 正式面继续保留，避免把大改扩散到服务端协议。

### 6.3 保留 standalone backend 调试能力

`python -m desktop_agent` 仍保留，方便 backend-only 调试、验证和发布。但默认桌面产品链路应由 Electron 托管它，而不是要求用户手动双开。

## 7. 验收要求

桌面一体化改动至少要确认：

1. renderer 默认地址已改成本地 bridge，而不是 Core `127.0.0.1:8000`
2. Electron 启动后会优先托管 desktop backend
3. `desktop_agent` 仍能完成 `agent.hello -> agent.ready`
4. UI 的 HTTP / WS、附件 ticket、Danxi 与 operator/debug 窗口不再直连 Core
5. `scripts/manual-acceptance.cmd start` 的桌面链路口径与文档一致

## 8. 关联文档

- 当前架构事实：`architecture-baseline.md`
- 部署与打包约束：`deployment-and-platform.md`
- 实施顺序：`../plan/implementation-plan.md`
