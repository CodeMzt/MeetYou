# MeetYou V3 Bot Integration

## 1. 目的

本文档定义 V3 `Phase 3` 的 Bot 接入真源边界。当前范围仅包含基于官方 WeChat iLink / OpenClaw Weixin channel 的 `WeChat Bot`。

本轮文档收口目标：

- 明确 `Phase 3` 不再包含 QQ 相关接入范围
- 将 WeChat Bot 默认方案切换为官方 iLink 路径
- 约束 WeChat Bot 与现有 Core / Client / Agent 主链的集成方式
- 为后续 `F330` - `F332` 的实现与验收提供统一口径

## 2. 参考来源

当前方案以官方路径为准，`docs/wechatbot.txt` 仅作为本仓库内的方案草案参考。

- OpenClaw WeChat channel docs: `https://docs.openclaw.ai/channels/wechat`
- Tencent OpenClaw Weixin plugin: `https://github.com/Tencent/openclaw-weixin`
- iLink protocol reference: `https://www.wechatbot.dev/en/protocol`
- Local draft: `docs/wechatbot.txt`

关键事实：

- WeChat 接入由 `@tencent-weixin/openclaw-weixin` 外部 channel plugin 承担，OpenClaw Core 本身保持 channel-agnostic。
- 官方插件负责二维码登录、Tencent iLink API 调用、媒体上传下载、`context_token` 与账号监控。
- iLink 使用扫码登录获取 `bot_token`，业务请求使用 `AuthorizationType: ilink_bot_token`、`Authorization: Bearer <bot_token>` 与随机 `X-WECHAT-UIN`。
- 入站消息通过 `POST /ilink/bot/getupdates` 长轮询获取，不是 WebSocket 或第三方 callback。
- 出站消息通过 `POST /ilink/bot/sendmessage` 发送，回复必须携带入站消息中的 `context_token`。

## 3. 范围收口

### 3.1 In Scope

- 基于官方 iLink 的 WeChat Bot 接入设计
- 二维码登录、凭证持久化、会话恢复与过期重登策略
- `getupdates` 长轮询到正式 `Client API + GET /client/ws` 主链的桥接
- `sendmessage` 文本回复回发与 `context_token` 缓存
- 最小文本闭环、去重、自发消息过滤、确认/补充输入语义
- 后续图片、文件、语音、视频等媒体能力的扩展边界

### 3.2 Out Of Scope

- QQBot 或任何 QQ 平台接入
- 继续维护第三方个人微信协议适配器
- 在同一轮需求里同时铺开多 Bot 平台抽象
- 绕过正式 Client 面，直接把 Bot 逻辑塞进 Core 内部私有链路
- 把本地文件、Shell、桌面能力等 Desktop Agent 职责混入 Bot 适配层

## 4. 架构方向

WeChat Bot 仍是外部客户端入口，不改变 `Core Service`、`desktop-agent`、`edge-agent` 的发布边界。

推荐主链：

1. `WeChat iLink transport` 通过二维码登录取得 `bot_token` 与账号标识
2. `WeChatLongPoller` 调用 `POST /ilink/bot/getupdates` 长轮询入站消息
3. `WeChatInputAdapter` 将 `WeixinMessage` 标准化为 MeetYou 输入事件
4. 桥接层复用正式 `Client API + GET /client/ws` 与 Core 建立会话
5. Core 继续沿用现有模式、会话、工具与附件处理主链
6. `WeChatOutputService` 调用 `POST /ilink/bot/sendmessage` 回发文本或后续媒体消息

## 5. 模块边界

- `WeChatSessionManager`
  - 负责 `GET /ilink/bot/get_bot_qrcode?bot_type=3`
  - 负责 `GET /ilink/bot/get_qrcode_status?qrcode=...`
  - 保存 `bot_token`、`ilink_bot_id`、`ilink_user_id`、`baseurl`
  - 遇到 `errcode=-14` 或会话失效时清理凭证并重新登录
