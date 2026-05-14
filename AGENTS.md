# AGENTS

## V5 Architecture Rules

- V5 extends the Core-owned Runtime + Endpoint Provider boundary from V4 unless a task explicitly says to redesign that boundary.
- `research` is a public assistant mode in V5. Do not normalize `research` to `general`; legacy `normal` / `auto` / `documents` / `study` still normalize according to the public contract.
- Project is a user work container, not the same thing as Workspace. Workspace remains the governance, permissions, endpoint, and execution boundary.
- Core owns Project / ProjectSource / Artifact / ResearchTask / ThreadBranch / ConversationCheckpoint.
- Endpoint Providers may expose local research/file/search capabilities, but they must not own project source truth, artifact metadata, conversation branches, or checkpoints.
- Deep research must use read-only evidence gathering unless the user explicitly asks for a separate write action.
- V5 Deep Research execution is externalized through the `research_adapter` HTTP service by default. Runtime and assistant `manage_research_tasks(action="run")` should call Core `ResearchExecutionService` with `ResearchAdapterConfig.from_env()`; Core still owns `ResearchTask`, evidence ledger normalization/safety, Artifact records, delivery messages, and checkpoints.
- Deep Research execution is paused in the default product path because the self-maintained adapter is not stable enough for user-facing delivery. Keep `ResearchTask` / Artifact schemas and optional adapter code for future vendor or explicitly enabled deployments, but hide default desktop research entry points and return a structured disabled response unless `MEETYOU_RESEARCH_ENABLED=true`.
- External research providers, including GPT Researcher and future Open Deep Research adapters, must not write MeetYou DB rows or own ProjectSource/Artifact truth. They only return a report, sources, progress/status, and provider metadata through the adapter contract.
- Project-source-only research tasks may complete inside the external adapter without launching GPT Researcher when the source policy explicitly includes project sources, has no web/search seeds, and has an empty `source_adapters` list. This still counts as externalized execution; Core must continue to own persistence and artifact truth.
- If the external research adapter is required but not configured or returns no citeable sources, Core must fail the ResearchTask with structured metadata instead of falling back to a low-quality uncited internal report. Internal read-only gathering is only a deliberate development/test fallback when external adapter requirement is disabled.
- Research reports must persist as Artifacts; final assistant messages should summarize and link to artifacts instead of embedding large report files.
- Research report PDF/DOCX exports are derived Core Artifact records. Keep Markdown as the primary report artifact, store derivatives through ArtifactStore bytes, and expose them through artifact APIs / task metadata instead of embedding files in messages.
- Completed ResearchTasks bound to a thread should persist an assistant Message containing only a short summary and artifact link(s), then attach that message to the active conversation branch so automatic checkpoints still apply.
- Desktop Markdown rendering must route Core artifact download links (`/runtime/artifacts/{artifact_id}/download` or `/desktop/artifacts/{artifact_id}/download`) through the authenticated desktop artifact download path. Do not leave report artifact links as unauthenticated ordinary navigation.
- Project settings UI must edit Core Project title/description/instructions through project APIs. Do not store project instructions in frontend-only state or Workspace governance fields.
- Project context injection is Core-owned. Ordinary turns in project threads should receive bounded Project title/description/instructions/source snapshots from Core; clients must not assemble hidden project prompts themselves.
- Research panel source/progress UI must display Core `ResearchTask` evidence, summary, and artifact metadata. Do not fabricate source lists from frontend-only plan state.
- Research panel external-service UI must display Core `ResearchTask.metadata.research_provider`, `external_run_id`, `adapter_status`, and `adapter_error` when present. Do not hide adapter failures behind a generic failed state.
- Desktop research UX is chat-native in V5: do not mount a standalone `ResearchPanel` above the message list. Research mode treats the first user message as the thread-bound topic, the assistant replies with an editable/confirmable plan, and live Core/adapter progress appears as a compact assistant-style status bubble in the current thread.
- Runtime must enforce the chat-native research plan gate in `/runtime/messages`, not rely on prompt compliance alone. A research-mode user topic creates a thread-bound planned `ResearchTask` plus an assistant plan-confirmation message and suppresses the normal LLM queue; an explicit confirmation such as “确认开始” starts the task and persists a start message in the same thread.
- Desktop UI thread/project actions must wait for any pending endpoint initialization before creating or switching Core contexts. A delayed default-thread initialization must never overwrite a user-selected thread, especially before the research plan-confirm-start flow.
- GPT Researcher progress granularity is provider-limited. Surface real adapter stages, run events, provider/status, elapsed time, source counts, artifacts, and errors; do not invent per-source or chain-of-thought progress that the adapter did not return.
- Research evidence audit UI must expose Core ledger rank, quality score, duplicate merge count/source ids, verification status, and source trust when those fields are present; do not hide ranking/dedupe/safety metadata behind artifact downloads only.
- Project source UI may create user note sources through Core `/projects/{project_id}/sources`, save message snapshots through `/sources/from-message`, and delete sources through `DELETE /projects/{project_id}/sources/{source_id}`. Delete means archive the ProjectSource record; never delete the original message or artifact. All mutation paths must reload Core source records instead of keeping frontend-only source truth.
- Research runner stage UI must read Core state: compact `ResearchTask.metadata.progress` / `progress_events` plus durable ResearchTask RunEvents when available. Do not model research stage progress as frontend-only state.
- Core-generated ResearchTask plans must be Chinese-first and editable before start. Plans should expose research questions, source strategy, quality gates, deliverables, and an explicit user-confirmation step rather than only a minimal step list. Use `quality_gates[].id="citation_guard"` for citation validation and `approval.editable_before_start=true` for pre-start editing.
- Desktop Research UI must auto-refresh visible `running` ResearchTask state on a short bounded interval and refresh project artifacts when running tasks leave the active state. Do not require users to manually click refresh to track ordinary research progress.
- Research panel web controls must write `source_policy.web_search`, optional `source_policy.web_queries`, and optional `source_policy.web_urls` into Core ResearchTask creation. If web search is disabled and no seed URLs are provided, omit the `web` adapter instead of creating a guaranteed `WebSeedUrlsRequired` task.
- Research panel default UI must not expose academic adapter chips. External research providers own ordinary web/academic discovery; Core academic adapters (`arxiv`, `openalex`, `crossref`, `semantic_scholar`) remain a development fallback or future advanced provider-level constraint, not default visible controls.
- Research panel export controls must write optional `source_policy.derived_formats` into Core ResearchTask creation. Do not represent PDF/DOCX export selection only as frontend state.
- Core `web` research gathering supports direct seed URLs and governed `search_web` discovery. Search-result-only entries are discovery seeds, not verified evidence; reports may cite them only after Core has a readable source summary or direct fetch evidence in the ResearchTask evidence ledger.
- Project artifact UI must list/download Core Artifact records through artifact APIs. Do not infer the project artifact list only from visible ResearchTask state.
- Evidence-ledger citations must refer to recorded sources. Do not invent citations or cite unread sources as verified.
- Core research runner must deduplicate and rank gathered evidence before report synthesis. Final citation ids must come from the final ranked evidence ledger, not from pre-dedup gather order.
- Research evidence text is untrusted by default. Evidence ledger entries must mark sources as evidence-only and instruct downstream synthesis to ignore instructions embedded in webpages, project sources, search results, or academic records.
- Starting a V5 ResearchTask may trigger the external research adapter through Core. If no readable/citeable evidence is returned, fail the task instead of producing an uncited report.
- Desktop-created V5 ResearchTasks must bind to the current Core Thread and the visible research panel must list only that thread's tasks. Project sources and artifacts may remain project-scoped; active research task state is thread-scoped.
- Core must not cancel external deep research solely because a fixed total timeout elapsed. Start the external adapter run, persist `external_run_id`, poll status/progress durably, and cancel only on explicit ResearchTask cancellation or terminal adapter failure.
- Transient research adapter poll failures should remain running until the configured poll-error budget is exhausted. Use `MEETYOU_RESEARCH_POLL_MAX_ERRORS` and `MEETYOU_RESEARCH_POLL_ERROR_GRACE_SECONDS`; do not fail a long research run after only a few temporary connection errors.
- Default thread titles such as `新会话`, `桌面聊天`, `Desktop Chat`, and `Untitled` should be automatically replaced from the first persisted user message by a deterministic local title. Do not overwrite user/manual titles.
- V5 research assistant tools (`search_academic_sources`, `create_research_task`, `manage_research_tasks`) must stay registered in Core and exposed in `user/tools.example.json`; research mode prompts must not name tools that are missing public schemas.
- V5 project assistant tools (`manage_projects`, `manage_project_sources`) must stay registered in Core, exposed in `user/tools.example.json`, and included in assistant mode tool bundles where project/thread/source context can be managed. Do not leave Project capabilities available only through direct Runtime UI/API paths.
- Research tools must not silently drop invalid bindings. If `project_id` or `thread_id` is supplied and unknown, return a structured not-found error instead of creating or listing unscoped tasks.
- Starting a V5 ResearchTask through Runtime must bind it to a Core Run and durable `research.*` RunEvents. Research progress APIs should support resume-style reads by `after_seq` instead of relying only on frontend polling state.
- V5 ResearchTask cancellation is cooperative but durable: once a task is `cancelled`, the runner must stop at the next stage/source boundary, record cancelled progress, and avoid creating report artifacts or delivery messages.
- Conversation checkpoint restore and checkout are non-destructive. Do not delete old messages when switching branch/checkpoint.
- Core must create automatic conversation checkpoints when persisted messages advance a thread leaf. Checkout should not depend on users manually creating checkpoints.
- Historical edit retry creates a new message revision and branch. Do not overwrite the original message content.
- Historical edit retry may use the current active Runtime session as a same-thread fallback when the original user message lacks `session_id`; reject fallback sessions from other threads instead of queueing a replay into the wrong thread.
- V5 visible thread history must be projected by Core from `Thread.current_leaf_message_id` through `Message.parent_message_id`. Frontend branch/checkpoint controls must reload Core history after restore/checkout instead of hiding messages locally.
- V5 branch UI should derive active branch, compact tree, path, and sibling variants from Core branch records (`metadata.is_active`, `parent_branch_id`). Do not create separate frontend-only retry tree state.
- V5 branch tree activation must call Core branch activation APIs, then reload Core history/version state. Do not switch branches by locally filtering message arrays.
- V5 message-level restore/checkout must target the Core automatic checkpoint whose `message_id` matches the message. Do not implement message-level restore by local UI filtering.
- V5 desktop UI text should be Chinese by default. At the 400x620 Electron size, preserve the original titlebar tools as visible, non-overlapping, clickable controls: pin, memory graph, workspace, Danxi, context/usage, developer tools, settings, minimize, and close.
- The V5 Project / Thread / Branch / Source / Artifact dock must not cover or replace the original titlebar. Keep it to one compact row in the chat surface; do not add controls that wrap into another row or steal unnecessary chat vertical space.
- Core-generated V5 titles that can surface in desktop UI, including default branch, automatic checkpoint, checkout branch, edit-retry branch, and project source snapshot titles, must use Chinese fallbacks unless an explicit user-provided title is passed.

