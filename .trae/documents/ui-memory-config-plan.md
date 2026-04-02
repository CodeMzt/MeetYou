# MeetYou 前端界面更新计划（记忆可视化与用户配置对接）

## 1. 摘要 (Summary)
本项目旨在为 MeetYou 桌面端引入「记忆可视化」与「配置管理」能力。鉴于主聊天窗口（360x560）空间有限，计划新开一个独立的 Electron 窗口（Dashboard，尺寸约 850x650），专用于展示 4 个维度的记忆视图（Overview, Records, Timeline, Graph）以及全局用户配置（如深度思考参数等）。主窗口将优化为纯粹的 MacOS 风格，并加入交通灯窗口控件。

## 2. 当前状态分析 (Current State)
- **主窗口布局**：`App.tsx` 中的聊天界面空间紧凑，不适合展示复杂的网络图（Graph）和数据表格。
- **后端接口支持**：`gateway/api.py` 和 `gateway/models.py` 已提供 `/config`（读写）和 `/memory`, `/memory/graph`（读）接口，但前端 `useMeetYou.ts` 尚未对接。
- **依赖情况**：前端 `package.json` 已安装 `vis-network`（可用于 Graph 视图）、`framer-motion`（用于动画）以及 `lucide-react`（用于图标）。

## 3. 提议的变更 (Proposed Changes)

### 3.1. Electron 窗口管理 (`electron/main.ts`, `electron/preload.ts`)
- **新增 Dashboard 窗口**：在 `main.ts` 中增加 `createDashboardWindow()` 函数，创建一个 850x650 大小的窗口，同样启用 `mica`/`popover` 材质，无边框设计（隐藏原生标题栏）。
- **IPC 通信**：在 `main.ts` 中监听 `open-dashboard` 事件，由主聊天窗口触发以打开或唤起（Focus）Dashboard 窗口。
- **多窗口路由支持**：由于使用 Vite，通过在 `loadURL` 或 `loadFile` 后面追加 hash 路由（如 `#/dashboard`）来区分当前加载的是主窗口还是 Dashboard。

### 3.2. React 架构调整与路由 (`src/main.tsx`, `src/App.tsx`, `src/Dashboard.tsx`)
- 引入轻量级的 Hash 路由（或手动监听 `window.location.hash`）来渲染不同的根组件。
- `App.tsx` 依然作为主聊天界面。
- 新增 `Dashboard.tsx` 组件，作为新窗口的根节点。

### 3.3. 数据对接 Hooks (`src/hooks/useMemory.ts`, `src/hooks/useConfig.ts`)
- **`useConfig`**：封装 `GET /config`（获取所有配置快照）和 `PATCH /config`（批量更新配置）。支持 `thinking_enabled`, `thinking_effort`, `thinking_budget_tokens` 等选项的读取与修改。
- **`useMemory`**：封装 `GET /memory` 和 `GET /memory/graph`。返回结构化的 `MemorySnapshotResponse` 和 `MemoryGraphResponse`。

### 3.4. 记忆可视化设计 (Memory Views in `Dashboard.tsx`)
采用左侧导航栏 + 右侧内容区的布局。左侧导航栏包含 "Overview", "Records", "Timeline", "Graph" 以及 "Settings"。

1. **Overview (概览视图)**：
   - 顶部卡片展示全局和会话的 `working_summaries`。
   - 统计卡片展示 `stats.by_type`（Profile 数量、Task 数量、Episode 数量）。
   - 最近的 5 条高重要度（`importance`）事件速览。

2. **Records (记录列表视图)**：
   - 展示所有 `records`，提供一个优雅的表格或卡片流。
   - 顶部提供筛选器：按 `type` (profile_fact, task, episode) 和 `status` (active, invalidated) 过滤。
   - 卡片内展示 `content`，以及 Badge 样式的 `confidence`, `strength` 和 `tags`。

3. **Timeline (时间线视图)**：
   - 将 `records` 按 `created_at` 或 `last_updated_at` 排序。
   - 使用垂直时间线组件，区分 `episode` 的发生、`task` 的状态变更（如完成或新增）、`profile_fact` 的失效（`invalidated`）。

4. **Graph (知识图谱视图)**：
   - 利用已安装的 `vis-network` 库，渲染 `nodes` 和 `edges`。
   - 节点颜色按 `type` 区分（如 Profile 节点为蓝色，Task 为绿色，Episode 为灰色）。
   - 边的粗细或透明度反映 `semantic_sim` 或关联强度（`same_entity`, `same_project`）。
   - 提供缩放、拖拽和节点点击高亮详情能力。

### 3.5. 配置面板 (Settings in `Dashboard.tsx`)
- 提供一个表单页面，分类展示并修改 `/config` 下的受管配置。
- 包括：API 密钥、模型选择、深度思考（Thinking）参数、网关端口等。
- 采用防抖（Debounce）或底部 "保存" 按钮调用 `PATCH /config` 接口。

### 3.6. 主窗口 MacOS 风格优化 (`src/App.tsx`, `src/index.css`)
- **交通灯按钮**：将右上角的标题栏操作按钮移至左上角，替换为红（关闭）、黄（最小化）、绿（全屏/置顶）的圆形按钮。
- **设置入口**：原有的设置齿轮按钮点击后，通过 `ipcRenderer.send('open-dashboard')` 唤起新窗口，而非在原窗口内弹出拥挤的面板。
- **气泡与细节**：优化字体排版、毛玻璃层级和气泡阴影，确保在 Windows 的 Mica 材质上拥有极佳的透明质感。

## 4. 假设与决策 (Assumptions & Decisions)
- **多窗口架构**：假定通过 Electron 新开窗口来展示复杂图表是最佳实践，避免主聊天窗口频繁调整大小导致体验割裂。
- **图表库选择**：使用已存在于 `package.json` 中的 `vis-network`，无需引入新的庞大依赖（如 `react-force-graph-2d`）。
- **路由实现**：为避免引入 `react-router-dom` 增加体积，可以通过简单的 `window.location.hash === '#/dashboard'` 在 `main.tsx` 中做根级分发。

## 5. 验证步骤 (Verification Steps)
1. 启动 Electron 应用，检查主窗口的 MacOS 交通灯布局是否正常，窗口置顶、最小化、关闭功能是否工作。
2. 点击主窗口的「设置/记忆」按钮，确认 Dashboard 新窗口是否成功弹出且具有独立布局。
3. 在 Dashboard 的 Config 页面修改 `thinking_enabled` 等选项，确认能够通过 `PATCH /config` 成功更新后端状态。
4. 确保后端包含一定量的记忆数据，并在 Dashboard 的 Graph、Timeline、Records、Overview 四个视图中检查渲染是否正确且无报错，特别是 `vis-network` 图表的交互性。