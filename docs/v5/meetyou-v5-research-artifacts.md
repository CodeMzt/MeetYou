# MeetYou V5 Research And Artifacts

## Research Task Flow

Deep research is represented by `ResearchTask`.

1. Intake: store topic, optional project/thread, source policy, and output format.
2. Plan: create an editable Chinese-first plan with explicit gather/synthesize/artifact steps.
3. Approval/start: user or automation approves the editable plan, then starts the task. Status transitions are explicit: `planned -> approved -> running`; `planned -> running` remains allowed for single-step automation.
4. Gather: use read-only web, academic, project-source, file-search, or MCP search/fetch tools.
5. Synthesize: produce claims that map to evidence records.
6. Artifact: validate report citations against the evidence ledger, save a Markdown report through `ArtifactStore`, and optionally create PDF/DOCX derived artifacts when requested by `source_policy.derived_formats`, `artifact_formats`, `report_formats`, output format, or the `include_pdf` / `include_docx` flags.
7. Deliver: assistant final message contains a short summary and artifact link, not the full large report body.

The first executable runner is deliberately conservative:

- `PATCH /runtime/research-tasks/{id}` with `action=start` transitions the task to `running`; unless `source_policy.auto_execute=false`, Runtime schedules the Core read-only runner.
- `manage_research_tasks(action="run")` executes the same runner from assistant tools.
- Assistant-facing V5 research tools are part of the public tool template: `search_academic_sources`, `create_research_task`, and `manage_research_tasks` must be present in `user/tools.example.json` with parameter schemas that match the registered Core tool implementations and research-mode prompts.
- Runtime `start` binds the ResearchTask to a Core `Run`, stores the public `run_id` on the task response/metadata, and emits durable `research.started` plus subsequent `research.*` RunEvents. `GET /runtime/research-tasks/{id}/events?after_seq=N` returns incremental task events so progress UIs can resume without depending only on current task metadata.
- The runner gathers from implemented academic adapters, direct read-only web seed URLs, governed web-search discovery, and, when requested, ProjectSource snapshots. It does not mutate sources or send private data to write channels.
- Unsupported adapters are recorded in `metadata.gather_errors`; they do not become citations.
- `web` supports direct page gathering from `source_policy.web_urls`, `seed_urls`, or `source_urls`. If `source_policy.web_search=true` or explicit `web_queries` / `web_search_queries` / `search_queries` are present, Core first uses the governed `search_web` path to discover sources. Sources already read by the search tool can enter the evidence ledger; search-result-only URLs must be fetched by the direct web reader before they become citeable evidence. If a task requests `web` without seed URLs or search discovery, the runner records `WebSeedUrlsRequired` and continues with other configured sources.
- The runner persists lightweight progress into `ResearchTask.metadata.progress`, keeps recent `metadata.progress_events`, and mirrors each progress transition as durable `research.progress` RunEvents when a task has a Run binding. Current stages are `gather`, `synthesize`, `artifact`, and `completed`; metadata remains the compact task snapshot while RunEvents provide the resumable progress stream.
- Cancellation is cooperative and durable. Once a task reaches `cancelled`, the runner stops at the next stage/source boundary, records cancelled progress, and must not create a report artifact or thread delivery message after cancellation is observed.
- If no readable evidence is gathered, the task transitions to `failed` and no report artifact is created.
- If evidence is gathered, the runner builds a Markdown report, validates bracket citations against `evidence_ledger`, creates a primary `research_report` Artifact, creates requested PDF/DOCX `research_report_derivative` Artifacts, and completes the task.
- Derived artifacts are recorded in `ResearchTask.metadata.derived_artifacts`, exposed in `RuntimeResearchTaskResponse.derived_artifacts`, and visible through the project artifact list API. The primary Markdown artifact remains the task's `artifact_id`.
- If the task is bound to a thread, the runner also persists an assistant Message with a short summary, primary artifact download link, derivative artifact links, ResearchTask id, and evidence count. It then attaches the message to the active conversation branch so the ordinary automatic checkpoint path still applies.

## Evidence Ledger

Every research report must carry an evidence ledger. The ledger records source id, adapter, URL or project-source id, title, verification status, and freshness notes.

All evidence ledger entries are untrusted by default. Core marks gathered sources with `source_trust=untrusted`, `trusted_for=evidence_only`, `ignore_source_instructions=true`, and a `prompt_injection_mitigation` note. Downstream synthesis must treat webpages, project sources, search results, and academic records as material to cite, not as instructions to follow.

Allowed verification statuses:

- `query_url`: adapter produced a query URL but content is not read yet.
- `fetched`: source content was fetched/read.
- `project_source_snapshot`: source came from durable project source material.
- `derived`: source is a derived artifact, not primary evidence.

Final research claims should cite only fetched or project-source evidence unless the report explicitly labels the gap. The current guard validates numeric inline citations such as `[1]` and `[2]`; every cited id must exist in `evidence_ledger[].source_id`, or the API/tool request fails with `research_report_citation_invalid` before any report artifact is written.

