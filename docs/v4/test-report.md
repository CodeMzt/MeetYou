# MeetYou V4 Test Report

Status: local V4 validation, CI, Deploy, and remote Core verification passed for the latest deploy. Latest WeChatBot human confirmation is still pending a fresh user-sent WeChat marker.

## 2026-04-30 Desktop Reply Control / Heartbeat Streaming Addendum

- Functional commit sha: `de103e1957dd564ad2ce3dcd0a48d01e3107a225`.
- Scope: restored Desktop UI `stop` / `regenerate` reply controls by adding the V4 Runtime HTTP entrypoint `POST /runtime/sessions/{session_id}/reply-control` and proxying it through `/desktop/sessions/{session_id}/reply-control`. The UI no longer sends bare control payloads over `/endpoint/ws`, avoiding `expected meetyou.endpoint.ws.v4` endpoint-frame errors.
- Heartbeat UI fix: Desktop chat state now treats `heartbeat`, `initializing`, and `shutting_down` as non-streaming statuses for existing assistant turns, so heartbeat output does not leave the UI stuck in an output state.
- Local focused backend test: passed (`.venv\Scripts\python.exe -m unittest tests.test_gateway_runtime_api`, 15 tests).
- Local frontend typecheck: passed (`npm run typecheck`).
- Local frontend tests: passed (`npm run test`, 21 files / 87 tests).
- Local desktop rebuild: passed in order (`scripts\build-desktop-backend.ps1 -SkipInstall`, then `npm run build`). Backend executable: `meetyou-ui\resources\desktop-backend\desktop_client\desktop_client.exe`; installer: `meetyou-ui\release\MeetYou Setup 1.0.0.exe`.
- CI status: passed (`CI`, run `25165729420`, commit `de103e1957dd564ad2ce3dcd0a48d01e3107a225`).
- Deploy status: passed (`Deploy MeetYou Core`, run `25165729374`, commit `de103e1957dd564ad2ce3dcd0a48d01e3107a225`).
- Remote Core `/health`: passed (`https://core.maziteng.cn/health`, `status=ready`, `ready=true`, `degraded=false`, `build_info.git_commit=de103e1957dd564ad2ce3dcd0a48d01e3107a225`, `branch=main`, `build_time=2026-04-30T12:37:47Z`).
- Local Desktop -> remote Core real acceptance: not rerun for this focused UI/runtime control fix.
- External Feishu / WeChatBot human confirmation: not rerun for this focused UI/runtime control fix.

## 2026-04-30 Endpoint Thread Deletion Rebind Addendum

- Commit sha: `53cfdb5545dabdc8c116eb9b152b3fe746da2801`.
- Scope: fixed endpoint-owned conversation recovery after a user deletes the Core thread for a WeChat/Feishu external conversation. The shared `GatewayConversationClient` now detects stale `thread_id/session_id` errors, clears the cached context, reconnects the endpoint subscription, re-resolves `/runtime/endpoint-sessions/resolve`, and retries the inbound message once.
- Root cause: Core binding resolution already created a new thread when an `EndpointThreadBinding` pointed to a deleted thread, but long-lived provider clients kept the old in-memory `thread_id/session_id` and skipped re-resolution because the old WebSocket subscription was still marked acknowledged. New messages were therefore posted to a deleted thread and failed before a new binding could be created.
- MeetWeChat-specific cache fix: after a rebind, MeetWeChat now writes the new Core `thread_id` back to its compatibility state cache so a provider restart does not resurrect the deleted thread id.
- Runtime API fix: `/runtime/messages`, `/runtime/sessions`, thread message listing, and operation creation now return controlled `thread_not_found` errors for missing/deleted threads instead of leaking an unclassified KeyError path.
- Local focused backend tests: passed (`.venv\Scripts\python.exe -m unittest tests.test_gateway_client tests.test_endpoint_thread_binding tests.test_gateway_runtime_api tests.test_meetwechat_adapter tests.test_feishu_input_adapter`, 68 tests).
- Local frontend typecheck: passed (`npm run typecheck`).
- Local compile check: passed (`.venv\Scripts\python.exe -m compileall clients gateway sensors`).
- Local desktop rebuild: passed in order (`scripts\build-desktop-backend.ps1`, then `npm run build`). Local installer regenerated at `meetyou-ui\release\MeetYou Setup 1.0.0.exe`.
- CI status: passed (`CI`, run `25161423286`, commit `53cfdb5545dabdc8c116eb9b152b3fe746da2801`).
- Deploy status: passed (`Deploy MeetYou Core`, run `25161423322`, commit `53cfdb5545dabdc8c116eb9b152b3fe746da2801`).
- Remote Core `/health`: passed (`https://core.maziteng.cn/health`, `status=ready`, `ready=true`, `degraded=false`, `build_info.git_commit=53cfdb5545dabdc8c116eb9b152b3fe746da2801`, `branch=main`, `build_time=2026-04-30T10:52:32Z`).
- Desktop Release status: passed (`Desktop Release`, run `25161526477`, artifact `meetyou-windows-desktop`, artifact id `6728438937`, size `231613199` bytes).
- External WeChatBot human confirmation: pending. User should delete a WeChat private/group thread in Desktop, send a fresh message in that same WeChat conversation, and confirm that a new Core thread appears and a real WeChat reply is received.

