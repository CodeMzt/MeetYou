# ClawBot iLink WeChat Endpoint Provider

This is MeetYou's main WeChat integration path. It is a native Endpoint Provider that talks directly to Tencent's ClawBot iLink HTTP/JSON API.

It must not require a separate bot runtime, CLI, or external state directory. MeetYou stores only its own token, cursor, context token, dedupe state, and Core thread bindings.

## Boundaries

- iLink owns WeChat QR authorization and message transport.
- MeetYou Core owns Thread, Message, Run, Delivery, EndpointAddress records, and final assistant message persistence.
- The provider is under `endpoint_providers/clawbot.py` and connects back to Core through `/endpoint/ws`.
- V1 supports direct/private text only. Group, media, and old MeetWeChat state migration are intentionally out of scope.

## Login

Run login from the MeetYou repo:

```bash
python -m endpoint_providers.clawbot login --enable
```

The command calls:

- `GET /ilink/bot/get_bot_qrcode?bot_type=3`
- `GET /ilink/bot/get_qrcode_status?qrcode=...`

It prints the QR URL and writes the same data to:

```text
user/clawbot-ilink-login-qr.txt
```

After WeChat confirms the QR, the command saves these MeetYou-owned settings:

- `.env`: `MEETYOU_CLAWBOT_ILINK_BOT_TOKEN`
- `user/config.json`: `clawbot_ilink_base_url`, `clawbot_ilink_bot_id`, `clawbot_ilink_user_id`
- `user/clawbot_ilink_state.json`: local cursor/context state

## Run

Production Core deploy installs and restarts the `meetyou-clawbot-wechat-provider` systemd service together with other external providers. After `python -m endpoint_providers.clawbot login --enable`, the next successful Core deploy should start the provider service automatically.

For local development or foreground diagnostics, start Core and the provider separately:

```bash
python -m service_runtime
python -m endpoint_providers.clawbot
```

Required environment/config values:

```env
MEETYOU_CLAWBOT_WECHAT_ENABLE=true
MEETYOU_CLAWBOT_ILINK_BOT_TOKEN=...
MEETYOU_CLAWBOT_ILINK_BASE_URL=https://ilinkai.weixin.qq.com
```

## Runtime Flow

1. The provider long-polls `POST /ilink/bot/getupdates` with MeetYou's stored `get_updates_buf`.
2. Completed direct text messages are converted into MeetYou runtime user messages with `source=wechat` and `transport=clawbot_ilink`.
3. The provider stores the message `context_token` per `(bot_id, peer_id)`.
4. Core persists the user message, runs the assistant turn, and emits delivery frames.
5. The provider sends final assistant text through `POST /ilink/bot/sendmessage` with `to_user_id`, `context_token`, `message_type=2`, `message_state=2`, and a unique `client_id`.

## Acceptance

- `python -m endpoint_providers.clawbot login --enable` completes after a real WeChat QR confirmation.
- `python -m endpoint_providers.clawbot` registers `wechat.clawbot.provider.ui`.
- A private WeChat text message creates or reuses a Core thread.
- The assistant final reply is delivered back through iLink.
- Restarting the provider preserves cursor/context state. If iLink returns session expiry, rerun the MeetYou login command.
