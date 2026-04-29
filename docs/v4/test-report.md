# MeetYou V4 Test Report

Status: local V4 validation, CI, Deploy, remote Core verification, and local Desktop -> remote Core validation passed; external human confirmation pending.

## Build Under Test

- Branch: `main`
- Commit sha: pending final deployed commit update
- Local validation date: 2026-04-29
- Local Core database: `meetyou_v4_local_20260429080852`
- `.env` note: repository `.env` was not edited; local runs used process-level overrides because `.env` mainly points to remote Core.

## Local Automated Tests

- Python tests: passed (`.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`, latest rerun 511 tests, 1 skipped)
- Frontend typecheck: passed (`npm run typecheck`)
- Frontend tests: passed (`npm run test`, 17 files / 71 tests)
- Frontend build: passed (`npm run build`; existing Electron metadata and Vite chunk warnings only)
- Migration tests: passed through full Python discovery (`tests.test_db_bootstrap`, `tests.test_db_phase1`)
- Endpoint protocol tests: passed through full Python discovery (`tests.test_endpoint_provider_protocols`, `tests.test_endpoint_tool_protocol`, gateway runtime tests)
- Scheduler tests: passed through full Python discovery (`tests.test_scheduler_v4`, `tests.test_scheduler_tools_v4`, heartbeat guardrail tests)
- Tool router tests: passed through full Python discovery (`tests.test_tool_router_v4`, `tests.test_tool_runtime`, execution-boundary tests)
- Delivery tests: passed through full Python discovery (`tests.test_delivery_v4`, `tests.test_thread_delivery_bridge`)
- Feishu / MeetWeChat non-streaming duplicate and final-message fallback regression tests: passed (`tests.test_feishu_output_adapter`, `tests.test_feishu_ws_client`, `tests.test_meetwechat_adapter`)

## Local Core + Desktop + UI Real Tests

- Core target: local Core `http://127.0.0.1:8000`, started with `MEETYOU_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/meetyou_v4_local_20260429080852`
- External adapters during local validation: disabled with process env `MEETYOU_FEISHU_ENABLE=false`, `MEETYOU_MEETWECHAT_ENABLE=false`
- Desktop Provider target: local Desktop bridge `http://127.0.0.1:38952`, provider id `local-final-20260429080852`, connected to local Core
- UI target: `http://127.0.0.1:5173`, with `VITE_MEETYOU_DESKTOP_BASE_URL=http://127.0.0.1:38952`
- Endpoint provider registration: passed; `desktop.local-final-20260429080852.ui` and `desktop.local-final-20260429080852.executor` were online, executor exposed `utility.echo`, `file.read`, `file.write`, `shell.exec`, and `workspace.analyze`
- Real acceptance command: passed (`.venv\Scripts\python.exe scripts\v4_real_acceptance.py --base-url http://127.0.0.1:8000 --ui-url http://127.0.0.1:5173 --desktop-tool-endpoint desktop.local-final-20260429080852.executor --json-out logs\v4-local-final-acceptance.json`)
- Latest local acceptance rerun: passed (`logs\v4-local-final-acceptance-rerun.json`, marker `V4OK_20260429003714_359bee`, real Desktop tool marker `DESKTOP_TOOL_20260429003728_6e9894`)
- Unique marker: `V4OK_20260429001701_e294ee`
- Thread / session: passed (`thr_bab0f0552bcd4164bf35b41be52a7862`, `sess_42bf900fa4654eed9f899d4a457d24eb`)
- Streaming: passed (`V4STREAM_20260429001702_b1a8e2`; RunEvent `message.delta` + `message.completed`; persisted assistant message `msg_c0ac554aaeae4da4809589f36fe42a51`)
- Non-streaming final delivery: passed (persisted assistant message `msg_c7528c465014449bb5089aecc09bbcb6`; marker appeared once; exactly one `delivery.message`)
- `assistant.progress_notice`: passed (RunEvent observed before final reply; not persisted as final assistant message)
- ToolRouter synthetic endpoint: passed (`utility.echo`, operation `op_7d029ee1c24f48daa174602689afcd23`)
- Real Desktop tool through ToolRouter + ExecutionTarget: passed (`utility.echo` routed to `desktop.local-final-20260429080852.executor`, operation `op_d63a2f21eece413fb053a4abf4b2b925`, marker `DESKTOP_TOOL_20260429001713_ac1d4f`)
- Scheduler / `system.heartbeat`: passed (`system.heartbeat` interval round-trip, delete rejected, disposable ordinary job `acceptance.v4ok_20260429001701_e294ee` created and deleted)
- Endpoint heartbeat separation: passed (`endpoint.heartbeat` used as connection keepalive only)
- Disconnect / reconnect: passed (durable RunEventLog replay, seq `17`)
- UI stale placeholder: passed (served HTML did not contain “等待后端服务启动后即可使用”)
- Legacy protocol guard: passed (`/client/ws` rejected with HTTP 403 during WebSocket handshake)

