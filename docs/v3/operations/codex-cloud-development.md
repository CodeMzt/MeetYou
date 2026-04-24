# Codex 云端开发接入

## 1. 目标

这份文档给 MeetYou 提供一套可直接落地的 Codex 云端开发配置，目标是：

- 让 Codex 云端任务能稳定完成代码修改
- 保留前端 `typecheck` / `vitest`
- 保留 `desktop_agent` 的非 GUI 逻辑测试
- 不误把 Windows 本机桌面验收迁成 Linux 容器验收

## 2. 适用边界

适合放到 Codex 云端的工作：

- `core/`、`gateway/`、`service_runtime/` 代码修改
- 协议、配置、文档、测试代码修改
- `desktop_agent/` 的纯逻辑改动
- `meetyou-ui/` 的非 Electron 真机 GUI 改动
- `npm run typecheck`
- `npm run test`

不适合直接放到 Codex 云端的工作：

- Electron 多窗口真机交互验收
- `desktop-agent` 的本机文件、Shell、UIAutomation、截图链路验收
- `scripts\Capture-Screen.ps1` 相关验收
- Windows 打包产物最终验收

## 3. 仓库内现成资产

已提供以下文件：

- [cloud-setup.sh](/E:/Documents/Project/MeetYou/scripts/codex/cloud-setup.sh)
- [cloud-maintenance.sh](/E:/Documents/Project/MeetYou/scripts/codex/cloud-maintenance.sh)
- [cloud-verify.sh](/E:/Documents/Project/MeetYou/scripts/codex/cloud-verify.sh)
- [cloud.env.example](/E:/Documents/Project/MeetYou/deploy/codex/cloud.env.example)
- [check_codex_cloud_readiness.py](/E:/Documents/Project/MeetYou/scripts/check_codex_cloud_readiness.py)

注意：

- 这三份 `.sh` 脚本面向 Codex 云端 Linux 容器
- 不要把它们当成你本地 Windows PowerShell 启动脚本

## 4. Codex 环境推荐配置

参考 OpenAI 官方文档：

- [Cloud environments](https://developers.openai.com/codex/cloud/environments)
- [Internet access](https://developers.openai.com/codex/cloud/internet-access)

推荐这样配置：

1. GitHub 仓库接入当前仓库
2. Setup script 填：

```bash
bash scripts/codex/cloud-setup.sh
```

3. Maintenance script 填：

```bash
bash scripts/codex/cloud-maintenance.sh
```

4. 运行后人工校验命令：

```bash
bash scripts/codex/cloud-verify.sh
```

## 5. Environment variables

直接参考：

- [cloud.env.example](/E:/Documents/Project/MeetYou/deploy/codex/cloud.env.example)

推荐最小值：

- `MEETYOU_CODEX_INSTALL_FRONTEND=1`
- `MEETYOU_CODEX_INSTALL_DESKTOP_AGENT=1`
- `MEETYOU_CODEX_INSTALL_EDGE_AGENT=0`
- `MEETYOU_CODEX_VERIFY_FRONTEND=1`
- `MEETYOU_CODEX_VERIFY_PROFILE=cloud-dev`

只有你要跑真实 Core / 受保护 surface 时，再补：

- `MEETYOU_DATABASE_URL`
- `MEETYOU_GATEWAY_ACCESS_TOKEN`
- `MEETYOU_API_KEY`
- 其他模型 / agent token

## 6. Internet access 建议

推荐默认策略：

- setup script：允许网络
- agent phase：默认关闭，或使用 limited + allowlist

推荐 allowlist 起点：

- `github.com`
- `githubusercontent.com`
- `pypi.org`
- `pythonhosted.org`
- `files.pythonhosted.org`
- `registry.npmjs.org`
- `npmjs.com`

如果云端任务需要访问线上 Core，再追加你的 Core 域名。

如果需要 Danxi，再按实际链路单独追加对应域名。

## 7. 数据库注意事项

当前仓库的正式 Core 链路依赖 PostgreSQL。

这意味着：

- 仅做代码编辑、前端验证、纯逻辑单测时，可以不配数据库
- 只要想在 Codex 云端里真正启动 Core 或跑依赖数据库的后端测试，就必须提供 `MEETYOU_DATABASE_URL`

更实际的建议是：

1. 默认把 Codex 云端当成“代码开发 + 非 DB 验证”环境
2. 只有当你已经确认云端环境确实能稳定访问目标 PostgreSQL 时，再切到 `cloud-core-test` 级别验证

数据库可用性检查命令：

```bash
python scripts/check_codex_cloud_readiness.py --profile=cloud-core-test
```

## 8. 验证方式

### 8.1 云端开发基线

```bash
python scripts/check_codex_cloud_readiness.py --profile=cloud-dev
bash scripts/codex/cloud-verify.sh
```

### 8.2 仅检查本地桌面验收边界

```bash
python scripts/check_codex_cloud_readiness.py --profile=desktop-local-acceptance
```

这个 profile 的目的不是在云端通过，而是明确提醒你：桌面验收必须回到 Windows 本机。

## 9. 典型工作流

推荐工作流：

1. 在 Codex 云端做代码修改
2. 在云端跑 `bash scripts/codex/cloud-verify.sh`
3. 涉及 Electron 真机 UI、桌面工具、本机文件/Shell 能力时，回到本地 Windows 做人工验收
4. 需要最终构建时，再回本地 Windows 跑 `npm run build`

## 10. 不要这样用

不要在 Codex 云端里默认做这些事：

1. 把 `/desktop/*` 当成用户本机 Windows backend 来验收
2. 把 Linux 容器内的文件/Shell 验收，当成 Desktop Agent 本机能力验收
3. 把 Electron renderer 单测通过，当成桌面产品最终验收
4. 在没配 PostgreSQL 的前提下，声称 Core 云端开发环境已经完整