## V4 Architecture Rules

- V4 is a development-period replacement, not a V3 compatibility layer.
- Core owns Thread / Message / Run / Scheduler / Heartbeat / Memory / Operation / Delivery.
- Client is only Endpoint Provider. Desktop, Edge, Feishu, WeChatBot, webhook, email, and similar surfaces provide endpoints; they do not own conversations, runs, scheduler state, heartbeat, memory, operations, or delivery semantics.
- Endpoint represents a Provider runtime and its connection/capability health. Provider-internal destinations such as Feishu chats and WeChat private/group chats are `EndpointAddress` records, not separate Clients.
- Actor-to-channel routing uses explicit `ActorDeliveryPreference` bindings. The alias `me` must resolve through an actor binding; if no binding exists, the assistant must ask the user to choose/confirm a delivery address.
- Core is not Client. `core.local` is an in-process `ExecutionTarget`, not a Client. Core-owned endpoints such as `core.local`, `core.scheduler`, `core.inbox`, and `core.notification` are runtime targets inside Core.
- Scheduler is the only system-level scheduling clock.
- `system.heartbeat` is a Scheduler-owned system preset Job. It is non-deletable, can be enabled or disabled, and can have its interval changed.
- Heart may execute a single `system.heartbeat` run when Scheduler calls it, but Heart must not own a repeating scheduler or heartbeat clock. `service_runtime` compatibility paths must start `App.scheduler_processor()`, not Heart scheduler / heartbeat loops.
- `endpoint.heartbeat` is connection keepalive only. It must not trigger `system.heartbeat`.
- `short_reply` is no longer a directed tool. Replace it with `assistant.progress_notice` RunEvent / Runtime Action.
- `assistant.progress_notice` must not go through ToolRouter, must not create Operation / OperationCall, and must not become final assistant message content.
- Delivery is responsible for delivering `message`, `run_event`, `notice`, and `operation_update`. Delivery must not generate replies.
- Cross-provider human-visible delivery must target `EndpointAddress` through Delivery. Do not expand `send_endpoint_message` into a cross-channel user delivery abstraction; use `send_delivery_message` or Scheduled Workflow delivery outputs.
- Final assistant reply must be an assistant Message persisted by MessageService.
- Streaming must flow through RunEventLog plus Delivery fan-out.
- Tool dispatch must flow through ToolRouter plus ExecutionTarget.
- `exec_core_cmd` is the only explicit Core-host shell exception. It runs on the Core Service host through `core.local`, is exposed as a default/basic assistant tool when enabled, must stay behind the Core command whitelist policy, and must not be generalized into Core-owned local file, workspace, or local MCP execution.
- `exec_sys_cmd` remains the Desktop/Endpoint-side shell tool and must continue to require an EndpointCapability such as `shell.exec`.
- Permissions live on Actor / Workspace / RunPolicy. Execution ability lives on EndpointCapability.
- V4 HTTP facade is `/runtime/*`; local Desktop `/desktop/*` may proxy to `/runtime/*`, `/operator/*`, or `/developer/*`, never to old `/client/*`.
- Do not keep `/client/ws`, `source_client_id`, `target_client_id`, or `ClientToolDispatchService` compatibility paths.
- Runtime assistant modes are `general`, `automation`, `research`, and `danxi`. Legacy `normal` / `auto` / `documents` / `study` inputs normalize to `general`; legacy `office` normalizes to `automation`. Do not persist or expose `normal` / `office` as runtime modes.
- Procedure is removed in V4. Do not reintroduce Procedure API, table, tool, prompt layer, pinned Procedure fields, or UI. Reusable workflow guidance must use SKILL.
- SKILL is the only reusable workflow guide layer. Public workflow discovery and authoring go through `list_skills`, `load_skill`, and `create_skill`; skill lookup must match titles, summaries, scenarios, and recommended tools; capability exposure flows through `CapabilityRegistry`, semantic routing, ToolRouter, and ExecutionTarget.

