# MeetYou V4 Test Report

Status: local V4 validation, CI, Deploy, remote Core verification, local Desktop -> remote Core validation, and external Feishu / WeChatBot human confirmation passed.

## 2026-04-29 V4 Optimization / External Provider Deploy Addendum

- Commit sha: `82bdb8849915451baf85f6a641a1b10e92162f3d`
- Scope: implemented the V4 optimization batch for reasoning controls, markdown-aware endpoint delivery, thread-first UI, Delivery Outbox, ToolRouter cache/batch routing, namespaced RuntimeStateStore, and external Feishu / WeChatBot Endpoint Provider decoupling. Follow-up deploy fixes added provider systemd units and made Core deploy restart optional external providers without blocking Core.
- Local focused backend tests: passed (`.venv\Scripts\python.exe -m unittest tests.test_endpoint_provider_protocols tests.test_config_manager tests.test_meetwechat_adapter tests.test_feishu_output_adapter`, 66 tests).
- Local compile check: passed (`.venv\Scripts\python.exe -m compileall clients core sensors endpoint_providers`).
- CI status: passed (`CI`, run `25110659977`, commit `82bdb8849915451baf85f6a641a1b10e92162f3d`).
- Deploy status: passed (`Deploy MeetYou Core`, run `25110659925`, commit `82bdb8849915451baf85f6a641a1b10e92162f3d`).
- Remote Core `/health`: passed (`https://core.maziteng.cn/health`, `status=ready`, `ready=true`, `degraded=false`, `build_info.git_commit=82bdb8849915451baf85f6a641a1b10e92162f3d`, `branch=main`, `build_time=2026-04-29T13:07:43Z`).
- Remote endpoint status after deploy: `desktop.mzt-desktop-client.executor` online, `desktop.mzt-desktop-client.ui` online, `feishu.provider.ui` online, and `wechat.provider.ui` online.
- Remote Core + local Desktop real acceptance: passed (`logs\v4-remote-provider-deploy-acceptance.json`, marker `V4OK_20260429130949_3a305f`, streaming marker `V4STREAM_20260429130949_7b2f81`, real Desktop tool marker `DESKTOP_TOOL_20260429130956_1443d7`, replay seq `17`).
- Root cause for Feishu / WeChatBot no-response report: V4 correctly removed external adapter startup from Core lifecycle, but deployment still only restarted `meetyou-core.service`; therefore external provider processes were offline. The first deploy follow-up installed provider systemd units, the second added non-interactive sudo, and the third aligned provider `User/Group` with the running Core service user.
- External human feedback: passed. Human sent `FEISHU_PROVIDER_20260429_2111` and `WECHAT_PROVIDER_20260429_2111`; both Feishu and WeChatBot returned automatic replies.

## 2026-04-29 ToolRouter Core Tool / Feishu Root-Cause Addendum

- Commit sha: `3546f8fbce8f4102091105bac98bceea43038327`
- Scope: fixed the V4 upper/lower contract mismatch where assistant-visible Core-owned tools such as `send_delivery_message`, `list_delivery_targets`, and `create_scheduled_workflow` were declared but not registered as `core.local` in-process ToolRouter targets. Local Shell/file capabilities remain excluded and must still route through Desktop Endpoint execution targets.
- Root cause: Feishu Provider startup was already fixed in commit `829dd5741333eb6985edf00ace0175ec29827`; the remaining failure surfaced a second root cause: ToolRouter could not execute non-`core.*` Core tools and returned `execution_target_unavailable`.
- Python tests: passed (`.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`, 530 tests, 1 skipped).
- Frontend typecheck: passed (`npm run typecheck`).
- Frontend tests: passed (`npm run test`, 17 files / 71 tests).
- Frontend build: passed (`npm run build`; existing Electron author, Vite CJS, and chunk-size warnings only).
- CI status: passed (`CI`, run `25102124569`, commit `3546f8fbce8f4102091105bac98bceea43038327`).
- Deploy status: passed (`Deploy MeetYou Core`, run `25102124602`, commit `3546f8fbce8f4102091105bac98bceea43038327`).
- Remote Core `/health`: passed (`https://core.maziteng.cn/health`, `status=ready`, `ready=true`, `degraded=false`, `build_info.git_commit=3546f8fbce8f4102091105bac98bceea43038327`, `build_time=2026-04-29T09:50:15Z`).
- Remote endpoint status after deploy: `feishu.provider.ui` online, `wechat.provider.ui` online, and local `desktop.mzt-desktop-client.executor` online against remote Core.
- Remote Core + local Desktop real acceptance: passed (`logs\v4-remote-toolrouter-corefix-acceptance.json`, marker `V4OK_20260429095334_d00df3`, streaming marker `V4STREAM_20260429095335_fd3c43`, real Desktop tool marker `DESKTOP_TOOL_20260429095342_61e2ee`, replay seq `16`).
- ToolRouter Core tool probe: passed. `list_delivery_targets` executed through `/runtime/operations` as `core.local`, operation `op_231f292f111444c58f3abd16fb29df94`.
- Feishu address delivery probe: passed. `send_delivery_message` executed through `/runtime/operations` as `core.local`, operation `op_00a246211b48488cba56fecaabca4a6b`, marker `FEISHU_CORE_DELIVERY_20260429_1753`.
- External human feedback: passed. Human confirmed the Feishu validation was OK after the `FEISHU_CORE_DELIVERY_20260429_1753` probe and the Feishu inbound auto-reply check. WeChatBot remained OK as the comparison endpoint.
- `.env.bak` handling: inspected, removed from Git tracking, and explicitly ignored. The working-tree `.env.bak` contains non-placeholder API keys, tokens, passwords, and a database URL, so the local file must remain untracked.
- Deploy follow-up: push `886415bff5812046a85dbde1dacf609e7b2b85fc` passed CI but remote Deploy run `25102849096` failed because the remote working tree still had local changes in the formerly tracked `.env.bak`. The deploy workflow now preserves the remote local `.env.bak` outside the repository pull, lets Git remove it from tracking, then restores it as an ignored local file without printing or committing its contents.
- Deploy workflow verification: passed after the cleanup fix. Commit `78d5a1cd75212220052dcda9c686cecb21d0cb8a` passed CI run `25103120214` and Deploy run `25103120218`. Remote Core `/health` returned `status=ready`, `ready=true`, `degraded=false`, and `build_info.git_commit=78d5a1cd75212220052dcda9c686cecb21d0cb8a`.