- `WeChatLongPoller`
  - 负责 `POST /ilink/bot/getupdates`
  - 持久化并原样传回 `get_updates_buf`
  - 按服务端返回的 `longpolling_timeout_ms` 调整下一轮超时
  - 失败时使用低频 backoff，避免高频打满 iLink 服务
- `WeChatInputAdapter`
  - 过滤机器人自身消息
  - 识别文本 `MessageItem.type=1`
  - 将 `from_user_id`、`session_id`、`message_id`、`context_token` 写入 metadata
  - 通过 `GatewayConversationClient` 复用正式 Client 主链
- `WeChatOutputService`
  - 生成唯一 `client_id`
  - 构造 `message_type=2`、`message_state=2` 的 Bot 回复
  - 从缓存读取目标用户最新 `context_token`
  - 对长文本做自然边界分片
- `ContextTokenStore`
  - 缓存并持久化 `(account_id, from_user_id) -> context_token`
  - 会话过期或重新登录时清理旧 token
  - 禁止跨用户、跨账号复用 token

## 6. 协议约束

- 默认 base URL 为 `https://ilinkai.weixin.qq.com`，但登录成功后必须优先使用返回的 `baseurl`
- 所有业务 POST 请求都应包含：
  - `Content-Type: application/json`
  - `AuthorizationType: ilink_bot_token`
  - `Authorization: Bearer <bot_token>`
  - `X-WECHAT-UIN: <base64(random_uint32_as_decimal_string)>`
- 所有 iLink 请求还应按官方插件线携带 `iLink-App-Id: bot` 与 `iLink-App-ClientVersion`
- 请求体需要包含 `base_info.channel_version`，默认按当前官方插件线使用 `2.1.7`
- 首次拉取消息时 `get_updates_buf` 为空字符串
- 每次 `getupdates` 返回的新 `get_updates_buf` 是不透明游标，必须原样保存并传回
- 每条回复必须携带入站消息里的 `context_token`
- `ret=0` 表示成功；`errcode=-14` 表示会话过期，需要清理状态并重新扫码

## 7. Feature 对应关系

### F330 WeChat iLink Transport 接入骨架

状态：已落地最小文本闭环骨架，待真实扫码联调。

目标：

- 删除旧第三方微信 transport 方案
- 已建立 iLink client、session manager 与 long poller
- 已最小支持二维码登录状态机、凭证保存、长轮询、文本发送
- 已将运行态配置限定为 iLink 所需字段

建议配置：

- `enable_wechat_bot`
- `wechat_ilink_base_url`
- `wechat_ilink_channel_version`
- `wechat_ilink_token_file`
- `wechat_ilink_qr_output_path`
- `wechat_ilink_poll_timeout_ms`

密钥与登录凭证不进入普通 `user/config.json`；`bot_token` 等运行凭证写入受限权限的 token file 或后续加密状态后端。

### F331 Bot -> Client 主链桥接

状态：已落地最小桥接骨架，待真实微信消息验收。

目标：

- 每个微信用户以 `wechat:account:{ilink_bot_id}:user:{from_user_id}` 作为稳定会话键
- 入站文本已通过 `GatewayConversationClient` 进入正式 Client 主链
- `message_id` 或 `(seq, session_id, create_time_ms)` 已作为幂等键候选
- metadata 保留 `context_token` 是否存在、`from_user_id`、`session_id`、`ilink_user_id`

### F332 Bot 交互语义补齐

状态：已落地文本、去重、`context_token` 与交互请求骨架，待真实闭环验收。

首期完成判定仍以文本闭环为准：

- 已忽略机器人自身消息
- 已做入站消息去重
- 已支持文本回复回发
- 已支持长文本分片
- 已支持 `errcode=-14` 会话过期清理并重新扫码
- 已支持最小 `confirm` / `human input` 交互桥接

后续扩展：

- 图片、文件、语音、视频需要补 CDN 上传下载、AES-128-ECB 加解密与附件桥接
- typing 状态可通过 `getconfig` + `sendtyping` 增强长任务体验
- 群聊当前不作为承诺能力，需等官方能力元数据明确后再扩展

