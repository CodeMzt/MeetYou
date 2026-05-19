# MeetWeChat

> Legacy note: MeetWeChat / old WeChatBot is kept only as historical failed support. New WeChat development must use the native ClawBot iLink provider documented in `docs/ClawBot_Wechat.md`.

MeetWeChat 是一个 Linux-first 的微信桥接服务。它不做 LLM、不做业务编排、不直接暴露 agent-wechat API，只把真实微信能力整理成稳定的本地 `/v1` HTTP API。

当前真实链路已经在远程 Linux 验证通过：

```text
官方 Linux 微信客户端
  -> agent-wechat sidecar 读取本地消息库 / 执行 UI 发送
  -> MeetWeChat runtime-agent 轮询并落库
  -> 上层应用调用 MeetWeChat /v1 API
```

V0 边界：

- 单账号、单租户。
- 默认只监听 `127.0.0.1`。
- 只支持文本消息。
- 支持私聊入站、私聊出站、群聊入站、群聊出站策略。
- 不支持媒体消息、WebSocket、多消费者游标、多账号、Wayland。
- 不自动回复；上层应用必须自己消费事件并调用发送接口。

## 当前可用能力

已真实验证：

- `GET /v1/health`：检查 MeetWeChat 和 agent-wechat 运行状态。
- `GET /v1/chats`：读取会话列表，返回 MeetWeChat 稳定 `chat_id`。
- `GET /v1/events`：读取未 ACK 的入站文本事件。
- `POST /v1/events/ack`：ACK 已处理事件。
- `POST /v1/messages/text`：发送文本消息。
- `PUT /v1/overrides/{chat_id}`：设置 `manual_only` / `mute` / `read_only`。
- 私聊：入站、ACK、出站发送已通。
- 群聊：会话识别、入站、普通群出站阻断、`is_group_mention=true` 允许出站、`manual_only` 阻断已通。

仍需后续扩展：

- 真实 `@我` 入站是否由 agent-wechat 自动标为 `is_group_mention=true` 还需要继续适配更多真实字段。
- 服务重启后的真实 dedup/idempotency 长周期回归建议纳入夜间 E2E。
- 当前不内置自动回复逻辑。

## 部署后调用方式

默认地址：

```text
http://127.0.0.1:38961
```

所有接口都在 `/v1` 下。当前默认依赖本机访问控制，不建议开放公网。如果要给其他机器访问，应放在内网反向代理后，并自行加认证、限流和审计。

通用约定：

- 请求和响应均为 JSON。
- `chat_id` 是 MeetWeChat 生成的不透明稳定 ID，形如 `aw:<hash>`。
- 上层应用不要解析 `chat_id`，只应原样保存和传回。
- `message_id` 是 best-effort，不能作为唯一业务事实来源。
- 发送接口必须提供 `idempotency_key`。
- 不要在日志里记录 token、完整聊天正文、真实联系人名、完整 agent-wechat 原始 JSON。

推荐业务流程：

```text
1. GET /v1/health
2. GET /v1/events
3. 对每条事件执行业务逻辑
4. 如果需要回复，POST /v1/messages/text
5. 处理完成后 POST /v1/events/ack
```

## API 文档

### GET /v1/health

检查服务和 runtime 状态。

```bash
curl -sS http://127.0.0.1:38961/v1/health | python3 -m json.tool
```

示例响应：

```json
{
  "status": "ok",
  "wechat_process_alive": true,
  "desktop_alive": true,
  "scanner_alive": true,
  "dispatcher_alive": true,
  "last_inbound_at": "2026-04-25T10:00:00Z",
  "last_outbound_at": "2026-04-25T10:01:00Z",
  "mode": "healthy",
  "backend": "agent_wechat"
}
```

关键字段：

- `backend`: 当前 runtime，真实部署应为 `agent_wechat`。
- `mode`: `healthy` / `degraded` / `manual_only` / `offline`。
- `wechat_process_alive=false`: agent-wechat 或微信进程不可用。
- `desktop_alive=false`: sidecar 可达，但微信登录态或自动化状态异常。

### GET /v1/chats

读取会话列表。

```bash
curl -sS http://127.0.0.1:38961/v1/chats | python3 -m json.tool
```

示例响应：

```json
{
  "items": [
    {
      "chat_id": "aw:09380d17dcb036fc4128064d",
      "chat_type": "private",
      "display_name": "联系人显示名",
      "platform_id": "agent-wechat-upstream-id",
      "last_seen_at": "2026-04-25T10:00:00Z",
      "last_processed_message_id": null
    }
  ]
}
```

注意：

- `display_name` 可能包含真实联系人名，业务日志里应脱敏。
- `platform_id` 目前会在 API 响应中出现，后续可能进一步收敛；上层业务不要依赖它。
- `chat_type` 为 `private` 或 `group`。

