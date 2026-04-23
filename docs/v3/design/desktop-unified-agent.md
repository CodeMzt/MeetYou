# MeetYou V3 桌面一体化 Agent 设计

## 1. 目的

V3 要把当前桌面端收口成一个真正的一体化 Agent 产品：

- Electron UI 只负责交互与窗口
- `desktop_agent` 是 UI 的真正后端，负责连接 Core、维护本地状态、执行业务动作与本地能力

关键原则不是“让 UI 通过本地进程转发请求到 Core”，而是“让 UI 只面对本地 backend，自身不再感知 Core surface”。

## 2. 当前问题

旧方案的问题不在于是否使用 loopback，而在于职责模型仍是错误的：

1. UI 原先面向 Core 的 `client/*`、`operator/*`、`runtime/*`、`developer/*`
2. `desktop_agent` 独立通过 `WSS /agent/ws` 工作，只承接 capability
3. 如果本地后端只是透明转发 UI 请求，它仍然只是 Core 的跳板，而不是 UI 的真正后端

这种结构会导致：

- UI 仍然依赖 Core 的正式协议面与路径命名
- 前端边界难以稳定，Core surface 一变前端就必须跟着变
- 桌面端无法自然承接本地缓存、离线、状态聚合和本地容错
- 桌面产品内部边界不清晰，仍然像“两套客户端并行挂在 Core 上”

## 3. 目标架构

```text
Electron Renderer
        |
        | HTTP / WS (loopback, /desktop/*)
        v
Desktop Backend (`desktop_agent`)
  |- Desktop API (/desktop/*, /desktop/ws)
  |- Core Client (内部调用 client/*, operator/*, runtime/*, developer/*, /client/ws)
  |- Agent Runtime (/agent/ws)
  |- Local File / Shell / MCP / Attachments
        |
        v
Core Service
```

### 3.1 职责划分

UI 只负责：

- 聊天、审批、窗口状态、配置页面与 Danxi 页面交互
- 调用本地 `desktop_agent` 暴露的 `/desktop/*` API
- 不直接访问 Core 的 `client/*`、`operator/*`、`runtime/*`、`developer/*` 或 `GET /client/ws`

Electron main process 负责：

- 启动与托管桌面后端进程
- 管理窗口、Danxi 认证窗口和最小 IPC
- 向 renderer 注入本地 backend 地址与本地访问令牌

`desktop_agent` 负责：

- 通过 `WSS /agent/ws` 接入 Core，承接本地 capability
- 通过内部 Core client 访问 Core 的 client/operator/runtime/developer surface
- 对 UI 暴露自己的 `/desktop/*` API 与 `/desktop/ws`
- 统一管理 Core token、本地 token、连接状态、附件上传下载与本地依赖性操作

桌面端真实启动顺序按以下口径收口：

1. Electron main 启动本地 desktop backend 进程
2. renderer 创建本地 desktop session（`POST /desktop/sessions`）
3. desktop backend 在 session 建立后再启动 `/agent/ws` runtime
4. `agent_connected` 注入只保留一次，不再在 session bootstrap 阶段重复回放第二条提示

## 4. 对外契约与对内契约

### 4.1 Core 正式契约保持不变

- Client 实时入口仍是 `GET /client/ws`
- Agent 实时入口仍是 `WSS /agent/ws`
- 根路径 `GET /ws` 仍不恢复为正式聊天入口
- 本地文件、Shell、本地 MCP 仍留在 Agent 边界

### 4.2 Desktop Backend 对 UI 暴露新契约

桌面 UI 不再调用 Core 路径，而是调用本地 backend 的：

- `/desktop/health`
- `/desktop/workspaces`
- `/desktop/threads`
- `/desktop/sessions`
- `/desktop/messages`
- `/desktop/operations`
- `/desktop/procedures`
- `/desktop/attachments/*`
- `/desktop/danxi/*`
- `/desktop/config*`
- `/desktop/memory*`
- `/desktop/runtime/*`
- `/desktop/ws`