## 2026-04-30 SKILL Core Storage Boundary Addendum

- Functional commit sha: `dfea137e0059d63224212335871dc5aeb5d75b0a`.
- Scope: corrected SKILL storage semantics so Desktop treats SKILL list/detail records as remote Core state, removed the stale local `open-local-path` SKILL path IPC, added `storage_ref` (`core://skills/...`) for SKILL list/detail payloads, stopped exposing Core filesystem paths through public `storage_path`, and moved created/managed SKILL files to the Core runtime skill store (`created_skill_dir`, default `user/skills`) instead of the built-in `prompt/SKILL` package directory.
- Local backend focused tests: passed (`.venv\Scripts\python.exe -m unittest tests.test_assistant_modes tests.test_scenario_tools tests.test_gateway_config_api tests.test_desktop_agent_ui_bridge tests.test_tools_manager_browser_guard tests.test_tool_runtime`, 79 tests).
- Local frontend typecheck: passed (`npm run typecheck`).
- Local frontend tests: passed (`npm run test`, 21 files / 86 tests).
- Real Settings/SKILL window visual QA: passed (`npm run visual:settings-skill`). The check opened a real frameless Electron Settings window at `560x660` and `560x620`, covered config top, directory picker, SKILL list, and SKILL detail states, and reported no missing visible text, no horizontal overflow, and no clipped controls.
- Visual QA evidence: screenshots were generated under `%TEMP%\meetyou-settings-skill-visual\`, including `settings-default-skills-list-560x660.png` and `settings-minimum-skill-detail-560x620.png`; manual inspection confirmed SKILL list/detail show `core://skills/reusable/task_recognition` and no `E:\...` local path.
- Desktop build: passed (`npm run build`); installer regenerated at `meetyou-ui\release\MeetYou Setup 1.0.0.exe`.
- CI status: passed (`CI`, run `25155924106`, commit `dfea137e0059d63224212335871dc5aeb5d75b0a`).
- Deploy status: passed (`Deploy MeetYou Core`, run `25155924083`, commit `dfea137e0059d63224212335871dc5aeb5d75b0a`).
- Remote Core `/health`: passed (`https://core.maziteng.cn/health`, `status=ready`, `ready=true`, `degraded=false`, `build_info.git_commit=dfea137e0059d63224212335871dc5aeb5d75b0a`, `branch=main`).
- Remote SKILL API probe: passed. `GET /operator/skills?skill_type=reusable&query=task_recognition` and `GET /operator/skills/task_recognition` returned `storage_ref=core://skills/reusable/task_recognition`, empty `storage_path`, and detail content.
- Remote V4 real acceptance without UI: passed (`logs\v4-remote-skill-boundary-acceptance.json`, marker `V4OK_20260430084321_6881e9`, streaming marker `V4STREAM_20260430084322_35c806`, replay seq `15`).
- Local Desktop Provider -> remote Core real acceptance: passed (`logs\v4-remote-skill-boundary-desktop-acceptance.json`, provider `desktop.remote-skill-boundary-20260430164437.executor`, marker `V4OK_20260430084534_652e71`, real Desktop tool marker `DESKTOP_TOOL_20260430084541_89bc28`, replay seq `14`).
- External Feishu / WeChatBot human confirmation: not rerun for this SKILL storage-boundary correction.

