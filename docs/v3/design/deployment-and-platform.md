# MeetYou V3 部署与跨平台设计

## 1. 目标

V3 在部署与平台方向上的核心目标是：

1. 简化个人用户部署 Core Service 的成本
2. 把桌面端收口为统一交付物，由 Electron UI + desktop backend 组成
3. 保留 Core / Desktop / Edge 的分离边界，不把本地能力打回服务端单体口径
4. 降低 Windows 优先实现对 Linux 部署与长期维护的牵制
5. 为后续便携打包与自动化测试提供稳定边界

## 2. 当前基线

当前仓库已经具备：

- Core / Desktop Agent / Edge Agent 三套依赖清单
- `python -m service_runtime`、`python -m desktop_agent`、`python -m edge_agent` 三个生产入口
- Core 官方 `Dockerfile`
- `deploy/docker/compose.core-postgres.yml` 最小个人部署模板
- `scripts/prepare_core_runtime.py` 与 `scripts/check_core_runtime.py` 最小初始化 / 自检脚本
- Linux 非容器化部署模板：`deploy/systemd/*` 与 `scripts/linux/*`
- Electron 桌面端构建脚本：`npm run build`
- Electron main 托管本地 desktop backend，renderer 默认改连本地 `/desktop/*` API

当前仓库尚未具备：

- Python 服务端 / Agent 的便携打包脚本
- 跨平台 CI 测试矩阵

## 3. 设计原则

### 3.1 部署简化优先服务端

V3 的“一键部署”优先覆盖 Core Service 与数据库，因为这条链路最适合在 Linux 服务器、NAS、树莓派或家庭服务器上长期运行。

`desktop-agent` 仍然是用户设备侧运行时，不应为了追求单命令部署而被并入服务器镜像。

### 3.2 保留服务端分离、桌面端一体化

V3 计划同时维护两条部署口径：

- Linux 主机部署：继续基于 `systemd` 模板与脚本演进
- 容器化部署：新增适合个人用户的 Core + PostgreSQL 最小编排模板

二者的目标是共享同一套运行边界，而不是做两套不同的服务拓扑。

对桌面端则采用另一条原则：

- UI 与 desktop backend 作为一个桌面产品交付
- Core 与 Edge Agent 继续保留独立部署与发布节奏

### 3.3 平台相关能力继续留在 Agent 边界

Windows 专属桌面能力、UI automation、本地 Shell 与本地文件访问继续归属于 Agent 边界。

V3 的跨平台改造应优先做：

- 平台能力抽象
- 能力可用性声明
- 非 Windows 下的替代实现或显式禁用

而不是把平台差异重新转嫁回 Core。

### 3.4 打包口径按交付边界分离

如果 V3 后续引入便携发行包或可执行文件，按以下交付边界考虑：

- Core Service
- Desktop Product（Electron UI + desktop backend）
- edge-agent

不要把三者重新打成必须同批上线的单包；也不要再把桌面 UI 和本地 backend 当成两份互不相干的桌面交付物。

## 4. 计划落点

### 4.1 容器化

当前仓库已经提供的容器化基线是：

- Core Service 的官方 `Dockerfile`
- 面向个人用户的 Core + PostgreSQL 编排模板：`deploy/docker/compose.core-postgres.yml`
- 与 `deploy/docker/compose.env.example`、`user/config.docker.example.json` 对齐的最小配置说明
- 初始化 / 自检脚本：`scripts/prepare_core_runtime.py`、`scripts/check_core_runtime.py`

容器方案需要明确：

- 数据卷边界
- 数据库连接与 migration 责任
- `gateway_access_token` 等敏感配置的注入方式
- Docker 配置模板中 `gateway_host=0.0.0.0` 的要求

### 4.2 Linux 部署模板延续

现有 `deploy/systemd/` 与 `scripts/linux/` 是 V3 的直接基础，不应在新增容器路径时被废弃。

V3 应继续维护：

- systemd 模板与环境变量样例
- Linux 文档中的启动、升级、回滚和人工验收路径

对应操作基线见 `../operations/core-deployment.md`。

### 4.3 跨平台能力收口

围绕桌面端继续推进：

- Electron 托管 desktop backend 的启动、恢复与退出
- Desktop backend 对 UI 的 `/desktop/*` 契约边界
- Windows 特定能力的插件化或模块化边界
- 非 Windows 下的 capability 降级、禁用或替代实现语义
- 文档与测试中对平台差异的显式说明

### 4.4 打包与分发

桌面端已有 `electron-builder` 基础；Core / Agent 的打包仍是待建设项。

V3 可以探索：

- 桌面产品内嵌或托管 Python backend 的分发方式
- Core / Edge 独立安装包
- 面向非技术用户的最小安装脚本

但在真正落地前，文档不得把这些能力写成既有事实。

## 5. 验收约束

部署与平台方向的改动至少要保证：

- 不破坏现有 `python -m service_runtime`、`python -m desktop_agent`、`python -m edge_agent` 入口
- 不改变 `GET /client/ws` 与 `WSS /agent/ws` 的正式路径口径
- 不削弱 PostgreSQL + Alembic migration 的正式持久化路径
- 不让 renderer 恢复为直连 Core 的默认路径
- 文档声明只覆盖仓库中已存在、或已被代码与测试验证的能力

## 6. 关联计划

执行顺序与 feature 拆分见 `../plan/implementation-plan.md` 中的 Phase 1、Phase 2 与 Phase 5；具体 Core 部署操作见 `../operations/core-deployment.md`。
