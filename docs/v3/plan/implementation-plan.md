# MeetYou V3 Implementation Plan

## 1. 目的

本文档是 MeetYou V3 的统一实施计划书，服务于后续设计、编码、验证与阶段验收。

本文档延续 V2 已验证的 `Phase -> Feature -> Task` 组织方式，但不再继续把 V2 的特性清单直接追加到旧文档里。

## 2. 当前真源文档

V3 默认以以下文档为真源：

- `docs/v3/design/architecture-baseline.md`
- `docs/v3/design/deployment-and-platform.md`
- `docs/v3/design/bot-integration.md`

历史设计与迁移资料统一转入 `docs/archive/v2/`，仅作参考输入。

## 3. V3 总体目标

V3 的目标聚焦三条主线：

1. 把桌面端收口为 Electron UI + desktop backend 一体化产品
2. 简化部署与跨平台支持
3. 基于既有 QQBot / WeChatBot 方案落地新的外部客户端接入
4. 提升性能、自动化验证、可维护性与可观测性

V3 默认继续沿用当前仓库已经稳定的运行边界：

- Core 在服务器侧
- Desktop Backend / Edge Agent 在用户设备或边缘节点侧
- Desktop UI 默认通过本地 `/desktop/*` API 与 Desktop Backend 交互，不再直连 Core
- Client 正式面仍是 `client/* + GET /client/ws`
- Agent 走 `WSS /agent/ws`

## 4. 执行原则

- 先收口文档真源，再推进代码迭代
- 先复用已存在的稳定边界，再扩功能
- 优先做最小可验证闭环，不把计划写成无法落地的大而全清单
- 文档中的“已完成”只用于标记仓库中已经落地的内容

## 5. Phase 视图

```text
Phase 0  文档归档与 V3 基线建立
Phase 1  部署简化与容器化基线
Phase 2  桌面端一体化与 Desktop API 收口
Phase 3  QQBot / WeChatBot 接入
Phase 4  性能与可维护性优化
Phase 5  自动化测试、CI/CD 与可观测性
```

## 6. Feature 清单

### Phase 0

- `F300` V2 文档归档与 V3 文档入口建立。范围：`docs/`、`README.md`、`AGENTS.md`。状态：已完成。
- `F301` V3 设计/计划真源建立。范围：`docs/v3/`。状态：已完成。

### Phase 1

- `F310` Core 容器化基线。范围：新增 Core Service 官方 `Dockerfile`、基础运行说明与环境变量约定。边界：容器资产、`README.md`、`docs/v3/`。状态：已完成。
- `F311` Core + PostgreSQL 个人部署编排模板。范围：新增最小编排模板与数据卷、密钥注入说明。边界：部署资产、`README.md`、`docs/v3/`。状态：已完成。
- `F312` Linux 主机部署模板继续收口。范围：基于现有 `deploy/systemd/` 与 `scripts/linux/` 统一 systemd 口径、升级路径与验收说明。边界：`deploy/systemd/`、`scripts/linux/`、`README.md`、`docs/v3/`。状态：已完成。

### Phase 2

- `F320` Desktop Backend API。范围：让 `desktop_agent` 对 UI 暴露显式 `/desktop/*` 与 `/desktop/ws` API，而不是通配式 Core 代理。边界：`desktop_agent/`、相关测试与文档。状态：进行中。
- `F321` Electron 托管桌面后端。范围：由 Electron main 负责拉起、监控与关闭 desktop backend，并把本地 backend 地址与令牌注入 renderer；desktop runtime 在本地 session 建立后启动，避免重复连接注入。边界：`meetyou-ui/electron/`、`meetyou-ui/src/`、`desktop_agent/`。状态：进行中。
- `F322` UI 直连 Core 收口。范围：把 renderer 的 `client/*`、`operator/*`、`developer/*`、`runtime/*` 与 `GET /client/ws` 访问统一改成桌面 backend 自己的 `/desktop/*` 和 `/desktop/ws` 契约。边界：`meetyou-ui/src/`、`desktop_agent/`、相关测试。状态：进行中。
- `F323` Desktop 平台能力与非 Windows 语义收口。范围：继续显式化 Windows 专属 capability、Linux / macOS 下的降级与禁用语义。边界：`desktop_agent/`、`platform_layer/`、文档与测试。状态：计划中。
- `F324` Desktop Product 打包策略设计。范围：明确桌面产品内 UI + backend 的便携打包或安装路径，同时保持 Core / Edge 独立发布。边界：发布文档、构建脚本、`docs/v3/`。状态：计划中。
- `F325` Danxi WebVPN fallback 收口。范围：沿用现有 Danxi 直连 + WebVPN 方案，在不引入新的通用代理配置面的前提下，让 Danxi 会话在直连不可用或直连请求失败时自动切到已有 WebVPN 登录态；同步收口 Danxi 状态返回口径、最小相关测试与计划文档。边界：`tools/danxi_tools.py`、Danxi 相关测试、`docs/v3/`。状态：已完成。