## Raspberry Pi Endpoint Provider Rules

- Raspberry Pi 5 / Linux ARM64 support is an Endpoint Provider only. Do not turn it into Core and do not let it own Thread, Message, Run, Scheduler, `system.heartbeat`, Memory, Delivery, Operation records, ToolRouter, or persistence.
- Raspberry Pi provider work lives under `endpoint_providers/raspberry_pi/`, with docs in `docs/endpoints/raspberry-pi.md`, `docs/endpoints/rpi-capabilities.md`, `docs/endpoints/rpi-security.md`, `docs/endpoints/rpi-operations.md`, and real hardware acceptance records under `docs/endpoints/rpi-real-acceptance-*.md`.
- The Pi must actively connect to Core through `GET /endpoint/ws` using `meetyou.endpoint.ws.v4`; do not add an inbound Pi server or revive `/client/ws`.
- Pi executable tools must be advertised as EndpointCapability snapshots and executed only from Core-routed `tool.call.request` frames. Results must return through `tool.call.accepted` / `tool.call.progress` / `tool.call.result` / `tool.call.error`.
- `endpoint.heartbeat` from the Pi is connection keepalive only and must not trigger Scheduler-owned `system.heartbeat`.
- GPIO and shell capabilities must be deny-by-default: no GPIO outside `security.gpio_allowed_pins`, no arbitrary shell strings, no `shell=True`, and `rpi.shell.safe_exec` must not be advertised unless enabled with an allowlist.
- Raspberry Pi device abstractions (`rpi.device.*` / `rpi.button.read`) must remain endpoint-local wrappers over allowlisted GPIO. Device config must validate `device_id`, BCM pin allowlist, type/direction, relay confirmation defaults, and pulse/blink bounds without changing Core routing or endpoint protocol ownership.
- Raspberry Pi device capabilities must surface through existing endpoint inventory and tool-call paths: `list_endpoint_tool_targets`, `list_active_endpoints`, and `send_endpoint_message(delivery_kind="tool_call")`. Do not add Pi-specific Core inventory APIs or endpoint protocol extensions for device calls.
- Raspberry Pi device confirmation is currently capability-level, not per-device. A write-class `rpi.device.*` capability may advertise `requires_confirmation=true` when any configured output device requires confirmation; do not redesign Core approval for per-device confirmation unless explicitly scoped.
- Raspberry Pi GPIO arguments use BCM numbering, not physical header pin numbers.
- Raspberry Pi 5 GPIO must use gpiozero with `lgpio`; keep `MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio` in the service environment and do not fall back to legacy `RPi.GPIO`/native backends.
- The Pi systemd service must run as `meetyou-rpi`, include the `gpio` supplementary group, and use `/var/lib/meetyou-rpi` for `WorkingDirectory` / `TMPDIR`; `lgpio` creates `.lgd-*` runtime files and must not write into `/opt/meetyou/MeetYou`.
- Manual Pi diagnostics run as `meetyou-rpi` from `/var/lib/meetyou-rpi` must include `PYTHONPATH=/opt/meetyou/MeetYou`; the endpoint package imports the repository-local `endpoint_tool_sdk`, and systemd sets this environment variable for the service.
- GPIO diagnostics for the service user should run from `/var/lib/meetyou-rpi`, not from the repository checkout. `can not open gpiochip` means `/dev/gpiochip*` permission/group setup is wrong, not a ToolRouter problem.
- The Pi endpoint may emit operation progress/result/error, but final assistant replies must still be persisted by Core MessageService.