安全查看会话数量：

```bash
TMP_JSON="$(mktemp)"
curl -fsS -o "${TMP_JSON}" http://127.0.0.1:38961/v1/chats

python3 - "${TMP_JSON}" <<'PY'
import json, sys
p=json.load(open(sys.argv[1]))
items=p.get("items", [])
print("chat_count=", len(items))
print("group_count=", sum(1 for item in items if item.get("chat_type") == "group"))
PY

rm -f "${TMP_JSON}"
```

### GET /v1/events

读取未 ACK 的入站事件。

参数：

- `limit`: 默认 `20`，范围 `1..100`。
- `cursor`: 上一页最后一个 `event_id`，用于翻页。

```bash
curl -sS 'http://127.0.0.1:38961/v1/events?limit=20' | python3 -m json.tool
```

示例响应：

```json
{
  "items": [
    {
      "event_id": "evt-1fc756b352ce",
      "message_id": "2",
      "chat_id": "aw:af4726a1743d27b935c2642a",
      "chat_type": "private",
      "sender_id": "sender-upstream-id",
      "sender_name": "发送者显示名",
      "is_self": false,
      "is_group_mention": false,
      "content_type": "text",
      "text": "消息正文",
      "attachments": [],
      "timestamp": "2026-04-25T10:00:00Z",
      "raw_hash": "sha256:...",
      "dedup_key": "mid:2"
    }
  ],
  "next_cursor": "evt-1fc756b352ce"
}
```

注意：

- 当前只接收文本事件。
- 非文本消息会被跳过。
- `is_self=true` 的消息会被跳过，不进入事件队列。
- 事件在 ACK 前会一直保留为 pending。
- 不要把完整 `text` 打到业务日志。

安全查看事件摘要：

```bash
TMP_JSON="$(mktemp)"
curl -fsS -o "${TMP_JSON}" http://127.0.0.1:38961/v1/events

python3 - "${TMP_JSON}" <<'PY'
import json, sys
p=json.load(open(sys.argv[1]))
items=p.get("items", [])
print("event_count=", len(items))
for event in items[:5]:
    print({
        "event_id": event.get("event_id"),
        "chat_id": event.get("chat_id"),
        "chat_type": event.get("chat_type"),
        "text_len": len(event.get("text") or ""),
        "is_group_mention": event.get("is_group_mention"),
    })
PY

rm -f "${TMP_JSON}"
```

### POST /v1/events/ack

ACK 已处理事件。

```bash
curl -sS -X POST http://127.0.0.1:38961/v1/events/ack \
  -H 'Content-Type: application/json' \
  -d '{"event_ids":["evt-1fc756b352ce"]}' | python3 -m json.tool
```

示例响应：

```json
{
  "acked": 1
}
```

语义：

- ACK 是幂等的。
- 第一次 ACK 返回 `acked: 1`。
- 重复 ACK 同一个事件返回 `acked: 0`。
- 建议在业务逻辑和发送动作完成后再 ACK。

### POST /v1/messages/text

发送文本消息。

私聊示例：

```bash
curl -sS -X POST http://127.0.0.1:38961/v1/messages/text \
  -H 'Content-Type: application/json' \
  -d '{
    "chat_id": "aw:af4726a1743d27b935c2642a",
    "text": "收到",
    "idempotency_key": "reply-20260425-001"
  }' | python3 -m json.tool
```

成功响应：

```json
{
  "ok": true,
  "command_id": "cmd-...",
  "status": "sent",
  "message_id": "agent-wechat-message-id",
  "detail": null
}
```

幂等规则：

- `idempotency_key` 必填。
- 同一个 `idempotency_key` + 同一 payload 重复请求，会返回同一命令结果。
- 同一个 `idempotency_key` + 不同 payload，会返回 blocked。

冲突示例：

```json
{
  "ok": false,
  "command_id": "cmd-...",
  "status": "blocked",
  "message_id": null,
  "detail": "idempotency key conflict: request payload mismatch"
}
```

### 群聊发送策略

V0 默认要求群聊回复必须显式传 `is_group_mention=true`。这是为了避免普通群消息触发误回复。

普通群发送会被阻断：

```bash
curl -sS -X POST http://127.0.0.1:38961/v1/messages/text \
  -H 'Content-Type: application/json' \
  -d '{
    "chat_id": "aw:group-chat-id",
    "text": "这条不应该发送",
    "idempotency_key": "group-block-001"
  }' | python3 -m json.tool
```

预期：

```json
{
  "ok": false,
  "status": "blocked",
  "detail": "group message requires @mention"
}
```

群聊 `@我` 回复由上层显式声明：