### Phase 3

- `F330` QQBot / WeChatBot transport 接入骨架。范围：新增平台 transport client 或 webhook 适配入口。边界：`adapters/`、`sensors/`。状态：计划中。
- `F331` Bot -> Client 主链桥接。范围：复用或扩展 `clients/gateway_client.py`，让新 Bot 通过正式 Client API 与 `/client/ws` 接入。边界：`clients/`、`sensors/`、Gateway 相关测试。状态：计划中。
- `F332` Bot 交互语义补齐。范围：confirm、human input、附件与低风险用户操作的正式桥接。边界：`sensors/`、`clients/`、相关测试与文档。状态：计划中。

### Phase 4

- `F340` 高负载模块边界审视。范围：梳理 gateway、task scheduler、memory search 等潜在瓶颈的拆分接口。边界：`core/`、`gateway/`、设计文档。状态：计划中。
- `F341` 长耗时任务异步化设计。范围：为长耗时任务预留队列化或异步化接口，不破坏当前单体主链。边界：`core/`、`gateway/`、设计文档。状态：计划中。
- `F342` 运行诊断与日志收口。范围：统一 Core / Agent 侧排障信息的最小可观测基线。边界：后端、Agent、文档。状态：计划中。

### Phase 5

- `F350` 自动化测试矩阵扩展。范围：补齐部署、握手、能力调用、数据库 migration 与 Bot 接入的最小回归覆盖。边界：`tests/`、必要的前端测试。状态：计划中。
- `F351` CI/CD 基线。范围：引入自动化测试与构建工作流，覆盖至少一个 Linux 路径；如果后续扩平台，再扩展矩阵。边界：CI 资产、文档。状态：计划中。
- `F352` 监控与指标基线。范围：建立 `/health`、数据库连通性、Agent 在线状态等指标与日志收集的文档和实现入口。边界：后端、运维资产、文档。状态：计划中。

## 7. 默认推进顺序

当前默认推进顺序：

1. 完成 Phase 0 的文档真源收口
2. 补齐 Phase 1 的部署简化基线
3. 优先推进 Phase 2 的桌面端一体化与 Desktop API 收口
4. 以 Feishu 适配模式为参照推进 Phase 3 的 Bot 接入
5. 在桌面主链与核心接入路径明确后，再推进 Phase 4、Phase 5 的系统性收口

若当轮需求有明确优先级，以用户目标优先。

## 8. Phase 4 完成记录

### 8.1 目标

- 统一 Core / Agent 侧最小诊断字段，让 runtime health、telemetry、background status 与结构化日志能落在同一套排障口径上
- 为 scheduler 与 memory search 抽出明确边界接口，避免 Phase 4 继续把行为、状态和调度细节堆回单一函数
- 为后续长耗时任务异步化预留可复用的 dispatch plan，而不改变当前单体主链、正式协议和运行顺序

### 8.2 已落地范围

本轮已按 `F342 -> F340 -> F341` 顺序完成以下收口：

- `F342`
  - `ServiceRuntime health`、`background_status` 与 `gateway delivery telemetry` 共享诊断来源字段
  - `StructuredFormatter` 兼容既有 `structured_data` 与遗留 `context` 扩展字段
  - Agent runtime、Desktop Agent MCP 初始化失败、Heart 关键失败路径都补入结构化日志
- `F340`
  - 新增 `core/scheduled_task_dispatch.py`，把 scheduled task 的 control event / operation 元数据边界显式化
  - 新增 `tools/memory_search.py`，把 memory search 的 query / structured recall 边界从 tool formatting 中拆出