## Runtime Shape

- The target architecture is `Core-owned Runtime + Endpoint Routing`.
- Python runtime and `meetyou-ui/` remain separate layers. Desktop delivery remains Electron UI plus `desktop_client` backend as one product.
- Development entrypoints remain `python main.py service`, `python main.py cil`, `python main.py desktop-client`, and `python main.py edge-client`; `python main.py` / `python main.py launcher` opens the launcher.
- Production entrypoints remain `python -m service_runtime`, `python -m desktop_client`, and `python -m edge_client`.
- Dependencies remain split across `requirements-core.txt`, `requirements-desktop-client.txt`, and `requirements-edge-client.txt`.
- The optional external Deep Research service uses `research_adapter/` and `requirements-research-adapter.txt`; it runs as `python -m research_adapter` and talks to Core only through the HTTP adapter contract.
- V4/V5 implementation source of truth is the necessary design material in `docs/v4/`, `docs/v5/`, plus this file. Development plans, subplans, historical V3 notes, and phase reports are local/ignored artifacts, not part of the public project body.

## Repository Workflow

- `main` is the publish branch. A finished task must be committed, pushed, and merged back to `main`; do not leave completed work only on a feature branch or as local uncommitted changes.
- If work starts on `main`, commit directly to `main` only when the change is already verified and ready to publish. If work starts on another branch, merge it back to `main` after verification and push `main`.
- During V5 expansion, `v5` is the active integration branch. Each V5 phase must follow: detailed phase plan -> scoped changes -> local verification -> commit -> push `v5` -> wait for GitHub Actions CI -> wait for Core deployment of `v5` -> real runtime/API validation -> update V5 docs -> continue the next phase.
- V5 branch deployment is allowed through `.github/workflows/deploy-core.yml`; CI success on `v5` may deploy `v5`, and manual dispatch must explicitly name the branch to deploy.
- Keep public documentation focused on reusable project design, API surfaces, setup, and acceptance guidance. Ignore or remove development plans, old migration notes, historical architecture drafts, and local reports unless the user explicitly asks to publish them.
- This Windows environment rejects `rg`. Use PowerShell file scanning (`Get-ChildItem`, `Select-String`), `git ls-files`, or targeted language/tooling commands for repository searches.
- Publish prep must remove or ignore local-only outputs such as caches, logs, build folders, Electron release artifacts, packaged runtime templates, and screenshot/test artifacts. Do not commit local secrets or runtime state.

