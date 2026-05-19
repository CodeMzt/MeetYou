# ClawBot WeChat Endpoint Provider

This is the main WeChat integration path for MeetYou. It uses Tencent's official ClawBot/OpenClaw WeChat channel as an external Endpoint Provider and keeps MeetYou Core as the owner of Thread, Message, Run, Delivery, and EndpointAddress records.

Legacy `MeetWeChat` / old WeChatBot support remains in the repository only as a failed historical path. New WeChat work should not adapt to its `/v1/events`, ACK, or `chat_id` shape.

## Official Upstream

- Official docs: https://docs.openclaw.ai/channels
- Official package/source: https://github.com/Tencent/openclaw-weixin
- Official npm package: `@tencent-weixin/openclaw-weixin`

Relevant official API surfaces used here:

- `ilink/bot/getupdates`
- `ilink/bot/sendmessage`
- `ilink/bot/getconfig`
- `ilink/bot/msg/notifystart`
- `ilink/bot/msg/notifystop`

## Boundaries

- ClawBot/OpenClaw owns WeChat login and iLink transport.
- MeetYou ClawBot provider owns only local transport state: OpenClaw account discovery, `get_updates_buf`, `context_token`, and dedupe/thread binding state.
- MeetYou Core owns all product truth: threads, messages, runs, delivery, address records, and assistant final messages.
- V1 supports direct/private text messages only. Group behavior, media, and old MeetWeChat state migration are intentionally out of scope.

## Setup

Install and login using the official OpenClaw WeChat channel:

```bash
npx -y @tencent-weixin/openclaw-weixin-cli install
openclaw channels login --channel openclaw-weixin
```

The official login writes account state under `OPENCLAW_STATE_DIR/openclaw-weixin/` or `~/.openclaw/openclaw-weixin/`.

Enable MeetYou's provider:

```env
MEETYOU_CLAWBOT_WECHAT_ENABLE=true
MEETYOU_CLAWBOT_WECHAT_STATE_DIR=
MEETYOU_CLAWBOT_WECHAT_BASE_URL=
MEETYOU_CLAWBOT_WECHAT_STATE_FILE=user/clawbot_wechat_state.json
MEETYOU_CLAWBOT_WECHAT_POLL_TIMEOUT_MS=35000
MEETYOU_CLAWBOT_WECHAT_BOT_AGENT=MeetYou/1.0
```

Then start Core and the external provider separately:

```bash
python -m service_runtime
python -m endpoint_providers.clawbot
```

## Runtime Flow

1. The provider reads official OpenClaw account files from `openclaw-weixin/accounts.json` and `openclaw-weixin/accounts/*.json`.
2. Each account polls `ilink/bot/getupdates` with its stored `get_updates_buf`.
3. Completed direct text messages are converted into MeetYou runtime user messages with `source=wechat` and `transport=clawbot`.
4. Core persists the user message, creates/runs the assistant turn, and emits delivery frames.
5. The provider sends the final assistant text back through `ilink/bot/sendmessage` with the stored `context_token`.

## Acceptance

- Start the official login flow and confirm `openclaw-weixin/accounts.json` contains at least one account id.
- Start `python -m endpoint_providers.clawbot` and confirm it registers `wechat.clawbot.provider.ui`.
- Send a private WeChat text message to the logged-in account.
- Confirm MeetYou persists the user message in the per-conversation Core Thread.
- Confirm the assistant's final text is returned through official ClawBot and no old MeetWeChat process is required.