- `F341`
  - scheduler 改用 `ScheduledTaskDispatchPlan` 生成 control event 和 operation metadata
  - 预留 `dispatch_mode=inline_control_event` 与 `dispatch_queue=scheduled_task_controls`，后续可平滑切换到 queue/job，而当前仍走 event bus 主链

### 8.3 逐文件改动清单

- `docs/v3/design/runtime-diagnostics-and-performance.md`
  - 记录 Phase 4 的热点路径、执行顺序、边界约束与已落地结果
- `docs/v3/plan/implementation-plan.md`
  - 将 `F340` / `F341` / `F342` 状态收口为已完成
  - 把 Phase 4 的实际落地范围、代码边界与验证矩阵写回真源计划
- `core/scheduled_task_dispatch.py`
  - 抽出 scheduled task / reminder 的 dispatch plan 与 operation metadata 边界
- `tools/memory_search.py`
  - 抽出 memory search query 与 structured recall service
- `core/background_status.py`
  - 在系统问题快照中保留 `background_status_sources` 与 `job_failure_count`
- `core/logger.py`
  - 统一结构化日志字段解析，兼容遗留 `context` 扩展字段
- `service_runtime/telemetry.py`
  - 为 gateway delivery 失败保留 metadata 中的关联上下文字段
- `service_runtime/service.py`
  - 在 health metrics / checks 中保留背景状态来源数量与 job failure 计数
- `agent_sdk/runtime.py`
  - 为 handshake、capability call、call failure / completion 增补结构化日志字段
- `desktop_agent/runtime.py`
  - 为 MCP 初始化失败补充结构化日志
- `edge_agent/runtime.py`
  - 为 runtime 连接失败补充结构化日志
- `core/heart.py`
  - 使用 dispatch plan 驱动 scheduled control event 与 operation 预创建
  - 在 scheduler / heartbeat 失败路径上补充结构化日志
- `core/app.py`
  - 复用 dispatch plan 创建 / 复用 scheduled operation，并统一 agent-connected 结构化日志字段
- `tools/agent_memory.py`
  - 接入 `MemorySearchService`，让 memory search tool 面与 retrieval service 面分离
- `tests/test_service_runtime.py`
  - 增补结构化日志兼容、诊断字段和 gateway delivery 关联上下文断言
- `tests/test_heart_scheduler.py`
  - 验证 scheduler control event 与 operation metadata 带有 dispatch reservation 字段
- `tests/test_scheduled_control_flow.py`
  - 验证 App 侧 scheduled operation 复用新的 dispatch metadata
- `tests/test_scheduled_task_dispatch.py`
  - 验证 dispatch plan 与 operation metadata 边界
- `tests/test_memory_search_service.py`
  - 验证 memory search service 的 structured recall 边界

### 8.4 完成判定

本轮完成后，Phase 4 视为已收口，因为：

1. 诊断字段已覆盖 Core runtime、gateway delivery、Heart、Agent runtime 关键失败路径
2. scheduler 与 memory search 已有明确的边界模块，不再只依赖内联实现细节
3. 长耗时任务异步化已具备可复用的 dispatch reservation 字段，后续可在不改协议的前提下继续演进

### 8.5 验证矩阵

- `tests/test_service_runtime.py`
- `tests/test_runtime_ws.py`
- `tests/test_heartbeat_guardrails.py`
- `tests/test_task_scheduler.py`
- `tests/test_heart_scheduler.py`
- `tests/test_brain_memory_prefetch.py`
- `tests/test_scheduled_control_flow.py`
- `tests/test_edge_agent_runtime.py`
- `tests/test_desktop_agent_runtime.py`
- `tests/test_scheduled_task_dispatch.py`
- `tests/test_memory_search_service.py`

## 9. Danxi WebVPN Fallback 收口记录

### 9.1 目标

- 保持当前 Danxi 仍以 Core 侧 `DanxiTools` 为唯一真实会话源，不把 Danxi 登录态拆到 Desktop Agent 或 renderer
- 不新增 STUVPN / 通用代理配置面，继续沿用当前仓库已落地的 WebVPN 登录窗 + cookie 路由方案
- 当 Danxi 直连不可用，或某次 Danxi 直连请求发生网络级失败时，如果当前会话已经具备可用的 WebVPN cookie，则自动切到 WebVPN 路由