## Directory Boundaries

- Runtime main chain: `main.py`, `service_runtime/service.py`, `core/app.py`, `core/app_lifecycle.py`.
- Core assembly and lifecycle: `core/app.py`, `core/app_lifecycle.py`.
- Endpoint protocol surface: `gateway/`, endpoint protocol SDK files, and endpoint connection services. Do not add a `/client/ws` adapter.
- Desktop provider runtime: `desktop_client/`, especially `desktop_client/runtime.py`, `desktop_client/desktop_api.py`, and `desktop_client/core_client.py`.
- Edge provider runtime: `edge_client/`, especially `edge_client/runtime.py`.
- UI entrypoints: `meetyou-ui/electron/main.ts` for Electron main process and `meetyou-ui/src/main.tsx` for renderer.
- Frontend Core access path: `meetyou-ui/src/hooks/useMeetYou.ts` and `meetyou-ui/src/windowBridge.ts`.
- V5 desktop version UI: `meetyou-ui/src/components/version/`, with branch/checkpoint state wired through `meetyou-ui/src/hooks/useMeetYou.ts`.
- Persistence and migrations: `core/db/*` and `alembic/versions/*`.
- External research adapter service: `research_adapter/`, `core/research/external_adapter.py`, `requirements-research-adapter.txt`, and `deploy/systemd/meetyou-research-adapter.service.template`.
- Do not move local file, general Shell, local MCP lifecycle, or workspace-local execution back into Core. The only Core shell exception is `exec_core_cmd`, fixed to the Core process working directory and constrained by the Core whitelist policy; all other local execution capabilities must be exposed as endpoint execution capabilities and routed through ToolRouter / ExecutionTarget.

## Protocol Rules

- The only V4 real-time provider entrypoint is `GET /endpoint/ws`.
- The formal V4 HTTP facade is `/runtime/*`. `/client/*` is removed and must not be registered, adapted, or forwarded to V4.
- V4 WebSocket protocol is `meetyou.endpoint.ws.v4`.
- `/client/ws` is removed for V4. Do not keep a compatibility handler or a removed-response route for it.
- Endpoint lifecycle frames are `endpoint.hello`, `endpoint.capabilities.snapshot`, `endpoint.ready`, `endpoint.heartbeat`, and `endpoint.goodbye`.
- Endpoint address frames are `endpoint.addresses.snapshot`, `endpoint.address.upsert`, and `endpoint.address.delete`.
- Subscription frames are `subscription.start`, `subscription.update`, and `subscription.stop`.
- Delivery frames are `delivery.message`, `delivery.run_event`, `delivery.notice`, `delivery.operation_update`, `delivery.inbox_item`, `delivery.result`, `delivery.error`, and `delivery.result.ack`.
- Address-targeted `delivery.message` and `delivery.notice` payloads include `target_address_id`, `target_provider_type`, `target_address_type`, and `target_external_ref`.
- Tool frames are `tool.call.request`, `tool.call.accepted`, `tool.call.progress`, `tool.call.result`, `tool.call.error`, and `tool.call.cancel`.
- Use `origin_endpoint_id`, `target_endpoint_id`, and `execution_target_id` in V4 data paths. Do not add new runtime usage of `source_client_id` or `target_client_id`.
- Capability/provider ids should be endpoint-oriented. Permissions are checked against abstract tool keys on Actor / Workspace / RunPolicy, not against a Client allowlist.
- Scheduler-facing assistant tools should prefer `create_scheduled_workflow` and `manage_scheduled_workflows` for ordinary reminders, recurring analysis, document organization, and other scheduled assistant work. Use `create_scheduled_delivery` / `manage_scheduled_deliveries` only when the Scheduled Workflow output must be delivered to an `EndpointAddress`. Keep `manage_scheduled_jobs` as the low-level maintenance surface for Scheduler jobs and `system.heartbeat`.
- Scheduled Workflow is the extensible V4 scheduling protocol: `kind=scheduled_workflow`, `action_ref=core.workflow.scheduled_workflow`, and `run_template.schema=meetyou.scheduler.workflow.v1`. Scheduler owns due detection, leases, and firing; workflow specs own action/tool/output policy.
- Scheduled Workflow assistant output must persist the final assistant Message. Do not expose or accept `persist_message=false`; `create_thread=false` requires an existing `thread_id` or `session_id`.
- Core lifecycle must start Gateway only after Uvicorn reports ready, then external Endpoint Providers may self-connect to `/runtime/*` and `/endpoint/ws`. External providers are supervised by lifecycle recovery so one transient startup failure cannot leave Feishu/WeChat permanently offline.
- Gateway auth may accept `Authorization: Bearer ...` or `X-API-Key` when enabled.

