# MeetYou V5 Research And Artifacts

## Current Product Status

Deep research execution is disabled by default in V5 because the self-maintained GPT Researcher adapter path has not met the stability bar for user-facing delivery. The durable Core model (`ResearchTask`, evidence ledger, artifacts, run events, and thread binding) stays in place, and deployments can explicitly re-enable execution with `MEETYOU_RESEARCH_ENABLED=true` after validating a vendor or adapter service. Default Desktop UI should not expose a research-mode entry point while execution is disabled; research-mode messages receive a clear disabled assistant response instead of entering the old plan/start path and failing with connection errors.

Ordinary lightweight research remains a normal chat capability. Long-running vendor-grade deep research should be handled by a stable external product or a future provider behind the same adapter contract, not by silently falling back to an uncited Core report.

## Research Task Flow

Deep research is represented by `ResearchTask`.

1. Intake: store topic, optional project, current thread binding, source policy, and output format. Desktop-created tasks are thread-bound so switching conversations switches visible research state.
2. Plan: create an editable Chinese-first plan with research questions, source strategy, quality gates, deliverables, and explicit gather/synthesize/artifact steps.
3. Approval/start: user or automation approves the editable plan, then starts the task. Status transitions are explicit: `planned -> approved -> running`; `planned -> running` remains allowed for single-step automation.
4. Execute: Core calls the external `research_adapter` HTTP service. The adapter may use GPT Researcher in the first implementation and future providers such as Open Deep Research under the same contract.
5. Gather/synthesize outside Core: the external provider performs read-only search, reading, and synthesis, then returns Markdown report text plus source records.
6. Artifact: Core normalizes/safety-marks the returned sources into the evidence ledger, validates report citations against that ledger, saves a Markdown report through `ArtifactStore`, and optionally creates PDF/DOCX derived artifacts when requested by `source_policy.derived_formats`, `artifact_formats`, `report_formats`, output format, or the `include_pdf` / `include_docx` flags.
7. Deliver: assistant final message contains a short summary and artifact link, not the full large report body.

When deep research execution is explicitly enabled, the executable runner is externalized:

- `PATCH /runtime/research-tasks/{id}` with `action=start` transitions the task to `running`; unless `source_policy.auto_execute=false`, Runtime schedules Core to call the external research adapter. With default disabled execution, auto-executing starts are rejected with `research_disabled`.
- `manage_research_tasks(action="run")` uses the same Core adapter path from assistant tools and returns `research_disabled` while default execution is off.
- Assistant-facing V5 research tools are part of the public tool template: `search_academic_sources`, `create_research_task`, and `manage_research_tasks` must be present in `user/tools.example.json` with parameter schemas that match the registered Core tool implementations and research-mode prompts.
- Assistant-facing ResearchTask tools share the Runtime binding contract: supplied `project_id` and `thread_id` must resolve to durable Core records. Unknown ids return structured `project_not_found` or `thread_not_found` errors rather than silently creating or listing unscoped tasks.
- When assistant tools are invoked from a routed conversation and `project_id` or `thread_id` is omitted, `create_research_task` and `manage_research_tasks(action=list)` infer the current binding from route/event context. This keeps research mode thread-bound without requiring the model to copy ids into every call.
- New ResearchTasks receive a Core-generated Chinese-first plan. The plan includes an explicit `plan_review` confirmation step, research questions, source strategy, quality gates, deliverables, `requires_approval=true`, and remains editable until the task starts.
- Chat-native research mode is guarded by Runtime, not only by prompts. `POST /runtime/messages` with `preferred_mode=research` creates a thread-bound planned `ResearchTask` and persists an assistant plan-confirmation message instead of queuing a normal assistant run. A later explicit confirmation message such as `确认开始` transitions the active planned/approved task to `running`, binds the Core Run, and persists an assistant start message in the same thread. Other pre-start research-mode replies are recorded as plan revision notes and keep the task in planning.
- Runtime `start` binds the ResearchTask to a Core `Run`, stores the public `run_id` on the task response/metadata, and emits durable `research.started` plus subsequent `research.*` RunEvents. `GET /runtime/research-tasks/{id}/events?after_seq=N` returns incremental task events so progress UIs can resume without depending only on current task metadata.
- Core sends bounded project/thread/source context to the adapter according to `source_policy`, including active ProjectSource snapshots only when requested. The adapter must treat that data as read-only research context.
- Core starts an adapter run, persists `external_run_id`, polls the adapter status/progress, and mirrors adapter progress into `ResearchTask.metadata.progress` plus durable RunEvents. Core does not cancel an external research run merely because a fixed total timeout elapsed.
- Temporary adapter polling failures are non-terminal until the configured poll-error budget is exhausted. Core records `adapter_status=poll_error`, `adapter_poll_error_count`, elapsed seconds, and the last poll time while keeping the task `running`; terminal failure occurs only after `MEETYOU_RESEARCH_POLL_MAX_ERRORS` or `MEETYOU_RESEARCH_POLL_ERROR_GRACE_SECONDS` is exceeded.
- Adapter metadata is copied into `ResearchTask.metadata` as `research_provider`, `external_run_id`, `adapter_status`, `adapter_error`, `last_adapter_poll_at`, `adapter_metadata`, and `adapter_usage` when available.
- If the adapter is required but `MEETYOU_RESEARCH_ADAPTER_BASE_URL` is not configured, the task transitions to `failed` with `runner_error=research_adapter_unconfigured` and no artifact is created.
- If the adapter returns no report text or no citeable sources, the task transitions to `failed`. Core must not generate an uncited fallback report.
- The runner persists lightweight progress into `ResearchTask.metadata.progress`, keeps recent `metadata.progress_events`, and mirrors each progress transition as durable `research.progress` RunEvents when a task has a Run binding. Current stages include adapter-reported stages such as `queued`, `starting`, `research`, `gather`, `write`, `sources`, plus Core stages such as `artifact` and `completed`; metadata remains the compact task snapshot while RunEvents provide the resumable progress stream.
- Cancellation is cooperative and durable. Core requests adapter cancellation when possible and, once the task reaches `cancelled`, avoids creating report artifacts or thread delivery messages after cancellation is observed.
- If citeable evidence is returned, Core safety-marks evidence, validates bracket citations against `evidence_ledger`, creates a primary `research_report` Artifact, creates requested PDF/DOCX `research_report_derivative` Artifacts, and completes the task.
- Derived artifacts are recorded in `ResearchTask.metadata.derived_artifacts`, exposed in `RuntimeResearchTaskResponse.derived_artifacts`, and visible through the project artifact list API. The primary Markdown artifact remains the task's `artifact_id`.
- If the task is bound to a thread, the runner also persists an assistant Message with a short summary, primary artifact download link, derivative artifact links, ResearchTask id, and evidence count. It then attaches the message to the active conversation branch so the ordinary automatic checkpoint path still applies.

## Research Adapter Contract

The adapter is an independent FastAPI service, not a Core module with database privileges. First-stage provider support defaults to GPT Researcher because it already supports service-style autonomous web/local research, citations, Markdown/PDF/DOCX output patterns, and parallel research work. Open Deep Research remains a future provider under the same contract because its LangGraph/MCP configuration surface is larger.

Core calls:

- `GET /health`
- `POST /v1/research/runs`
- `GET /v1/research/runs/{run_id}`
- `POST /v1/research/runs/{run_id}/cancel`

The run request schema is `meetyou.research.adapter.run.v1` and includes provider, ResearchTask id, topic, source policy, output format, optional project/thread metadata, and bounded `project_sources[]`. The response must include:

- `run_id`
- `status`: running, completed, failed, or cancelled
- `progress`
- `report_markdown`
- `sources[]`
- optional `summary`, `usage`, and `metadata`

Core is the only component that creates Artifact records, PDF/DOCX derivatives, evidence-ledger safety metadata, final thread messages, and automatic checkpoints. The external adapter must not write MeetYou tables or assume artifact ids.

When `source_policy.include_project_sources=true`, `source_policy.source_adapters=[]`, and no web/search seed policy is supplied, the adapter may use its project-source-only execution path instead of launching GPT Researcher. This path still runs outside Core, returns citeable `project_source_snapshot` sources, and is intended for fast bounded local/project research and acceptance checks. Web or academic research requests continue to use the configured provider, currently GPT Researcher.