### 9.2 已落地范围

- `tools/danxi_tools.py`
  - 扩大 WebVPN 路由启用条件：已有 WebVPN cookie 且直连不可用时，不再要求显式 `use_webvpn=True` 才能走代理
  - 增加 Danxi 直连请求失败后的自动 WebVPN 重试逻辑，避免已有 WebVPN 登录态时仍直接报错退出
  - 收口 Danxi 会话状态口径，让 `transport`、`webvpn_enabled` 与 `webvpn_required` 能反映“已有 WebVPN fallback 可用”的事实
  - 当远端 Core 检测到浏览器提交的 WebVPN cookie 无法跨机复用时，允许使用服务端 `STUVPN_FUDAN_USER` / `STUVPN_FUDAN_PASSWORD` 重建 WebVPN 会话并重试
  - Danxi 主登录默认优先读取服务端 `DANXI_MAIL` / `DANXI_PASSWORD`；桌面端手动输入邮箱密码只保留为备用覆盖路径
- `gateway/routes/client.py`
  - `POST /client/danxi/session/login` 允许在不下发 `encrypted_credentials` 时走远端 Core 环境变量主登录，同时继续拒绝明文邮箱、密码与 cookie 跨边界提交
- `meetyou-ui/electron/main.ts`
  - 收紧 WebVPN cookie 捕获时机：只有认证窗真正回到 `webvpn.fudan.edu.cn` 的非登录页后，才把 cookie 回传给 Danxi，避免在 CAS/预登录阶段过早关闭窗口并注入无效 cookie
  - 为 WebVPN 认证窗补充独立 session、Chrome UA 与加载失败日志，降低白屏/无响应时的排障成本
- `meetyou-ui/src/DanxiWindow.tsx`
  - 当桌面端尚未持有 Danxi 会话时，WebVPN 手动登录结果会优先触发一次新的 Core 侧登录，而不是强制要求先手填 Danxi 凭证
- `tests/test_danxi_tools.py`
  - 增补“直连不可用时自动走 WebVPN cookie”
  - 增补“直连请求失败后自动重试 WebVPN”
  - 增补“已有 WebVPN cookie 时会话状态反映 fallback 可用”

### 9.3 边界说明

- 本轮没有新增 Danxi/STUVPN 专用配置项，也没有把代理设置接入 `operator/config` / `/desktop/config`
- 本轮继续沿用 Electron WebVPN 登录窗、`/desktop/danxi/*` -> `/client/danxi/*` -> Core `DanxiTools` 的现有跨端链路
- Danxi 主登录环境变量以 `DANXI_MAIL` / `DANXI_PASSWORD` 为准；旧的 `MEETYOU_DANXI_EMAIL` / `MEETYOU_DANXI_PASSWORD` 仅保留兼容兜底
- 当 Danxi 挂在远端 Core 且浏览器 cookie 无法跨机复用时，服务端可通过 `STUVPN_FUDAN_USER` / `STUVPN_FUDAN_PASSWORD` 自建 WebVPN 会话；这两个环境变量因此成为 WebVPN 远端部署场景下的正式运行入口

### 9.4 验证矩阵

- `.venv\Scripts\python.exe -m unittest tests.test_danxi_tools`
- `.venv\Scripts\python.exe -m unittest tests.test_gateway_surface_routes`
- `cd meetyou-ui && npm run typecheck`
- `cd meetyou-ui && npm run test -- src/DanxiWindow.test.tsx`
- `cd meetyou-ui && npm run test -- src/clientApi.test.ts src/DanxiWindow.test.tsx`

## 10. 验证要求

- 文档改动若直接涉及部署主链、发布顺序或兼容窗口，至少跑 `tests/test_agent_release_compatibility.py`
- 后端实现类改动按最小相关 `unittest` 模块执行
- Frontend 改动先 `npm run typecheck`，再 `npm run test`
- 只有在实际改到 Electron/Vite/build 链路时才补 `npm run build`

## 11. 历史参考

V2 的实施细节、验收口径与迁移记录已归档到 `docs/archive/v2/`，包括：

- V2 计划书
- V2 运行迁移说明
- V2 人工启动验收手册
- 旧版协议与 API 设计文档

需要追溯历史决策时查阅归档；需要推进 V3 时更新本目录。