## Configuration And State

- `user/config.json` is not optional; `ConfigManager` may fail startup when it is missing. Secrets belong in `.env`.
- `user/` is local runtime state; Git should keep only `*.example.json` templates and `user/README.md`.
- `user/core_mcp_servers.json` is for Core-side safe MCP only. `user/mcp_servers.json` is for Desktop Provider local MCP only.
- `user/core_cmd_policy.json` is the optional Core-host command whitelist policy for `exec_core_cmd`; if missing or invalid, Core must use the built-in whitelist rather than falling back to allow-all.
- Desktop Provider defaults to `user/desktop_client.json`; local capability boundaries are `read_roots`, `trusted_write_roots`, `cmd_policy_path`, `mcp_servers_path`, and local bridge settings.
- Edge Provider defaults to `user/edge_client.json`; edge boundaries are `workspace_ids`, provider identity/type, `transport_profile`, and endpoint capabilities.
- V5 research adapter configuration lives in environment variables: `MEETYOU_RESEARCH_ENABLED`, `MEETYOU_RESEARCH_ADAPTER_BASE_URL`, `MEETYOU_RESEARCH_ADAPTER_TOKEN`, `MEETYOU_RESEARCH_PROVIDER`, `MEETYOU_RESEARCH_TIMEOUT_SECONDS`, `MEETYOU_RESEARCH_ADAPTER_REQUIRED`, `MEETYOU_RESEARCH_POLL_SECONDS`, `MEETYOU_RESEARCH_POLL_MAX_ERRORS`, and `MEETYOU_RESEARCH_POLL_ERROR_GRACE_SECONDS`. `MEETYOU_RESEARCH_ENABLED` defaults off for the product path; `MEETYOU_RESEARCH_TIMEOUT_SECONDS` is a per-request adapter HTTP guard, not a total research run deadline. Adapter service process settings use `MEETYOU_RESEARCH_ADAPTER_HOST`, `MEETYOU_RESEARCH_ADAPTER_PORT`, and provider-specific keys such as `OPENAI_API_KEY` / `TAVILY_API_KEY`.
- The `v5` Core deploy workflow skips external `meetyou-research-adapter` installation/health-gating while `MEETYOU_RESEARCH_ENABLED` is false. When explicitly enabled, it owns installation/restart of the adapter systemd service, keeps the Core adapter token and adapter service token synchronized, and adapter env files must not contain blank provider-key assignments that override real Core env values.
- The research adapter may bridge Core `MEETYOU_API_KEY` to in-process `OPENAI_API_KEY`, `MEETYOU_*_BASE_URL` to `OPENAI_BASE_URL`, and `MEETYOU_TAVILY_API_KEY` to `TAVILY_API_KEY` when the external provider SDK requires those names; do not log or persist bridged secret values. Adapter health may expose safe boolean provider-env diagnostics, never raw secret values.
- Core / providers should use `MEETYOU_CLIENT_ACCESS_TOKEN` or Gateway/Core access tokens unless a V4 rename is intentionally implemented across config, docs, and deployment. Do not reintroduce `MEETYOU_AGENT_*`.
- PostgreSQL is the formal persistence layer. `bootstrap_core_domain()` runs Alembic migration on service startup. Do not treat `user/*.json` as the only source of truth.
- Danxi credential and WebVPN cookie updates accept encrypted transport only. Never expose plaintext email, password, cookie, or token in logs, error objects, debug output, snapshots, tests, or docs examples.

## Task Boundaries

