# Desktop Agent 远端云端验收记录（codex cloud）

## 1) 测试总纲

本次按“先测试、后修复、再复测”执行，目标是验证并修复 Desktop Agent 前后端联动中可在 Linux 云容器完成的部分，并明确云端边界：

- 覆盖聊天主链、前端状态与交互、Desktop Agent / Core 边界相关后端验证。
- Danxi 相关工具与页面不纳入本轮验收。
- 对必须依赖 Windows + Electron 真机的验收项，明确标记为“云端不可完成，需本地 Windows 继续验收”。

## 2) 环境前提

- 运行环境：Codex Linux 容器（非 Windows 桌面会话）。
- Python/Node/npm 已就绪。
- `MEETYOU_DATABASE_URL`、`MEETYOU_GATEWAY_ACCESS_TOKEN`、`MEETYOU_API_KEY`、`MEETYOU_AGENT_WS_ACCESS_TOKEN` 在环境中可见。
- 但容器内未提供可连接的 PostgreSQL 服务实例（`127.0.0.1:5432` 未监听），且无 Electron 真机能力。

## 3) 实际运行命令

### 3.1 基线与云端准备

1. `python scripts/check_codex_cloud_readiness.py --profile=cloud-dev`
2. `bash scripts/codex/cloud-verify.sh`（初次失败：缺少 `.venv-codex`）
3. `bash scripts/codex/cloud-setup.sh`（安装 Python 依赖成功；`npm ci` 因 lock 与 package 不一致失败）
4. `cd meetyou-ui && npm install --package-lock=false`（仅用于当前容器补齐 node_modules，不改 lock）
5. 重新执行 `bash scripts/codex/cloud-verify.sh`（通过）
6. `python scripts/check_codex_cloud_readiness.py --profile=cloud-core-test`

### 3.2 先测阶段（修复前）

1. `cd meetyou-ui && npm run typecheck`（最初因未安装依赖失败）
2. `cd meetyou-ui && npm run test`（最初因未安装依赖失败）
3. `.venv-codex/bin/python -m unittest tests.test_local_tool_agent_proxy`（通过）
4. `.venv-codex/bin/python -m unittest tests.test_gateway_surface_routes`（失败：PostgreSQL 连接拒绝）

### 3.3 修复后复测

1. `cd meetyou-ui && npm run typecheck && npm run test`（通过）
2. `python scripts/check_codex_cloud_readiness.py --profile=cloud-dev`（通过，含平台边界 warn）
3. `bash scripts/codex/cloud-verify.sh`（通过）
4. `python scripts/check_codex_cloud_readiness.py --profile=cloud-core-test`（通过，含平台/数据库诊断 warn）
5. `.venv-codex/bin/python -m unittest tests.test_local_tool_agent_proxy`（通过）
6. `.venv-codex/bin/python -m unittest tests.test_gateway_surface_routes`（仍失败：容器无 PostgreSQL 实例）

## 4) 发现的问题

### 4.1 交互问题（本次已修复）

1. **流式输出时强制自动滚动**：用户手动滚动阅读历史内容时，界面仍持续追踪到底部。
2. **“最近操作”组件在主聊天区过于突兀**：占据主页面注意力，影响主对话阅读。
3. **浮动面板无法点击外部收起**：
   - 输入框左侧设置弹层（模式/思考）
   - 顶部状态岛（灵动岛）展开面板
   均缺少外部点击自动关闭。

### 4.2 云端边界与后端验证问题

1. `tests.test_gateway_surface_routes` 依赖 PostgreSQL 管理连接；当前容器内数据库不可达，测试无法完成。
2. 云端容器无法替代 Windows 本机 Desktop Agent 能力验收（本地文件、Shell、UI 自动化、Electron 真机交互/截图）。
3. “File System 在 Agent（Windows）执行”这一产品语义，在 Linux 云容器中无法做最终真机语义验收；本次仅通过 dispatch 相关后端测试与边界文档校验，不能替代本地终验。

## 5) 修复内容

### 5.1 主聊天流自动滚动改造

- 在消息列表加入“自动追踪解锁”逻辑：
  - 流式阶段若用户滚离底部，自动停止追踪。
  - 提供“回到底部继续追踪输出”按钮，允许用户主动恢复。
  - 非流式阶段回到底部时自动恢复追踪。

### 5.2 “最近操作”从主页面迁出并精简

- 主聊天区移除 `OperationPanel`，减少视觉占用。
- 在“工作区与规程”子窗口新增轻量“开发调试 / 最近操作（最多 3 条）”列表，保留调试可见性但不打断主对话。

### 5.3 浮动面板外部点击关闭

- 输入区设置弹层新增 click-outside 自动关闭。
- 状态岛展开下拉新增 click-outside 自动关闭。

## 6) 复测结果

- 前端类型检查与单测：通过。
- 云端基线验证（cloud-dev/cloud-verify）：通过。
- Desktop Agent 本地工具代理边界相关后端最小测试：通过（`test_local_tool_agent_proxy`）。
- 依赖 PostgreSQL 的 gateway surface 路由测试：未通过（环境缺 PostgreSQL，不是本次代码回归引入）。

## 7) 云端已完成项

1. 基线 readiness 与 cloud verify。
2. 前端交互问题 3 项修复与复测（可在云端代码/测试层确认）。
3. Agent 工具边界相关最小后端测试（不含 Windows 真机能力）。
4. 过程文档与验收记录沉淀。

## 8) 仍需本地 Windows 最终验收项（云端不可完成）

> 明确标记：**云端不可完成，需本地 Windows 继续验收**

1. Electron 真机 UI 行为验收（窗口层级、点击体感、焦点行为、多窗协同）。
2. `scripts/Capture-Screen.ps1` 截图验收。
3. Desktop Agent 本机文件系统 / Shell / UIAutomation 能力的真实执行语义验收。
4. “File System 工具确实在 Windows Agent 侧执行，而非 Core Linux 执行”的真机链路终验。
5. 依赖 PostgreSQL 的完整 gateway surface / 真实链路联调（需可达 DB 实例）。

## 9) 备注

- 当前仓库本地仅有 `work` 分支，未发现 `codex/test` 分支；本次在当前分支执行。
- 未触碰 `.env`、`user/*.json`、`logs/`、构建产物目录。