## 2026-04-30 Main Chat UI Ordering / Context Popover Addendum

- Local commit: the main chat UI fix commit containing this addendum.
- Scope: fixed the dynamic-island context popover being clipped in the transformed top dock by rendering the popover through a body portal with viewport-bounded sizing, removed the hidden scroll anchor that created reply-tail whitespace, moved the invisible regenerate action bar out of normal layout so it no longer creates a fake blank line at the end of assistant replies, normalized leading/trailing assistant display blank lines, and made user sends optimistic so assistant streaming events can no longer appear above the user message when WebSocket events beat the HTTP response.
- Follow-up root cause: the portal regression fix still gated the popover on `usageSnapshot.usage_ready=true`, so real sessions with usage data still syncing toggled local click state without rendering any details window. The follow-up fix renders the popover on click even when usage is pending or absent, shows a Chinese syncing state, and gives the body-portal popover the global dropdown z-index.
- Frontend typecheck: passed (`npm run typecheck`).
- Frontend focused tests: passed (`npm run test -- --run chatState displayText UsagePanel`, 3 files / 17 tests).
- Frontend full tests: passed (`npm run test`, 20 files / 84 tests).
- Real UI visual QA: passed (`npm run visual:chat-ui`). The check opens the real Electron main window through Vite, uses a local mock Desktop HTTP/WebSocket backend, now defaults to `usage_ready=false` to cover the real pending-usage click regression, reproduces the race where assistant stream frames arrive before the delayed user-message HTTP response, captures a `360x520` dynamic-island popover state and a `400x620` post-send chat state, and verifies no popover clipping, Chinese pending-usage copy, correct user-before-assistant order, no trailing rendered blank node, `0px` bottom margin for a single-paragraph assistant reply, and padding-only assistant text-to-bubble bottom spacing.
- Visual QA evidence: screenshots were generated under `%TEMP%\meetyou-chat-ui-visual\`, including `main-narrow-island-open-360x520.png` and `main-chat-after-send-400x620.png`; the latest inspected report recorded `visualUsageReady=false`, popover bounds `left=20 top=92 right=340 bottom=235` in a `360x520` viewport, `clipped=false`, Chinese text `上下文统计同步中`, user index `0`, assistant index `1`, and assistant bottom gap `16px`.
- Local only: backend, CI, Deploy, remote Core, local Desktop against remote Core, and Feishu/WeChatBot human confirmation were not rerun for this UI-only batch.

## 2026-04-30 Endpoint Handler Registry / ToolRouter Scoring / Workspace Routing Governance Addendum

- Local commits: `503290a1` (`refactor endpoint frame handling`), `bef25146` (`feat tool router endpoint scoring`), and the final workspace routing governance commit containing this addendum.
- Scope: split `/endpoint/ws` into a frame handler registry, made capability snapshots replace old capability state, routed tool result/error updates through ToolRouter, added real-time endpoint scoring with operation routing metadata, persisted heartbeat/routing metrics in endpoint metadata, exposed workspace routing governance through Operator PATCH and UI controls, and added real Electron window visual QA for the workspace governance surface.
- This addendum records the final Operator/API/UI governance phase plus cross-phase verification.
- Backend focused tests: passed (`.venv\Scripts\python.exe -m unittest tests.test_tool_router_v4 tests.test_endpoint_protocol_v4 tests.test_endpoint_address_v4 tests.test_endpoint_tool_protocol tests.test_operator_workspace_governance`, 20 tests).
- Backend full discovery: passed after isolating an environment-sensitive provider URL fallback assertion from local `MEETYOU_CORE_BASE_URL` (`.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`, 579 tests, 1 skipped).
- Frontend typecheck: passed (`npm run typecheck`).
- Frontend focused tests: passed (`npm run test -- --run WorkspaceGovernanceEditor WorkspacePanel runtimeApi`, 3 files / 21 tests).
- Frontend full tests: passed (`npm run test`, 20 files / 82 tests).
- Real UI visual QA: passed (`npm run visual:workspace-governance`). The check opens the real Electron workspace route through Vite with mocked workspace sync data, captures `560x700` and `520x620` windows, and verifies top, governance upper, and governance lower scroll states for no horizontal overflow, no clipped controls, and required visible text.
- Visual QA evidence: screenshots were generated under `%TEMP%\meetyou-workspace-governance-visual\`, including `workspace-default-top-560x700.png`, `workspace-default-governance-560x700.png`, `workspace-default-governance-lower-560x700.png`, `workspace-minimum-top-520x620.png`, `workspace-minimum-governance-520x620.png`, and `workspace-minimum-governance-lower-520x620.png`.
- Evaluation vs real-window difference: SSR component tests proved text/payload rendering but did not catch actual click target height. The first real-window run failed because approval buttons rendered at 19px high; the UI was fixed with a stable `28px` minimum button height. The visual checker was also expanded from broad text presence to separate scroll-state screenshots so parent-container text does not create false confidence about below-fold form visibility.
- Local only: CI, Deploy, remote Core `/health`, local Desktop against remote Core, and Feishu/WeChatBot human confirmation were not rerun for this local implementation batch.

## 2026-04-30 Provider Thread / ThreadPicker Visual QA Addendum

- Commit sha: `46d07effe91c98e73f047b82ce4dc2cc7d82424a`
- Scope: stopped provider-only Feishu / MeetWeChat registration clients from resolving user-visible Core threads, hid historical provider management threads from the runtime thread picker, and fixed the ThreadPicker dropdown / delete confirmation modal layout for narrow desktop windows.
- Root cause for standalone `MeetWeChat Provider` / `Feishu Provider` threads: provider-level address/capability registration reused `GatewayConversationClient.start()` with thread binding enabled, so `/runtime/endpoint-sessions/resolve` created `shared_endpoint` Core threads even though these were management connections rather than user conversations. Provider registration now uses `bind_thread=false`; per-person/per-group external chats continue to use endpoint-owned `conversation_key` thread resolution.
- UI root cause: ThreadPicker and ConfirmModal were rendered under the top dock, whose transformed/fixed layout made viewport positioning differ from ordinary browser validation. Both controls now portal to `document.body`; the dropdown is clamped against the actual viewport, and the delete modal no longer leaves the dropdown visible behind it.
- Actual-window visual QA: passed against Electron main-window dimensions from `meetyou-ui/electron/main.ts`, including the default `400x620` window and minimum `340x460` window. Checks covered menu bounds, delete icon visibility, full wrapping of long thread detail text, modal centering, footer buttons, and no modal overflow.
- Local focused backend tests: passed (`.venv\Scripts\python.exe -m unittest tests.test_gateway_client tests.test_meetwechat_adapter tests.test_feishu_input_adapter`, 47 tests).
- Local frontend typecheck: passed (`npm run typecheck`).
- Local focused frontend tests: passed (`npm run test -- --run ThreadPicker threadPresentation`, 2 files / 3 tests).
- Local desktop rebuild: passed in the correct order (`scripts\build-desktop-backend.ps1` first, then `npm run build` so the Electron installer includes the regenerated desktop backend). Local installer path: `meetyou-ui\release\MeetYou Setup 1.0.0.exe`.
- CI status: passed (`CI`, run `25143441597`, commit `46d07effe91c98e73f047b82ce4dc2cc7d82424a`).
- Deploy status: passed (`Deploy MeetYou Core`, run `25143441584`, commit `46d07effe91c98e73f047b82ce4dc2cc7d82424a`).
- Remote Core `/health`: passed (`https://core.maziteng.cn/health`, `status=ready`, `ready=true`, `degraded=false`, `build_info.git_commit=46d07effe91c98e73f047b82ce4dc2cc7d82424a`, `branch=main`, `build_time=2026-04-30T01:59:50Z`).
- Desktop Release status: passed (`Desktop Release`, run `25143542163`, artifact `meetyou-windows-desktop`, artifact id `6721516126`, size `231604874` bytes).
- External WeChatBot human confirmation: not rerun in this addendum. The previous requested marker `WX_REAL_20260430_0756_12B533` remains pending until a fresh user-sent WeChat message is observed and confirmed.