Configuration:

- Core: `MEETYOU_RESEARCH_ENABLED`, `MEETYOU_RESEARCH_ADAPTER_BASE_URL`, `MEETYOU_RESEARCH_ADAPTER_TOKEN`, `MEETYOU_RESEARCH_PROVIDER`, `MEETYOU_RESEARCH_TIMEOUT_SECONDS`, `MEETYOU_RESEARCH_ADAPTER_REQUIRED`, `MEETYOU_RESEARCH_POLL_SECONDS`, `MEETYOU_RESEARCH_POLL_MAX_ERRORS`, and `MEETYOU_RESEARCH_POLL_ERROR_GRACE_SECONDS`. `MEETYOU_RESEARCH_ENABLED` defaults to false for the user-facing product path.
- Adapter process: `MEETYOU_RESEARCH_ADAPTER_HOST`, `MEETYOU_RESEARCH_ADAPTER_PORT`, `MEETYOU_RESEARCH_ADAPTER_TOKEN`, `MEETYOU_RESEARCH_PROVIDER`, provider-specific model/search keys, and optional `MEETYOU_RESEARCH_ADAPTER_FAKE=true` for local acceptance tests.
- Deployment: the `v5` Core deploy workflow writes `MEETYOU_RESEARCH_ENABLED=false` by default and skips adapter install/health-gating while execution is disabled. When a deployment explicitly sets `MEETYOU_RESEARCH_ENABLED=true`, the workflow installs `meetyou-research-adapter` as a separate systemd service with an isolated `.venv-research-adapter`, writes Core adapter settings into `/etc/meetyou/meetyou-core.env` only when missing or placeholder-valued, and keeps the adapter token synchronized with `/etc/meetyou/meetyou-research-adapter.env`. The adapter unit reads Core env first, then adapter env; adapter env files must not contain blank provider-key assignments such as `OPENAI_API_KEY=` because systemd would override real Core values with empty strings.
- Provider credentials: when `OPENAI_API_KEY` is absent but Core's `MEETYOU_API_KEY` is present in the adapter process env, the adapter exposes it to OpenAI-compatible provider SDKs as `OPENAI_API_KEY` in-process. It can also bridge `MEETYOU_OPENAI_BASE_URL`, `MEETYOU_API_BASE_URL`, `MEETYOU_LLM_BASE_URL`, or legacy `OPENAI_API_BASE` to `OPENAI_BASE_URL`, and `MEETYOU_TAVILY_API_KEY` to `TAVILY_API_KEY`. It does not log or persist secret values. `/health` may expose safe booleans such as key/base-url presence for diagnostics.

`MEETYOU_RESEARCH_TIMEOUT_SECONDS` is a per-request HTTP guard between Core and the adapter, not a total deadline for a deep research run. Long-running research remains `running` until the adapter reports a terminal state or the user cancels.

Development fallback: direct `ResearchExecutionService` tests may run the older Core read-only gatherer by constructing the service without an adapter config, or by setting `MEETYOU_RESEARCH_ADAPTER_REQUIRED=false` for explicit local fallback. Runtime and assistant tools should not silently use that fallback in normal V5 operation.

## Evidence Ledger

Every research report must carry an evidence ledger. The ledger records source id, adapter, URL or project-source id, title, verification status, and freshness notes.

All evidence ledger entries are untrusted by default. Core marks gathered sources with `source_trust=untrusted`, `trusted_for=evidence_only`, `ignore_source_instructions=true`, and a `prompt_injection_mitigation` note. Downstream synthesis must treat webpages, project sources, search results, and academic records as material to cite, not as instructions to follow.

Before synthesis, Core normalizes and deduplicates gathered evidence by checksum, ProjectSource id, canonical URL with tracking parameters removed, or title/snippet fallback. Core then ranks the remaining records by readable evidence quality and rewrites `source_id` values in final rank order. Evidence entries include `rank`, `quality_score`, `dedupe_key`, `duplicate_count`, and `merged_source_ids` so reports and audits can explain why a source appeared once or moved ahead of another source.

