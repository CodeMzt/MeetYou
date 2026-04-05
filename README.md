# MeetYou

MeetYou 是一个以 LLM 为核心的多入口智能体项目，当前已经整理为“网关后端 + 多种客户端/适配器”的运行形态。它围绕统一事件协议组织 `Brain`、`Heart`、`Memory`、`Tools`、`Speaker` 等模块，支持：

- `FastAPI` 网关
- `CIL` 终端客户端
- `Electron + React` 桌面悬浮窗
- 可选 `Feishu Bot`
- 记忆图谱、运行态快照、配置热更新、工具链调用与确认机制

## 当前形态

项目目前的主入口是网关运行时，默认使用：

```text
User / CIL / Desktop UI / Feishu
        ->
   HTTP / WebSocket / Adapter
        ->
      EventBus
        ->
       Brain
        ->
      Tools / Memory / MCP / Heart
        ->
      Speaker
        ->
WebSocket / CLI / Feishu Output
```

核心能力包括：

- 统一输入输出协议，便于同时接入 UI、CLI 和 Bot
- 多模型适配，当前代码中已接入 OpenAI、Anthropic、Gemini、Ollama
- 长时记忆与记忆图谱查询接口
- 会话级运行状态、推理摘要、token/context 使用量透出
- Assistant Modes 路由机制，支持不同场景下的工具束与策略切换
- 配置中心与热更新接口
- 定时任务、后台心跳、系统感知能力

## 目录结构

```text
core/            核心编排、会话、状态、模式路由、应用生命周期
gateway/         FastAPI HTTP / WebSocket 网关
cil/             基于 gateway 的终端客户端
adapters/        大模型与外部服务适配器
sensors/         输入/输出适配层与系统感知
tools/           工具集合，含 memory、mcp、documents、web_search 等
platform_layer/  平台能力抽象
prompt/          系统提示词、模式提示词、技能提示词（统一位于 prompt/SKILL）
meetyou-ui/      Electron + React 桌面端
docs/            协议与补充文档
tests/           自动化回归测试
user/            本地配置、工具 schema、记忆数据、MCP 配置等
```

## 环境要求

- Python `3.10+`
- Node.js `18+`（桌面端开发/构建）
- 可用的大模型服务与 API Key
- Windows 优先

说明：

- 当前仓库包含 `uiautomation`、PowerShell launcher、`.cmd` 脚本，以及 Electron Windows 窗口特性，整体体验明显偏向 Windows。
- 后端代码保留了 `platform_layer/linux.py`、`platform_layer/macos.py`，但如果要在非 Windows 环境完整跑通，需要自行验证系统工具链与依赖。

## 安装

### 1. 安装 Python 依赖

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 安装桌面端依赖

```bash
cd meetyou-ui
npm install
```

## 配置

配置分两层：

- `user/config.json`：非敏感业务配置
- `.env`：密钥与敏感令牌

`user/` 下常用模板已随仓库提供，可参考 [user/README.md](user/README.md) 复制初始化：

- `user/config.example.json` -> `user/config.json`
- `user/tools.example.json` -> `user/tools.json`
- `user/mcp_servers.example.json` -> `user/mcp_servers.json`
- `user/cmd_policy.example.json` -> `user/cmd_policy.json`
- `user/source_catalog.example.json` -> `user/source_catalog.json`
- `user/memory_graph.example.json` -> `user/memory_graph.json`
- `user/feishu_chat_ids.example.json` -> `user/feishu_chat_ids.json`

可以先复制环境变量模板：

```bash
copy .env.example .env
```

### 最小 `user/config.json` 示例

```json
{
  "api_provider": "openai",
  "api_url": "https://api.openai.com/v1/responses",
  "model": "gpt-5.4",
  "heartbeat_api_provider": "openai",
  "heartbeat_api_url": "https://api.openai.com/v1/responses",
  "heart_model": "gpt-5.4-mini",
  "embedding_api_url": "https://api.openai.com/v1/embeddings",
  "embedding_model": "text-embedding-3-small",
  "thinking_enabled": true,
  "thinking_effort": "medium",
  "tools_schema_path": "user/tools.json",
  "soul_path": "prompt/soul",
  "start_path": "prompt/start",
  "heartbeat_path": "prompt/heartbeat",
  "memory_file_path": "user/memory_graph.json",
  "source_catalog_path": "user/source_catalog.json",
  "gateway_host": "127.0.0.1",
  "gateway_port": 8000,
  "enable_gateway": true,
  "enable_feishu_bot": false
}
```