## Remote Core Verification

- CI status: passed (`CI`, run `25085307121`, commit `5e09a1c4f0c75b65f5a7f588e4f114cd297afea6`)
- Deploy status: passed (`Deploy MeetYou Core`, run `25085307124`, commit `5e09a1c4f0c75b65f5a7f588e4f114cd297afea6`)
- Remote Core `/health`: passed (`https://core.maziteng.cn/health`, `status=ready`, `live=true`, `ready=true`, `degraded=false`)
- Remote Core version / commit sha: passed (`build_info.git_commit=5e09a1c4f0c75b65f5a7f588e4f114cd297afea6`, `branch=main`, `component=core`, `build_time=2026-04-29T00:48:02Z`)

## Local Desktop -> Remote Core Real Tests

- Desktop Provider target: local bridge `http://127.0.0.1:38953`, provider id `remote-final-20260429085045`, connected to `https://core.maziteng.cn`
- Remote acceptance command: passed (`.venv\Scripts\python.exe scripts\v4_real_acceptance.py --base-url https://core.maziteng.cn --skip-ui --desktop-tool-endpoint desktop.remote-final-20260429085045.executor --json-out logs\v4-remote-final-acceptance.json`)
- Conversation / Streaming / `assistant.progress_notice`: passed (marker `V4OK_20260429005204_b2affb`, streaming marker `V4STREAM_20260429005219_d0b827`, thread `thr_9cd9fef334be4320b9f596e12fcc2465`)
- Real Desktop Provider tool through remote Core: passed (`utility.echo`, target `desktop.remote-final-20260429085045.executor`, operation `op_bf4c160ced1043e4a5190489bd3ef191`, marker `DESKTOP_TOOL_20260429005229_a3937c`)
- Scheduler / Heartbeat / disconnect-reconnect: passed (`system.heartbeat` interval round-trip, disposable ordinary job `acceptance.v4ok_20260429005204_b2affb`, replay seq `15`)

## External Delivery Human Feedback

- Feishu unique real-message test: pending human confirmation
- WeChatBot unique real-message test: pending human confirmation
- 2026-04-29 follow-up: human reported WeChatBot replied but Feishu did not. Remote endpoint diagnostics showed Feishu endpoint was not connected in the live WebSocket manager while WeChatBot was connected. Follow-up fix adds supervised Feishu long-connection reconnect, truthful live endpoint status (`offline` when not connected), and `delivery.message` fallback handling for non-streaming external final replies with message-id de-duplication.
- 2026-04-29 Feishu root-cause follow-up: direct Feishu OpenAPI send to the recorded chat returned success and human confirmed receipt, so Feishu credentials, chat id, and outbound API are valid. A synthetic Feishu-type Endpoint connected to remote Core and received `delivery.run_event` plus `delivery.message`, so Runtime / Message / Delivery fan-out is valid for non-streaming external endpoints. The failure was isolated to Feishu inbound long connection startup.
- Feishu inbound root cause: `lark_oapi` captures an asyncio loop at import time. V4 provider decoupling moved Feishu imports into the async Core lifecycle, so the SDK captured Core's already-running loop and then `client.start()` tried to drive that loop from a worker thread. The fix makes `FeishuWSClient` lazy-load and run the Lark SDK on a provider-owned worker thread with its own event loop, and Runtime now derives source kind from the endpoint provider instead of hardcoding `/runtime/messages` as `web`.
- Feishu local real long-connection probe after the fix: passed; the SDK reached a live `msg-frontier.feishu.cn` WebSocket connection with the repository Feishu credentials. This only verified transport startup and did not assume a user reply was delivered.

## Static V4 Guardrails

- Runtime scan found no active `ClientToolDispatchService`, `source_client_id`, `target_client_id`, directed `short_reply`, `manage_procedures`, `manage_scheduled_tasks`, `core_only`, or `specific_endpoint` usage outside removed-route guards, migrations, tests, and legacy docs.
- UTF-8 / UI text scan found no mojibake markers and no stale startup placeholder. Remaining English matches in UI source are internal logs, test names, type names, or build metadata fields.
- `service_runtime` compatibility path now starts `App.scheduler_processor()` and does not start Heart scheduler / heartbeat loops.
- External Feishu / MeetWeChat provider imports are lazy inside provider startup, so disabled or failing external providers do not block Core import.