## 2026-04-29 EndpointAddress / Scheduled Delivery Addendum

- Commit sha: `cbba889fdb11cc820697460074b68831de0e606d`
- Scope: added `EndpointAddress`, `ActorDeliveryPreference`, address-targeted Delivery payloads, provider address frames, persistent Scheduler due/lease fields, and high-level assistant tools `list_delivery_targets`, `set_delivery_preference`, `send_delivery_message`, `create_scheduled_delivery`, and `manage_scheduled_deliveries`.
- CI status: passed (`CI`, run `25096453118`, branch `main`, push at `2026-04-29T07:31:36Z`).
- Deploy status: passed (`Deploy MeetYou Core`, run `25096453071`, branch `main`, push at `2026-04-29T07:31:36Z`).
- Remote Core `/health`: passed (`https://core.maziteng.cn/health`, `status=ready`, `live=true`, `ready=true`, `build_info.git_commit=cbba889fdb11cc820697460074b68831de0e606d`, `branch=main`, `build_time=2026-04-29T07:32:05Z`).
- Python tests: passed (`.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`, 523 tests, 1 skipped).
- Frontend typecheck: passed (`npm run typecheck`).
- Frontend tests: passed (`npm run test`, 17 files / 71 tests).
- Frontend build: passed (`npm run build`; existing Electron metadata and Vite chunk warnings only).
- Endpoint protocol tests: passed for `endpoint.addresses.snapshot`, `endpoint.address.upsert`, `endpoint.address.delete`, and address-targeted delivery payloads (`tests.test_endpoint_address_v4`, full discovery).
- Scheduler tests: passed for daily/cron/one-shot calculation, persistent due fields, system heartbeat guardrails, and scheduled delivery tool creation (`tests.test_schedule_time_v4`, `tests.test_scheduler_tools_v4`, full discovery).
- Delivery tests: passed for `send_delivery_message` through `EndpointAddress` and non-streaming Feishu/MeetWeChat duplicate suppression. Address-targeted frames are handled by provider-level connections; chat-scoped thread subscriptions ignore address-targeted frames to avoid duplicate sends.
- Remote Core real acceptance: passed with proxy bypass (`NO_PROXY=core.maziteng.cn,127.0.0.1,localhost`; `.venv\Scripts\python.exe scripts\v4_real_acceptance.py --base-url https://core.maziteng.cn --skip-ui --json-out logs\v4-remote-endpoint-address-scheduled-delivery-acceptance.json`).
- Remote acceptance marker: `V4OK_20260429074025_65ec6d`; streaming marker `V4STREAM_20260429074026_69812a`; thread `thr_b0b4cbeffe994aa1872f685c777d56b5`; ToolRouter operation `op_c331d467fed34c25907f770cce29490e`; replay seq `15`.
- Local Desktop -> remote Core: not rerun in this addendum because no desktop provider endpoint was supplied to the acceptance command; previous real Desktop validation remains recorded below.
- Feishu / WeChatBot human confirmation: not rerun in this addendum. Previous human-confirmed external results remain recorded below; this addendum adds automated regression coverage for the Feishu/MeetWeChat non-streaming duplicate path and address-targeted provider delivery.