Generated reports also include a source-safety note in the risk section so exported Markdown/PDF/DOCX artifacts preserve the same boundary for human review.

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

The desktop UI exposes `research` as a composer mode and shows a compact ResearchTask panel in the main thread view while that mode is active. The first UI slice supports:

- create a task with topic, active project, active thread, default read-only source policy, and Markdown output format;
- enable or disable governed web-search discovery, optionally provide explicit search queries, and optionally provide direct webpage URLs before creating the task;
- choose read-only academic source adapters (`arxiv`, `openalex`, `crossref`, `semantic_scholar`) and a bounded per-adapter source limit before task creation;
- choose optional PDF/DOCX derived report exports before task creation;
- inspect generated plan steps;
- edit and save the plan while status is `planned`;
- approve, start, cancel, and refresh task state;
- inspect durable progress context from the selected task, including current runner stage, stage message, evidence count, gather error count, output format, summary, the first evidence ledger entries, and completed artifact filename/size;
- inspect the durable RunEvent stream for selected tasks when `run_id` is present, including event count, latest event, recent `research.started` / `research.progress` / terminal `research.*` events, and short run id;
- auto-refresh visible `running` tasks on a short bounded interval so stage progress and cancellation/completion state are trackable without manual refresh;
- download a completed report artifact through the authenticated `/desktop/artifacts/{artifact_id}/download` proxy.

This UI is a task shell over the durable API and runner. Evidence and source previews must be derived from `ResearchTask.evidence_ledger`; stage progress must be derived from `ResearchTask.metadata.progress`; event stream details must be derived from `/runtime/research-tasks/{id}/events`; artifact labels and downloads must be derived from the Core artifact records attached to the task. The web controls write `source_policy.web_search=true`, optional `source_policy.web_queries`, and optional `source_policy.web_urls` into task creation; when neither web search nor seed URLs are enabled, the UI omits the `web` adapter. The academic source controls write the selected academic adapters into `source_policy.source_adapters` and write `source_policy.limit` as a bounded source count. The export controls write optional `source_policy.derived_formats=["pdf","docx"]` and completed tasks show derived artifact count/filenames from Core response records. Markdown report links in assistant messages that point at `/runtime/artifacts/{artifact_id}/download` or `/desktop/artifacts/{artifact_id}/download` are intercepted by the desktop renderer and downloaded through the authenticated desktop artifact proxy. Derived PDF/DOCX artifacts are Core artifact records and can be downloaded through artifact APIs. Advanced capabilities such as editable multi-agent research plans, richer source ranking, and broader provider controls remain later V5 stages.

## Project Artifacts UI

Completed reports and other generated project outputs are visible from the desktop Project Artifacts popover. The popover calls the project artifact list API through the desktop proxy, shows the active artifact count, allows manual refresh, previews artifact filename, type, status, size, checksum, timestamp, and metadata, and downloads the selected artifact through the authenticated artifact download proxy.

This view is intentionally project-scoped rather than research-panel-scoped. A project artifact may be created by a research task, future document generation, or a later import/export workflow; the UI should therefore list Core artifact records directly instead of rebuilding the list from currently visible research tasks.

## Project Sources

Message snapshots saved from the desktop message menu are persisted through Core as ProjectSource records. The UI only sends the source request for already-persisted messages (`msg_*`) and a currently active project; Core owns the source content, checksum, metadata, and project membership.

The desktop top control dock includes a Project Sources popover for the active project. It calls the Core source list API through the desktop proxy, shows the current active-source count, allows manual refresh, and previews source title, type, status, saved timestamp, content, and selected metadata. Saving a message snapshot triggers a source refresh so research users can immediately confirm material that will be available to project-scoped research tasks.

## Web Sources

The Core `web` adapter is read-only. Research tasks may provide `source_policy.web_urls`, `source_policy.seed_urls`, or `source_policy.source_urls`; each valid HTTP(S) URL is fetched, stripped of scripts/styles/svg/noscript blocks, summarized into a bounded snippet, and recorded as `source_type=web_page` with `verification_status=fetched`.

Search discovery is opt-in through `source_policy.web_search=true` or explicit query lists in `source_policy.web_queries`, `web_search_queries`, `search_queries`, or `queries`. When enabled, Runtime bridges the ResearchTask runner to Core `search_web` without exposing raw MCP tools to the task. Search payloads are normalized into evidence only when the search reader already produced readable source summaries. Search-result-only entries are treated as discovery seeds and must be fetched by the direct web reader before the report may cite them. Tasks that request `web` without seed URLs or search discovery still get a `WebSeedUrlsRequired` gather error.

## Academic Sources

Academic source adapters are read-only adapters for:

- arXiv
- OpenAlex
- Crossref
- Semantic Scholar

The current Core implementation can produce normalized query URLs, fetch adapter results, parse provider payloads into evidence entries, and run under a test-injectable fetcher so CI does not depend on external networks.