这层 API 是桌面产品自己的契约，而不是 Core 路径的前端直接暴露。

## 5. 本地 Desktop API 设计

### 5.1 本地地址

- 默认 loopback 地址：`http://127.0.0.1:38951`
- Electron UI 默认改连这个本地地址
- 本地 backend 只绑定 loopback，不作为公网入口

### 5.2 API 前缀

- 健康与状态：`/desktop/status`、`/desktop/health`
- 实时消息：`/desktop/ws`
- 其余 UI 动作都归到 `/desktop/*`

renderer 侧实时流契约进一步固定为：

- 只升级本地 desktop backend 的 `ws://127.0.0.1:38951/desktop/ws?thread_id=...`
- 如需鉴权，只携带本地 `local_bridge_access_token`
- Desktop backend 在内部再转接到 Core 的 `GET /client/ws`，renderer 不直接感知 Core WebSocket 地址或 Core token

### 5.3 附件链路

桌面 UI 不再使用 Core 附件 URL。

Desktop backend 负责：

- 把 Core 的 upload ticket 转换为本地 `/desktop/attachments/upload/{ticket_id}`
- 把 Core 的 proxy download URL 转换为本地 `/desktop/attachments/content/{attachment_id}`
- 保留对象存储 presigned URL 这类真正应该让浏览器直下的地址

因此附件口径固定为：

- upload ticket 与 complete/删除/列表等控制面 API 始终走 `/desktop/attachments/*`
- 需要 backend 代管鉴权或代理下载时，renderer 只访问本地 `/desktop/attachments/content/{attachment_id}`
- 只有 download ticket 明确返回对象存储 presigned URL 时，renderer 才允许直接请求该对象地址；这属于附件内容直下例外，不代表 UI 恢复直连 Core

### 5.4 鉴权边界

- UI -> Desktop Backend：`local_bridge_access_token`
- Desktop Backend -> Core `/agent/ws`：`agent_access_token`
- Desktop Backend -> Core client/operator/runtime/developer surface：`gateway_access_token`

renderer 不再需要知道 Core Gateway token。

## 6. 迁移原则

### 6.1 不做透明反向代理

桌面后端不能再暴露“所有路径原样转发”的 catch-all 代理；否则 UI 仍然等价于在直接调用 Core。

### 6.2 先收口 UI 契约，再决定内部实现细节

第一阶段优先把 UI 契约收口到 `/desktop/*`。Desktop backend 内部可以逐步把逻辑从“显式调用 Core endpoint”继续演进到“更强的本地状态编排与缓存”。

### 6.3 保留 standalone backend 调试能力

`python -m desktop_agent` 仍保留，方便 backend-only 调试、验证和发布。但默认桌面产品链路应由 Electron 托管它，而不是要求用户手动双开。

### 6.4 避免重复连接注入

旧方案会在 agent 实际连接时注入一次 `agent_connected`，又在 client session bootstrap 时回放一次在线 agent，最终让 UI 收到两条近似的连接提示。

当前桌面端口径要求：

- agent runtime 延后到 desktop session 建立后启动
- client session bootstrap 不再重放第二次 `agent_connected` 注入
- UI 只看到一条一体化桌面端接入提示

## 7. 验收要求

桌面一体化改动至少要确认：

1. renderer 默认地址指向本地 desktop backend，而不是 Core
2. Electron 启动后会优先托管 desktop backend
3. `desktop_agent` 仍能完成 `agent.hello -> agent.ready`
4. UI 所有网络出口都落在 `/desktop/*` 和 `/desktop/ws`，而不是 Core surface
5. Desktop backend 到 Core 的连接由 backend 自己持有和管理
6. `scripts/manual-acceptance.cmd start` 的桌面链路口径与文档一致

## 8. 关联文档

- 当前架构事实：`architecture-baseline.md`
- 部署与打包约束：`deployment-and-platform.md`
- 实施顺序：`../plan/implementation-plan.md`