## Build Under Test

- Branch: `main`
- Functional fix commit sha: `376ff4ce85efa7bb844acd2a67c55b814f9605e5`
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

- CI status: passed (`CI`, run `25089783209`, commit `376ff4ce85efa7bb844acd2a67c55b814f9605e5`)
- Deploy status: passed (`Deploy MeetYou Core`, run `25089783172`, commit `376ff4ce85efa7bb844acd2a67c55b814f9605e5`)
- Remote Core `/health`: passed (`https://core.maziteng.cn/health`, `status=ready`, `live=true`, `ready=true`, `degraded=false`)
- Remote Core version / commit sha: passed (`build_info.git_commit=376ff4ce85efa7bb844acd2a67c55b814f9605e5`, `branch=main`, `component=core`, `build_time=2026-04-29T03:43:15Z`)

## Local Desktop -> Remote Core Real Tests

- Desktop Provider target: local bridge `http://127.0.0.1:38954`, provider id `remote-hotfix-20260429094734`, connected to `https://core.maziteng.cn`
- Remote acceptance command: passed with local proxy bypass (`NO_PROXY=core.maziteng.cn,127.0.0.1,localhost`; `.venv\Scripts\python.exe scripts\v4_real_acceptance.py --base-url https://core.maziteng.cn --skip-ui --desktop-tool-endpoint desktop.remote-hotfix-20260429094734.executor --json-out logs\v4-remote-feishu-loopfix-acceptance.json`)
- Conversation / Streaming / `assistant.progress_notice`: passed (marker `V4OK_20260429035007_92927e`, streaming marker `V4STREAM_20260429035009_de4258`, thread `thr_5f379c36d5e748fea1909ff5496d404a`)
- Real Desktop Provider tool through remote Core: passed (`utility.echo`, target `desktop.remote-hotfix-20260429094734.executor`, operation `op_da45a75ee8594df7ad1e4776140675d4`, marker `DESKTOP_TOOL_20260429035017_035cc0`)
- Scheduler / Heartbeat / disconnect-reconnect: passed (`system.heartbeat` interval round-trip, disposable ordinary job `acceptance.v4ok_20260429035007_92927e`, replay seq `14`)

## External Delivery Human Feedback

- Feishu unique real-message test: passed. Direct prompt marker `FEISHU_FIX_20260429_115118`; human confirmed receiving MeetYou's automatic reply after replying in Feishu.
- WeChatBot unique real-message test: passed by human feedback during the same external validation pass; human reported WeChatBot was responding while Feishu was the remaining failing channel.
- 2026-04-29 follow-up: human reported WeChatBot replied but Feishu did not. Remote endpoint diagnostics showed Feishu endpoint was not connected in the live WebSocket manager while WeChatBot was connected. Follow-up fix adds supervised Feishu long-connection reconnect, truthful live endpoint status (`offline` when not connected), and `delivery.message` fallback handling for non-streaming external final replies with message-id de-duplication.
- 2026-04-29 Feishu root-cause follow-up: direct Feishu OpenAPI send to the recorded chat returned success and human confirmed receipt, so Feishu credentials, chat id, and outbound API are valid. A synthetic Feishu-type Endpoint connected to remote Core and received `delivery.run_event` plus `delivery.message`, so Runtime / Message / Delivery fan-out is valid for non-streaming external endpoints. The failure was isolated to Feishu inbound long connection startup.
- Feishu inbound root cause: `lark_oapi` captures an asyncio loop at import time. V4 provider decoupling moved Feishu imports into the async Core lifecycle, so the SDK captured Core's already-running loop and then `client.start()` tried to drive that loop from a worker thread. The fix makes `FeishuWSClient` lazy-load and run the Lark SDK on a provider-owned worker thread with its own event loop, and Runtime now derives source kind from the endpoint provider instead of hardcoding `/runtime/messages` as `web`.
- Feishu local real long-connection probe after the fix: passed; the SDK reached a live `msg-frontier.feishu.cn` WebSocket connection with the repository Feishu credentials. This only verified transport startup and did not assume a user reply was delivered.

## Static V4 Guardrails

- Runtime scan found no active `ClientToolDispatchService`, `source_client_id`, `target_client_id`, directed `short_reply`, `manage_procedures`, `manage_scheduled_tasks`, `core_only`, or `specific_endpoint` usage outside removed-route guards, migrations, tests, and legacy docs.
- UTF-8 / UI text scan found no mojibake markers and no stale startup placeholder. Remaining English matches in UI source are internal logs, test names, type names, or build metadata fields.
- `service_runtime` compatibility path now starts `App.scheduler_processor()` and does not start Heart scheduler / heartbeat loops.
- External Feishu / MeetWeChat provider imports are lazy inside provider startup, so disabled or failing external providers do not block Core import.