### `.env` 中常见变量

```env
MEETYOU_API_KEY=
MEETYOU_HEARTBEAT_API_KEY=
MEETYOU_EMBEDDING_API_KEY=
TAVILY_API_KEY=
NOTION_TOKEN=
MEETYOU_FEISHU_APP_ID=
MEETYOU_FEISHU_APP_SECRET=
```

### 常用配置项

- `api_provider` / `api_url` / `model`：主对话模型
- `heartbeat_api_provider` / `heartbeat_api_url` / `heart_model`：后台心跳模型
- `embedding_api_url` / `embedding_model`：向量化与记忆能力
- `thinking_enabled` / `thinking_effort` / `thinking_budget_tokens`：默认推理参数
- `assistant_modes` / `mode_router`：模式路由与工具策略
- `tools_schema_path`：工具 schema
- `source_catalog_path`：研究来源目录
- `enable_feishu_bot`：是否启用飞书
- `gateway_host` / `gateway_port`：网关监听地址

## 启动方式

### 1. 默认启动 Launcher

```bash
python main.py
```

等价于：

```bash
python main.py launcher
```

Launcher 当前支持：

- `start gateway`
- `start cil`
- `start ui`
- `status`
- `exit`

### 2. 只启动网关后端

```bash
python main.py gateway
```

启动后默认监听：

```text
http://127.0.0.1:8000
```

### 3. 启动终端客户端 CIL

先确保 gateway 已启动：

```bash
python main.py cil
```

支持的内置命令：

- `/help`
- `/config list`
- `/config get <key>`
- `/config set <key> <value>`

### 4. 启动桌面端 UI

先确保 gateway 已启动，再在 `meetyou-ui/` 下运行：

```bash
npm run dev
```

如果你从 launcher 执行 `start ui`，会自动尝试拉起 gateway，再打开 Electron 开发窗口。

## 网关接口

当前主要接口如下：

- `GET /health`：健康检查
- `POST /inputs`：提交输入
- `GET /config`：读取受管配置快照
- `GET /config/{key}`：读取单项配置
- `PATCH /config`：更新配置并触发部分热刷新
- `GET /memory`：读取记忆快照
- `GET /memory/graph`：读取图结构记忆数据
- `GET /runtime/state`：读取运行状态
- `GET /runtime/usage`：读取 token/context 使用情况
- `GET /ws`：订阅会话流式输出

详细协议见 [docs/interface.md](docs/interface.md)。

### `POST /inputs` 示例

```json
{
  "content": "帮我总结今天的任务",
  "session_id": "web-session-001",
  "source_id": "desktop-app",
  "role": "user",
  "metadata": {},
  "options": {
    "thinking": {
      "enabled": true,
      "effort": "high",
      "budget_tokens": 1024
    }
  }
}
```

### WebSocket 连接示例

```text
ws://127.0.0.1:8000/ws?session_id=web-session-001&source_id=desktop-app
```

网关会通过统一 envelope 推送：

- `message`
- `reasoning`
- `status`
- `confirm_request`
- `runtime_status`
- `usage`
- `error`

## 桌面端说明

`meetyou-ui/` 是一个 Electron + React 桌面端，当前已经接入：

- 聊天界面
- 推理摘要展示
- 工具活动展示
- 运行状态条
- token/context 统计面板
- 设置页
- 记忆图谱页

开发命令：

```bash
cd meetyou-ui
npm run dev
```

构建命令：

```bash
npm run build
```

## 飞书 Bot

启用飞书前至少需要：

- `enable_feishu_bot = true`
- `.env` 中配置 `MEETYOU_FEISHU_APP_ID`
- `.env` 中配置 `MEETYOU_FEISHU_APP_SECRET`

相关持久化文件：

- `user/feishu_chat_ids.json`

输出端会通过 `FeishuOutputAdapter` 发送消息，输入端通过 `FeishuInputAdapter` 统一映射为内部事件。

## 测试

仓库当前包含较多后端测试，集中在 `tests/` 目录，例如：

- 运行态与 usage
- gateway 配置与记忆接口
- assistant modes
- memory / task scheduler
- scenario tools / document tools

如果本地已安装测试依赖，可执行：

```bash
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

## 相关文档

- [docs/interface.md](docs/interface.md)：网关协议
- [docs/playwright-mcp.md](docs/playwright-mcp.md)：Playwright MCP 说明

## License

MIT. See [LICENSE](LICENSE).
