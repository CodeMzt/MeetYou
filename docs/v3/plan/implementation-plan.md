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
- Desktop UI 默认经由本地 desktop bridge 访问 Desktop Backend，不再直连 Core
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
Phase 2  桌面端一体化与本地 bridge 收口
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

- `F320` Desktop Backend local bridge。范围：让 `desktop_agent` 同时承接 UI 到 Core 的 HTTP / WS 代理、附件 ticket URL 重写与 loopback bridge。边界：`desktop_agent/`、相关测试与文档。状态：进行中。
- `F321` Electron 托管桌面后端。范围：由 Electron main 负责拉起、监控与关闭 desktop backend，桌面 UI 默认改连本地 bridge。边界：`meetyou-ui/electron/`、`meetyou-ui/src/`、`desktop_agent/`。状态：进行中。
- `F322` UI 直连 Core 收口。范围：把 renderer 的 `client/*`、`operator/*`、`developer/*`、`runtime/*` 与 `GET /client/ws` 访问统一改经本地 backend。边界：`meetyou-ui/src/`、`desktop_agent/`、相关测试。状态：进行中。
- `F323` Desktop 平台能力与非 Windows 语义收口。范围：继续显式化 Windows 专属 capability、Linux / macOS 下的降级与禁用语义。边界：`desktop_agent/`、`platform_layer/`、文档与测试。状态：计划中。
- `F324` Desktop Product 打包策略设计。范围：明确桌面产品内 UI + backend 的便携打包或安装路径，同时保持 Core / Edge 独立发布。边界：发布文档、构建脚本、`docs/v3/`。状态：计划中。

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
3. 优先推进 Phase 2 的桌面端一体化与本地 bridge 收口
4. 以 Feishu 适配模式为参照推进 Phase 3 的 Bot 接入
5. 在桌面主链与核心接入路径明确后，再推进 Phase 4、Phase 5 的系统性收口

若当轮需求有明确优先级，以用户目标优先。

## 8. 验证要求

- 文档改动若直接涉及部署主链、发布顺序或兼容窗口，至少跑 `tests/test_agent_release_compatibility.py`
- 后端实现类改动按最小相关 `unittest` 模块执行
- Frontend 改动先 `npm run typecheck`，再 `npm run test`
- 只有在实际改到 Electron/Vite/build 链路时才补 `npm run build`

## 9. 历史参考

V2 的实施细节、验收口径与迁移记录已归档到 `docs/archive/v2/`，包括：

- V2 计划书
- V2 运行迁移说明
- V2 人工启动验收手册
- 旧版协议与 API 设计文档

需要追溯历史决策时查阅归档；需要推进 V3 时更新本目录。
