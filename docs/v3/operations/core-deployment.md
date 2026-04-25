# MeetYou Core Deployment

## Heartbeat Idle Poke Operations

Core deploys with idle proactive touch enabled by default: `heartbeat_idle_poke_enabled=true`, `heartbeat_idle_poke_after_seconds=3600`, `heartbeat_idle_poke_cooldown_seconds=3600`, and `heartbeat_idle_context_compaction_enabled=true`.

Operators can change these values without restarting through `/operator/config`, `/desktop/config`, or the `manage_heartbeat_settings` tool. `/health` exposes the effective values and recent idle poke/proactive delivery status through metrics/check metadata, while runtime debug exposes the same state under `task_state.background.heartbeat_idle`.

The idle poke path does not require a live websocket when a client thread can be resolved. Core still persists the assistant message to the thread/message store so the user can see it on the next open.

本文档记录 V3 当前可落地的 Linux 服务器部署口径。目标部署单元是：

- `Core Service`
- `PostgreSQL`

桌面 UI 与 `desktop-agent` 仍属于用户设备侧交付物，不部署到 Linux Core 服务器上作为主链。

WeChat 接入已切换为 MeetWeChat Client。真实微信账号、登录态和微信侧连接由已部署的 MeetWeChat 服务持有；Core 只通过 `docs/MeetWechat_API.md` 的 `/v1` HTTP API 轮询事件、ACK 和发送文本，并继续走正式 `/client/* + /client/ws` 主链。

## 1. Docker Compose 部署

仓库提供的 Compose 模板位于：

- `Dockerfile`
- `deploy/docker/compose.core-postgres.yml`
- `deploy/docker/compose.env.example`
- `user/config.docker.example.json`

首次准备：

```bash
python scripts/prepare_core_runtime.py --profile docker --output-root deploy/docker/runtime
python scripts/check_core_runtime.py --profile docker --runtime-root deploy/docker/runtime
```

如果服务器没有现成 PostgreSQL，用内置 PostgreSQL 启动：

```bash
docker compose --env-file deploy/docker/compose.env -f deploy/docker/compose.core-postgres.yml up -d --build
```

如果服务器已经有 PostgreSQL，把 `deploy/docker/compose.env` 中的 `MEETYOU_DATABASE_URL` 指向现有数据库，再按需移除 Compose 里的 `postgres` service。

Windows 本机调试也可以用：

```bat
scripts\docker-core-acceptance.cmd prepare
scripts\docker-core-acceptance.cmd check
scripts\docker-core-acceptance.cmd start
```

这里的 PostgreSQL service 不是第二套数据模型，也不是替代仓库已有 SQL 代码；它只是给没有现成数据库的部署场景顺带启动一个 PostgreSQL 进程。Core 仍然只通过 `MEETYOU_DATABASE_URL` 访问一套正式 PostgreSQL，并由 Core Service 持有 Alembic migration 主导权。

## 2. MeetWeChat Client 边界

MeetWeChat Client 当前方案见 `docs/v3/design/bot-integration.md`。部署层只保留以下原则：

- 不再在 Compose 中托管第三方微信协议服务
- MeetWeChat 服务应在 Core 可访问的网络地址上运行，默认 `http://127.0.0.1:38961`
- 默认保持 `MEETYOU_MEETWECHAT_ENABLE=false`，完成低频顺序验收后再按环境启用
- MeetWeChat 凭证、cookie、联系人名和完整聊天正文不得写入配置模板或验收记录
- Core 侧只持有 `meetwechat_state_file` 中的事件状态、ACK 补偿、thread 绑定和群成员别名
- 入站消息显式开放基础工具白名单，不开放本地文件/Shell/Desktop Agent 能力
- 当前只承诺文本闭环；媒体消息跳过并 ACK

最小联调步骤：

1. 确认 MeetWeChat 服务 `GET /v1/health` 正常。
2. 启动 `python -m service_runtime` 或对应 Docker Core 服务。
3. 设置 `MEETYOU_MEETWECHAT_ENABLE=true`，必要时设置 `MEETYOU_MEETWECHAT_BASE_URL`。
4. 私聊发送一条低风险文本消息，确认 MeetYou 经 `/client/* + /client/ws` 生成回复并通过 `/v1/messages/text` 回发。
5. 群聊普通消息应只 ACK 不回复；群聊 @ 助理时才回复。
6. 设置 MeetWeChat override 为 `manual_only`，确认 Core 不再发送微信回复。

## 3. Host / systemd 部署

非容器化部署仍保留：

- `deploy/systemd/meetyou-core.service.template`
- `deploy/systemd/core.env.example`
- `scripts/linux/install-core-systemd.sh`

核心要求：

- `WorkingDirectory` 指向仓库根目录
- `ExecStart` 使用 Core 生产入口 `python -m service_runtime`
- `EnvironmentFile` 指向服务端 `.env`
- PostgreSQL 连接串通过 `MEETYOU_DATABASE_URL` 注入
- Core Service 持有 Alembic migration 与协议协商主导权

## 4. 验收命令

最小后端验证：

```bash
python -m unittest tests.test_config_manager tests.test_gateway_config_api
```

Docker runtime 自检：

```bash
python scripts/check_core_runtime.py --profile docker --runtime-root deploy/docker/runtime
```

## 5. 模型能力刷新（Context / Output）

V3 起模型 context window 与 max output token 不再只靠 `adapters/base.py` 写死值，改为分层来源：

1. **Provider API 优先**：
   - Gemini: `models.get/list` 读取 `inputTokenLimit` / `outputTokenLimit`
   - Anthropic: Models API 读取 `max_input_tokens` / `max_output_tokens`（或兼容字段）
   - Ollama: `show/model_info` 读取 `context_length` / `num_ctx`
2. **官方文档/版本化 registry 兜底**：
   - DeepSeek 的 `/models` 不返回 token limit，使用官方文档映射（当前 `deepseek-v4-flash/pro`=1M context、384K output，`deepseek-chat/reasoner` 兼容映射到 v4-flash）
   - OpenAI `/models` 字段不足时，使用项目内 `core/model_capabilities/default_registry.json`（来源标注为 models/compare 页面）
3. **最终默认值**：仍保留回退值，但未知模型必须输出 diagnostic 与低置信度标记，禁止静默返回 8192。

运行态缓存：

- 默认缓存 TTL 为 24h（`MEETYOU_MODEL_CAPABILITY_CACHE_TTL_SECONDS` 可调）
- 默认缓存路径：`user/runtime/model_capabilities_cache.json`（不进入 Git 追踪运行态）
- 支持内部刷新方法 `refresh_model_capabilities`，返回来源、旧值、新值、置信度/人工确认标记
