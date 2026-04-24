# MeetYou V3 文档入口

这里是 MeetYou V3 的当前真源文档入口。

V3 的文档目标不是重复抄写 V2，而是在保留现有稳定运行边界的前提下，明确下一轮迭代要落到哪里、如何拆阶段、以及哪些约束不能被重新打破。

## 建议阅读顺序

1. `design/architecture-baseline.md`
2. `design/desktop-unified-agent.md`
3. `design/workspace-memory-context.md`
4. `design/deployment-and-platform.md`
5. `operations/core-deployment.md`
6. `design/bot-integration.md`
7. `plan/implementation-plan.md`

## 文档分工

- `design/architecture-baseline.md`：当前仓库已经证实的运行边界与 V3 设计基线
- `design/desktop-unified-agent.md`：桌面端 UI + backend 一体化、`/desktop/*` API 与运行边界设计
- `design/deployment-and-platform.md`：部署简化、容器化、跨平台与打包方向
- `operations/core-deployment.md`：Core + PostgreSQL 的 Docker Compose 与 Linux `systemd` 部署基线
- `operations/desktop-unified-acceptance.md`：桌面端一体化主链的人工启动与验收口径
- `design/bot-integration.md`：WeChat Bot 接入的设计边界、任务清单与落点
- `plan/implementation-plan.md`：V3 的 `Phase -> Feature -> Task` 执行计划

## 更新要求

- 影响部署、协议、发布单元、验收顺序或跨端边界时，同步更新本目录下相应文档。
- 影响仓库协作规则、验证口径或目录边界时，同时更新 `README.md` 与 `AGENTS.md`。
- V2 归档内容只作为参考输入；当 V3 文档与归档内容冲突时，以 `docs/v3/` 为准。