Allowed verification statuses:

- `query_url`: adapter produced a query URL but content is not read yet.
- `fetched`: source content was fetched/read.
- `project_source_snapshot`: source came from durable project source material.
- `derived`: source is a derived artifact, not primary evidence.

Final research claims should cite only fetched or project-source evidence unless the report explicitly labels the gap. The current guard validates numeric inline citations such as `[1]` and `[2]`; every cited id must exist in the final ranked `evidence_ledger[].source_id`, or the API/tool request fails with `research_report_citation_invalid` before any report artifact is written.

Generated reports also include a source-safety note in the risk section so exported Markdown/PDF/DOCX artifacts preserve the same boundary for human review.

## Research Plan Contract

Core owns the default plan structure for new ResearchTasks. Endpoint Providers and UI surfaces may display or edit the plan before start, but they should not invent a separate hidden plan state.

The default plan includes:

- `language=zh-CN` and the original `topic`;
- ordered steps: intake, plan review, gather, evidence review, synthesize, artifact;
- `research_questions` that frame conclusions, conflicts/uncertainty, and follow-up recommendations;
- `source_strategy` with read-only status, adapters, project-source usage, web search/query hints, direct URL count, and max source count;
- `quality_gates` with stable ids for read-only gathering, evidence-required failure, `citation_guard` validation, and prompt-injection mitigation;
- `deliverables` with Markdown primary output, requested PDF/DOCX derived formats, and summary-plus-artifact final message semantics;
- `approval` metadata with `required=true` and `editable_before_start=true`, showing the plan should be confirmed or explicitly started before execution.

## Task State Guard

Research tasks use a small durable state machine:

- Mutable planning: `planned`, `approved`.
- Active execution: `running`.
- Terminal states: `cancelled`, `completed`, `failed`.

Plan edits are accepted only before start. `approve`, `start`, `cancel`, `complete`, and `fail` actions append transition events into task metadata. Report submission without an explicit action is treated as `complete`; report submission with any other action is rejected by the tool/API guard.

## ArtifactStore

The first implementation ships `LocalArtifactStore`:

- Root: `user/artifacts/`.
- One directory per `artifact_id`.
- Stored metadata includes storage backend, storage key, filename, content type, byte size, checksum, status, and optional project/thread/run pointers.
- Text artifacts and binary artifacts use the same store contract. The local backend computes checksums over bytes and preserves MIME types for download routing.

Production storage must implement the same ArtifactStore contract and return an artifact download route or signed URL without changing ResearchTask semantics.

## Report Derived Artifacts

V5 keeps Markdown as the canonical report body because it is diffable, citation-readable, and easy to audit against the evidence ledger. PDF and DOCX exports are derived artifacts, not separate source-of-truth reports.

Supported first-stage derived formats:

- `pdf`: text-only PDF, generated by Core without external write actions.
- `docx`: Word document export using the core document dependency when available, with a minimal DOCX fallback.

Request formats through any of these task controls:

- `source_policy.derived_formats`: `["pdf", "docx"]`.
- `source_policy.artifact_formats` or `source_policy.report_formats`.
- `source_policy.include_pdf=true` or `source_policy.include_docx=true`.
- `output_format` containing `pdf`, `docx`, or `all`; `markdown` alone creates only the primary Markdown artifact.

Manual report submission through `PATCH /runtime/research-tasks/{id}` and `manage_research_tasks(report_markdown=...)` uses the same derivative generation path as the automatic runner. If a requested derivative cannot be created, the report completion fails instead of silently claiming an export exists.

## Desktop Research UI

The desktop UI exposes `research` as a composer mode, but research is no longer a standalone panel above the message list. The intended interaction is chat-native:

- The first user message in research mode is treated as the research topic for the current thread.
- The assistant creates a thread-bound `ResearchTask`, replies in chat with an editable Chinese plan, and asks the user to confirm, modify, or regenerate the plan before long-running execution.
- When execution starts, the visible progress appears as a compact assistant-style status bubble in the same thread rather than a separate form. Switching threads switches the visible ResearchTask list; project sources and project artifacts remain project-scoped.
- Running state displays only real Core/adapter data: topic, task status, provider, adapter status, stage, latest progress message, elapsed time, last update, source count, external run id, artifact/download state, and adapter errors.
- The status bubble can refresh, cancel a running task, start a planned/approved task when a durable task already exists, and download the completed artifact. It must not expose old default academic source chips or a fake step list while running.
- Markdown report links in assistant messages that point at `/runtime/artifacts/{artifact_id}/download` or `/desktop/artifacts/{artifact_id}/download` are intercepted by the desktop renderer and downloaded through the authenticated desktop artifact proxy. Derived PDF/DOCX artifacts are Core artifact records and can be downloaded through artifact APIs.

Evidence and source previews, when shown, must be derived from `ResearchTask.evidence_ledger`; adapter status must be derived from `ResearchTask.metadata.research_provider`, `external_run_id`, `adapter_status`, `adapter_error`, and `last_adapter_poll_at`; stage progress must be derived from `ResearchTask.metadata.progress`; event stream details must be derived from `/runtime/research-tasks/{id}/events`; artifact labels and downloads must be derived from the Core artifact records attached to the task. GPT Researcher does not expose reliable per-source live progress through the current adapter path, so the UI must not fabricate per-source reading or reasoning traces. Advanced capabilities such as source comparison views, academic-only constraints, and broader provider controls remain later V5 stages.

## Project Artifacts UI

Completed reports and other generated project outputs are visible from the desktop Project Artifacts popover. The popover calls the project artifact list API through the desktop proxy, shows the active artifact count, allows manual refresh, previews artifact filename, type, status, size, checksum, timestamp, and metadata, and downloads the selected artifact through the authenticated artifact download proxy.

This view is intentionally project-scoped rather than research-panel-scoped. A project artifact may be created by a research task, future document generation, or a later import/export workflow; the UI should therefore list Core artifact records directly instead of rebuilding the list from currently visible research tasks.

## Project Sources

Message snapshots saved from the desktop message menu are persisted through Core as ProjectSource records. The UI only sends the source request for already-persisted messages (`msg_*`) and a currently active project; Core owns the source content, checksum, metadata, and project membership.

The desktop top control dock includes a Project Sources popover for the active project. It calls the Core source list API through the desktop proxy, shows the current active-source count, allows manual refresh, and previews source title, type, status, saved timestamp, content, and selected metadata. Saving a message snapshot triggers a source refresh so research users can immediately confirm material that will be available to project-scoped research tasks. Deleting a source calls `DELETE /runtime/projects/{project_id}/sources/{source_id}` through the desktop proxy; Core archives the ProjectSource so it disappears from active lists and future project-context injection, but original messages and artifacts remain intact.

## Web Sources

The Core `web` adapter is read-only. Research tasks may provide `source_policy.web_urls`, `source_policy.seed_urls`, or `source_policy.source_urls`; each valid HTTP(S) URL is fetched, stripped of scripts/styles/svg/noscript blocks, summarized into a bounded snippet, and recorded as `source_type=web_page` with `verification_status=fetched`.

Search discovery is opt-in through `source_policy.web_search=true` or explicit query lists in `source_policy.web_queries`, `web_search_queries`, `search_queries`, or `queries`. When enabled, Runtime bridges the ResearchTask runner to Core `search_web` without exposing raw MCP tools to the task. Search payloads are normalized into evidence only when the search reader already produced readable source summaries. Search-result-only entries are treated as discovery seeds and must be fetched by the direct web reader before the report may cite them. Tasks that request `web` without seed URLs or search discovery still get a `WebSeedUrlsRequired` gather error.

## Academic Sources

Academic source adapters are read-only adapters for:

- arXiv
- OpenAlex
- Crossref
- Semantic Scholar

The current Core implementation can produce normalized query URLs, fetch adapter results, parse provider payloads into evidence entries, and run under a test-injectable fetcher so CI does not depend on external networks. These adapters are retained as Core fallback/test capability and future advanced constraints; the default desktop research UI delegates ordinary academic discovery to the external provider instead of exposing separate academic source chips.