- Backend-only tasks usually live in `core/`, `service_runtime/`, `gateway/`, `adapters/`, `tools/`, `sensors/`, and `cil/`.
- Frontend-only tasks usually live in `meetyou-ui/`; do not invent backend protocol names from UI assumptions.
- Endpoint provider runtime tasks live in `desktop_client/` or `edge_client/`; do not bypass endpoint execution by changing Core directly.
- External Endpoint Provider SDKs that capture an event loop or own a transport loop must initialize and run on provider-owned worker context, not on Core's main asyncio loop. Feishu/Lark long connection is the canonical example.
- Runtime source identity must follow the endpoint provider. Feishu and WeChat runtime messages must enter Core as `source.kind=feishu` / `source.kind=wechat`, not as generic `web` messages.
- Endpoint tool listing must match workspace device topology: use managed endpoint-workspace membership plus live WebSocket connection state, and do not drop connected devices such as Raspberry Pi only because legacy `workspace_scope` or DB `status` is stale.
- Endpoint/device listing requests must use endpoint listing tools as the source of truth. Do not answer endpoint inventories from memory, assumptions, or the current chat endpoint; include returned endpoint ids, provider types, status, workspace ids, and executable tools compactly without silently dropping Raspberry Pi / RPI or other connected providers. Keep assistant-facing endpoint tool results front-loaded with `tool_target_lines`, `executable_tools_by_endpoint`, `endpoint_ids`, and `compact_endpoints` before verbose details, and sort executable endpoints first so long capability payloads cannot hide later endpoints.
- Assistant-facing list tools must be complete before they are verbose: front-load compact lines, ids, counts, and summary maps for every returned item, and keep long metadata/capability blobs behind explicit detail flags or item-specific follow-up calls. Do not put long repeated lists before later records, because model-facing output budgets can hide or truncate later data.
- Assistant-facing tool results must not duplicate large JSON payloads in both a string field and a structured data field. Prefer one compact structured payload with complete ids/lines first, then optional detail flags for verbose records.
- Automatic thread titles are model-generated in the Runtime path. Message persistence only marks a default-title thread as pending auto-title after the first user message; Runtime calls the configured main model in the background, applies the generated title without setting `manual_title`, and emits `thread.updated`. Do not set the title by directly copying the user's first message except as an explicitly marked failure fallback.
- Treat changes as cross-surface if they touch gateway routes, WebSocket payloads, config loading, `core/db/*`, `desktop_client/runtime.py`, `edge_client/runtime.py`, or `meetyou-ui/src/hooks/useMeetYou.ts`.
- Danxi-related tasks usually touch `tools/danxi_tools.py`, `core/public_contract.py`, `core/assistant_modes.py`, `core/credential_transport.py`, `gateway/models.py`, `gateway/routes/runtime.py`, `gateway/routes/operator.py`, `meetyou-ui/src/`, `meetyou-ui/electron/`, and `docs/`. Do not put Danxi forum access into Desktop Provider or temporary MCP.

## High Risk Areas

- `core/app.py`, `core/app_lifecycle.py`: Core assembly and lifecycle.
- `gateway/routes/runtime.py`, `gateway/routes/endpoint.py`: HTTP facade and V4 Endpoint protocol surface; `/client/ws` must not be restored.
- `core/services/tool_router_service.py`: V4 ToolRouter / ExecutionTarget dispatch path.
- `core/db/*`, `alembic/versions/*`: persistence and migration surface.
- `desktop_client/runtime.py`, `edge_client/runtime.py`: provider execution and protocol connection paths.
- `meetyou-ui/src/hooks/useMeetYou.ts`: UI API and WebSocket main chain.
- `tools/danxi_tools.py`, `core/credential_transport.py`, `meetyou-ui/electron/main.ts`: Danxi/WebVPN login and credential encryption boundaries.

## Allowed And Forbidden

- Allowed: small fixes, local refactors, matching tests, and docs updates when interfaces, startup mode, config, or validation flow changes.
- Forbidden: reintroducing `python main.py gateway`, treating `/ws` as a formal chat path, restoring formal `/agent/ws`, or moving local terminal capabilities into Core beyond the policy-bound `exec_core_cmd` Core-host exception.
- Forbidden in V4 runtime code: `/client/ws`, `source_client_id`, `target_client_id`, Client-owned permissions, Client-owned executable capabilities, and `ClientToolDispatchService`.
- Do not modify real runtime files unless explicitly required: `.env`, `user/*.json`, `user/*.db`, `logs/`, `.venv/`, `.git/`.
- Do not modify lockfiles unless the task requires dependency changes. This repository normally only touches `meetyou-ui/package-lock.json`.
- Schema work may create Alembic migration files only when the task explicitly requires schema changes.
- Schema work must not recreate Procedure. V4 workflows belong in SKILL files and capability manifests.
- For Danxi changes, do not expose plaintext email, password, cookie, or token anywhere.

## Common Commands

