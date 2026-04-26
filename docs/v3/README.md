# MeetYou V3 文档入口

`docs/v3/` 是当前生效的设计、计划与运维文档真源。V2 归档内容仅作历史参考。

## 建议阅读顺序

1. `design/architecture-baseline.md`
2. `design/client-tools.md`
3. `design/desktop-unified-client.md`
4. `design/deployment-and-platform.md`
5. `operations/core-deployment.md`
6. `operations/desktop-client-acceptance.md`
7. `plan/implementation-plan.md`

## 文档分工

- `design/architecture-baseline.md`：当前 `Core + Clients + Tools` 架构基线。
- `design/client-tools.md`：Client identity、tool 声明、directed tool 调度和协议帧。
- `design/desktop-unified-client.md`：Electron UI + `desktop_client` backend 一体化边界。
- `design/deployment-and-platform.md`：发布单元、入口、打包、平台和升级顺序。
- `operations/core-deployment.md`：Core Service 部署与访问令牌口径。
- `operations/desktop-client-acceptance.md`：桌面主链人工启动与验收口径。
- `plan/implementation-plan.md`：当前 V3 执行计划。

## 更新要求

- 影响部署、协议、发布单元、验收顺序或跨端边界时，同步更新本目录相关文档。
- 影响仓库协作规则、验证口径或目录边界时，同时更新 `README.md` 与 `AGENTS.md`。
- 当 V3 文档与历史归档冲突时，以 `docs/v3/` 为准。