## 2026-04-30 Endpoint Tool Catalog / WeChat Delivery Fix Addendum

- Commit sha: `12b5335876f102e92e7ca9b1ab3ae348350bcc73`
- Scope: documented and implemented Endpoint Tool Catalog registration through `endpoint.capabilities.snapshot`, endpoint-owned thread binding through `/runtime/endpoint-sessions/resolve`, contextual endpoint tool auto-injection, MeetWeChat / Feishu provider conversation-key session resolution, UI delete confirmation styling and force-delete behavior, and MeetWeChat `guarded_auto` real-send delivery behavior.
- Root cause for the latest WeChat no-send report: MeetWeChat inbound messages and assistant replies were persisted in Core, but `guarded_auto` was not treated as an allowed outbound send mode by `MeetWeChatProxyPolicy.allow_send()`. The provider could therefore show the assistant reply in the Core thread while not actually calling the MeetWeChat sidecar send endpoint.
- Local focused backend tests: passed (`.venv\Scripts\python.exe -m unittest tests.test_meetwechat_adapter tests.test_feishu_output_adapter tests.test_gateway_client tests.test_endpoint_thread_binding tests.test_gateway_runtime_api tests.test_tool_runtime`, 82 tests).
- Local frontend typecheck: passed (`npm run typecheck`).
- Local focused frontend tests: passed (`npm run test -- --run ThreadPicker useEndpointContext`, 2 files / 4 tests).
- Local full frontend tests: passed earlier in the same change batch (`npm run test`, 20 files / 82 tests).
- Local full backend discovery: attempted earlier in the same change batch and timed out after 5 minutes without failure output; focused protocol/runtime/provider coverage above passed.
- CI status: passed (`CI`, run `25139807849`, commit `12b5335876f102e92e7ca9b1ab3ae348350bcc73`).
- Deploy status: passed (`Deploy MeetYou Core`, run `25139807858`, commit `12b5335876f102e92e7ca9b1ab3ae348350bcc73`).
- Remote Core `/health`: passed (`https://core.maziteng.cn/health`, `status=ready`, `ready=true`, `degraded=false`, `build_info.git_commit=12b5335876f102e92e7ca9b1ab3ae348350bcc73`, `branch=main`, `build_time=2026-04-29T23:49:14Z`).
- Remote endpoint status after deploy: `feishu.provider.ui` online and `wechat.provider.ui` online in workspace `personal`; deploy logs also show `meetyou-feishu-provider.service` and `meetyou-meetwechat-provider.service` restarted as running.
- Remote V4 real acceptance: passed with proxy bypass (`NO_PROXY=core.maziteng.cn,127.0.0.1,localhost`; `.venv\Scripts\python.exe scripts\v4_real_acceptance.py --base-url https://core.maziteng.cn --skip-ui`).
- Remote acceptance marker: `V4OK_20260429235343_731152`; streaming marker `V4STREAM_20260429235344_36106f`; thread `thr_8db99b5850b8440a9ff9abfffa6dd331`; ToolRouter operation `op_1adfa63b3149430aa7c6de4e55798242`; replay seq `15`.
- WeChatBot human confirmation: pending. Requested human marker `WX_REAL_20260430_0756_12B533`; a 4-minute remote thread poll did not observe that marker, so no fresh WeChat human receipt can be claimed yet.

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