- Full development install: `python -m venv .venv`, `.venv\Scripts\activate`, `pip install -r requirements.txt`
- Core production install: `pip install -r requirements-core.txt`
- Desktop Provider production install: `pip install -r requirements-desktop-client.txt`
- Edge Provider production install: `pip install -r requirements-edge-client.txt`
- Backend startup: `python main.py service` or `python -m service_runtime`
- Launcher: `python main.py`
- CIL: `python main.py cil`
- Desktop Provider: `python main.py desktop-client` or `python -m desktop_client`
- Edge Provider: `python main.py edge-client` or `python -m edge_client`
- Research Adapter: `python -m research_adapter`
- Raspberry Pi endpoint health on Pi: `sudo -u meetyou-rpi env PYTHONPATH=/opt/meetyou/MeetYou TMPDIR=/var/lib/meetyou-rpi bash -lc 'cd /var/lib/meetyou-rpi && /opt/meetyou/MeetYou/.venv-rpi/bin/python -m meetyou_rpi_endpoint.health --config /etc/meetyou/rpi-endpoint.json --env-file /etc/meetyou/rpi-endpoint.env'`
- Raspberry Pi endpoint smoke: `bash scripts/rpi/smoke-test.sh /etc/meetyou/rpi-endpoint.json`
- Frontend development: run `npm install`, `npm run dev` under `meetyou-ui/`
- Frontend verification: run `npm run typecheck`, `npm run test` under `meetyou-ui/`
- Frontend build: run `npm run build` under `meetyou-ui/`
- Backend module test: `.venv\Scripts\python.exe -m unittest tests.test_service_runtime`
- Backend full test: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`
- Manual main-chain check: `scripts\manual-acceptance.cmd start`, `scripts\manual-acceptance.cmd check`
- Repository search in this environment: `Get-ChildItem -Recurse -File | Select-String -SimpleMatch "needle"` or `git ls-files | Select-String -SimpleMatch "needle"`; do not use `rg`.

## Completion Boundary

- Before declaring work complete, confirm changes landed in the right boundary and did not reintroduce old entrypoint names or old protocol contracts.
- When changes touch protocol, config, persistence, or cross-surface behavior, add the smallest relevant verification.
- When interfaces, startup modes, config items, or validation flows change, update `AGENTS.md`, `README.md`, or related docs.
- V4 design, plan, deployment, compatibility-window, or cross-endpoint work updates go in `docs/v4/`; V5 research, project, artifact, checkpoint, branch, and edit-retry work updates go in `docs/v5/`.
- After each phase is complete, commit once so phase-level docs and code do not sit uncommitted for long. After the task is complete, merge to `main` and push `main`.
- Release/rollback docs must state that Core Service owns database migration and protocol negotiation. Only claim safe Core rollback when the matching PostgreSQL snapshot is retained.
- If behavior changes without repository test coverage, explicitly call out the test gap.

## Verification Order

- Backend changes: run the smallest related `unittest` module first; run full discovery for cross-directory or cross-system changes.
- Frontend changes: run `npm run typecheck`, then `npm run test`; add real functional tests for substantive UI behavior.
- Frontend acceptance must include a real browser or Electron run plus screenshot verification. Use the real target window size from `meetyou-ui/electron/main.ts` for the surface under test; wide desktop browser checks may be added but do not replace real-size validation. Save screenshots under an ignored local artifact directory and report the exact path in the completion note. Typecheck/unit tests alone are not enough for frontend acceptance.
- Cross-surface changes: verify backend first, then frontend; for API/protocol/service main-chain work, add runtime/gateway focused tests or `scripts\manual-acceptance.cmd check`.
- V5 phase validation must include remote verification after local verification: push `v5`, wait for `CI` on `v5`, wait for `Deploy MeetYou Core` on `v5`, then run real Core/runtime checks against the deployed branch before starting the next V5 phase.
- V5 deployed Core acceptance should use `scripts\v5_real_acceptance.py --base-url <core-url> --expected-branch v5` when the phase touches Project, ProjectSource, Artifact, ResearchTask, checkpoint, branch, or edit-retry behavior; ad hoc API probes may supplement it but should not replace the reusable runner for full V5 main-chain validation.
- V4 baseline test ladder must not stop at unit tests:
  - Run Python tests, frontend typecheck/build/test, migration tests, endpoint protocol tests, scheduler tests, tool router tests, and delivery tests as applicable.
  - Start local Core + Desktop + UI for real tests: Thread, Streaming, `assistant.progress_notice`, ToolRouter, Scheduler, `system.heartbeat`, and disconnect/reconnect.
  - After local real tests pass, commit, push, and merge to `main`.
  - Wait for GitHub Actions CI and Deploy. Remote Core is considered updated only after both pass.
  - After Deploy passes, confirm remote Core `/health` and version / commit sha.
  - Start local Desktop against remote Core and test conversation, Streaming, `assistant.progress_notice`, local tools, Scheduler, Heartbeat, and disconnect/reconnect.
  - Test Feishu and WeChatBot last with unique real messages and human confirmation. Never assume external delivery succeeded without human feedback.
  - Write the local ignored report at `docs/_local/v4-test-report.md` with commit sha, CI/Deploy status, remote Core status, local Desktop to remote Core results, and Feishu/WeChatBot human feedback unless the user explicitly asks to publish the report.

## Platform Notes

- The project is Windows-oriented: README, launcher, `.cmd` scripts, PowerShell startup, `uiautomation`, and Electron window behavior assume Windows by default.
- `launcher.py` probes `GET /health` before starting CIL or UI.
- V4 desktop chain should be validated as `service -> UI -> desktop backend managed by UI -> desktop provider session -> /endpoint/ws runtime`.