```bash
curl -sS -X POST http://127.0.0.1:38961/v1/messages/text \
  -H 'Content-Type: application/json' \
  -d '{
    "chat_id": "aw:group-chat-id",
    "text": "收到群@测试",
    "idempotency_key": "group-mention-001",
    "is_group_mention": true
  }' | python3 -m json.tool
```

预期：

```json
{
  "ok": true,
  "status": "sent"
}
```

### PUT /v1/overrides/{chat_id}

设置人工接管或静默策略。

支持模式：

- `manual_only`: 禁止自动出站。
- `mute`: 禁止自动出站。
- `read_only`: 只读，不允许出站。

示例：

```bash
CHAT_ID="aw:group-chat-id"

curl -sS -X PUT "http://127.0.0.1:38961/v1/overrides/${CHAT_ID}" \
  -H 'Content-Type: application/json' \
  -d '{"mode":"manual_only","reason":"human takeover"}' | python3 -m json.tool
```

响应：

```json
{
  "chat_id": "aw:group-chat-id",
  "mode": "manual_only",
  "reason": "human takeover",
  "expires_at": null
}
```

被 override 阻断的发送响应：

```json
{
  "ok": false,
  "status": "blocked",
  "detail": "chat override active: manual_only"
}
```

## 完整调用示例

下面是一个最小“读事件 -> 回复 -> ACK”的 shell 示例。生产业务应改成自己的服务代码。

```bash
EVENT_JSON="$(mktemp)"
curl -fsS -o "${EVENT_JSON}" http://127.0.0.1:38961/v1/events

EVENT_ID="$(python3 - "${EVENT_JSON}" <<'PY'
import json, sys
p=json.load(open(sys.argv[1]))
print(p["items"][0]["event_id"] if p.get("items") else "")
PY
)"

CHAT_ID="$(python3 - "${EVENT_JSON}" <<'PY'
import json, sys
p=json.load(open(sys.argv[1]))
print(p["items"][0]["chat_id"] if p.get("items") else "")
PY
)"

if [ -n "${EVENT_ID}" ] && [ -n "${CHAT_ID}" ]; then
  curl -sS -X POST http://127.0.0.1:38961/v1/messages/text \
    -H 'Content-Type: application/json' \
    -d "{
      \"chat_id\": \"${CHAT_ID}\",
      \"text\": \"收到\",
      \"idempotency_key\": \"reply-${EVENT_ID}\"
    }" | python3 -m json.tool

  curl -sS -X POST http://127.0.0.1:38961/v1/events/ack \
    -H 'Content-Type: application/json' \
    -d "{\"event_ids\":[\"${EVENT_ID}\"]}" | python3 -m json.tool
fi

rm -f "${EVENT_JSON}"
```

## 真实部署入口

远程 Linux 真实部署细节见：

- [docs/runbooks/linux-runtime.md](E:/Documents/Project/MeetWeChat/docs/runbooks/linux-runtime.md)
- [docs/runbooks/codex-remote-linux.md](E:/Documents/Project/MeetWeChat/docs/runbooks/codex-remote-linux.md)

关键命令摘要：

```bash
cd /opt/meetwechat
sudo bash scripts/linux/bootstrap_agent_wechat.sh
sudo usermod -aG docker wechatbot
sudo su - wechatbot
wx up
wx auth login --timeout 300
```

扫码成功后，回到 sudo-capable 用户导出 token：

```bash
sudo install -d -o wechatbot -g wechatbot -m 0700 /home/wechatbot/.config/meetwechat
sudo su - wechatbot -c 'wx auth token' \
  | tr -d '\r\n' \
  | sudo tee /home/wechatbot/.config/meetwechat/agent-wechat-token >/dev/null
sudo chown wechatbot:wechatbot /home/wechatbot/.config/meetwechat/agent-wechat-token
sudo chmod 0600 /home/wechatbot/.config/meetwechat/agent-wechat-token
```

## 本地开发与验证

本地 Windows / Codex cloud 默认使用 fake runtime，不依赖真实微信。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e .[dev]
.\.venv\Scripts\python -m ruff check src tests
.\.venv\Scripts\python -m pyright
.\.venv\Scripts\python -m pytest tests/unit tests/contract tests/integration
```

Docker fake smoke：

```powershell
docker compose -f deploy/docker/docker-compose.fake.yml up --build -d
docker compose -f deploy/docker/docker-compose.fake.yml logs api
docker compose -f deploy/docker/docker-compose.fake.yml down -v
```

## 安全要求

- 不要把 `127.0.0.1:6174` 或 `127.0.0.1:38961` 直接暴露到公网。
- 不要上传 agent-wechat token。
- 不要上传完整 `/api/chats`、`/api/messages`、`/v1/events` JSON。
- CI artifact 不应包含聊天正文、联系人名、token、SQLite 快照中的敏感数据。
- 如果必须远程访问 API，应通过内网/VPN/SSH tunnel，并在上层加认证。