## 8. 当前任务清单

- [x] `Task 1` 建立 `bot-integration.md` 真源文档，并将 `Phase 3` 范围收口为仅支持 `WeChat Bot`
- [x] `Task 2` 确认官方 iLink / OpenClaw Weixin channel 是新的默认方案
- [x] `Task 3` 删除旧第三方微信接入方案的代码、脚本、配置项与文档说明
- [x] `Task 4` 结合官方说明与 `docs/wechatbot.txt` 重写 Phase 3 设计口径
- [x] `Task 5` 实现 iLink session manager、long poller、input adapter 与 output service
- [x] `Task 6` 使用真实扫码登录完成文本闭环联调

## 9. High-Frequency Send/Receive Optimization

The iLink Bot is still a Core-side external client adapter. It does not move into Desktop Agent and it still enters MeetYou through the formal Client API plus `GET /client/ws`.

Runtime behavior for frequent send/receive:

- `getupdates` remains a single long-poll stream, but returned messages are normalized and placed into an inbound queue before processing.
- Inbound workers process different WeChat users concurrently while each `(account_id, from_user_id)` remains ordered by a per-conversation lock.
- `get_updates_buf`, `context_token`, and the dedupe window are kept in memory and flushed to the state file on a short debounce window, with forced flush on credential/session changes and shutdown.
- Outbound replies from `/client/ws` callbacks are queued instead of awaiting `sendmessage` directly, so slow iLink sends do not block the client websocket read loop.
- Outbound sends keep per-user order, apply a conservative global send interval, and retry transient send failures a small number of times.

Default knobs:

- `wechat_ilink_inbound_worker_count=4`
- `wechat_ilink_inbound_queue_size=500`
- `wechat_ilink_outbound_worker_count=2`
- `wechat_ilink_outbound_queue_size=500`
- `wechat_ilink_outbound_min_interval_ms=250`
- `wechat_ilink_send_timeout_ms=10000`
- `wechat_ilink_state_flush_interval_ms=500`
- `wechat_ilink_gateway_client_idle_ttl_seconds=600`

## 10. 验收提示

实现完成前只承诺设计已收口，不承诺微信消息真实可用。

最小验收矩阵应覆盖：

- 单测：iLink headers、二维码登录状态机、`get_updates_buf` 持久化、`context_token` 缓存、文本 `sendmessage` body
- 集成：长轮询消息进入 `Client API + GET /client/ws`
- 真链路：微信扫码登录、向 Bot 发文本、MeetYou 回复文本
- 失效恢复：模拟 `errcode=-14` 后清理 token、游标与 context token
- 安全：日志、错误、测试快照不泄露 `bot_token`、二维码 token、`context_token`

## 11. 真实联调记录

### 2026-04-22

- 已确认旧第三方微信路径不再作为 MeetYou 方案继续推进
- 已将 Phase 3 设计改为官方 iLink / OpenClaw Weixin channel 路径
- 已删除旧 transport、callback、Docker 服务、验收脚本与测试文件
- 已实现 iLink client、状态文件、长轮询输入适配器、`sendmessage` 输出服务与配置 schema
- 新增单测覆盖 headers/body、状态持久化、入站桥接、出站 `context_token` 文本回复
- 已修复 iLink `ilink_user_id` 误判为 bot 自身消息导致入站消息被过滤的问题；`ilink_user_id` 表示扫码用户，只应过滤 `ilink_bot_id` 与 `@im.bot` 自身账号
- 已在 Windows 本机通过 `python -m service_runtime` + Docker PostgreSQL + 官方 iLink 完成真实扫码登录与文本闭环联调
- 验收消息：用户向 Bot 发送 `测试：ping`，日志确认 iLink 入站文本进入 `Client API + GET /client/ws` 主链，用户确认微信侧收到正常回复
- 当前 Phase 3 最小文本闭环已完成；媒体附件、群聊与 typing 状态仍按后续扩展项处理
