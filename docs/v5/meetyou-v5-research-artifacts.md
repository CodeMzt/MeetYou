# MeetYou V5 Research And Artifacts

## Research Task Flow

Deep research is represented by `ResearchTask`.

1. Intake: store topic, optional project/thread, source policy, and output format.
2. Plan: create an editable Chinese-first plan with explicit gather/synthesize/artifact steps.
3. Approval/start: user or automation approves the editable plan, then starts the task. Status transitions are explicit: `planned -> approved -> running`; `planned -> running` remains allowed for single-step automation.
4. Gather: use read-only web, academic, project-source, file-search, or MCP search/fetch tools.
5. Synthesize: produce claims that map to evidence records.
6. Artifact: validate report citations against the evidence ledger, then save a Markdown report through `ArtifactStore`; PDF/DOCX export can be added as derived artifacts.
7. Deliver: assistant final message contains a short summary and artifact link, not the full large report body.

The first executable runner is deliberately conservative:

- `PATCH /runtime/research-tasks/{id}` with `action=start` transitions the task to `running`; unless `source_policy.auto_execute=false`, Runtime schedules the Core read-only runner.
- `manage_research_tasks(action="run")` executes the same runner from assistant tools.
- The runner gathers from implemented academic adapters, direct read-only web seed URLs, governed web-search discovery, and, when requested, ProjectSource snapshots. It does not mutate sources or send private data to write channels.
- Unsupported adapters are recorded in `metadata.gather_errors`; they do not become citations.
- `web` supports direct page gathering from `source_policy.web_urls`, `seed_urls`, or `source_urls`. If `source_policy.web_search=true` or explicit `web_queries` / `web_search_queries` / `search_queries` are present, Core first uses the governed `search_web` path to discover sources. Sources already read by the search tool can enter the evidence ledger; search-result-only URLs must be fetched by the direct web reader before they become citeable evidence. If a task requests `web` without seed URLs or search discovery, the runner records `WebSeedUrlsRequired` and continues with other configured sources.
- The runner persists lightweight progress into `ResearchTask.metadata.progress` and keeps recent `metadata.progress_events`. Current stages are `gather`, `synthesize`, `artifact`, and `completed`; this is pollable task state, not a replacement for future streaming progress.
- If no readable evidence is gathered, the task transitions to `failed` and no report artifact is created.
- If evidence is gathered, the runner builds a Markdown report, validates bracket citations against `evidence_ledger`, creates a `research_report` Artifact, and completes the task.

## Evidence Ledger

Every research report must carry an evidence ledger. The ledger records source id, adapter, URL or project-source id, title, verification status, and freshness notes.

Allowed verification statuses:

- `query_url`: adapter produced a query URL but content is not read yet.
- `fetched`: source content was fetched/read.
- `project_source_snapshot`: source came from durable project source material.
- `derived`: source is a derived artifact, not primary evidence.

Final research claims should cite only fetched or project-source evidence unless the report explicitly labels the gap. The current guard validates numeric inline citations such as `[1]` and `[2]`; every cited id must exist in `evidence_ledger[].source_id`, or the API/tool request fails with `research_report_citation_invalid` before any report artifact is written.

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

Production storage must implement the same ArtifactStore contract and return an artifact download route or signed URL without changing ResearchTask semantics.

## Desktop Research UI

The desktop UI exposes `research` as a composer mode and shows a compact ResearchTask panel in the main thread view while that mode is active. The first UI slice supports:

- create a task with topic, active project, active thread, default read-only source policy, and Markdown output format;
- inspect generated plan steps;
- edit and save the plan while status is `planned`;
- approve, start, cancel, and refresh task state;
- inspect durable progress context from the selected task, including current runner stage, stage message, evidence count, gather error count, output format, summary, the first evidence ledger entries, and completed artifact filename/size;
- download a completed report artifact through the authenticated `/desktop/artifacts/{artifact_id}/download` proxy.

This UI is a task shell over the durable API and runner. Evidence and source previews must be derived from `ResearchTask.evidence_ledger`; stage progress must be derived from `ResearchTask.metadata.progress`; artifact labels and downloads must be derived from the Core artifact record attached to the task. The current UI can create/approve/start a task, show completed source/summary/artifact state, and download the completed artifact, but advanced capabilities such as editable multi-agent research plans, long-running progress streams, richer source ranking, PDF/DOCX derivation, and broad provider selection remain later V5 stages.

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
