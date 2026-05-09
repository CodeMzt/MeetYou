# MeetYou V5 Research And Artifacts

## Research Task Flow

Deep research is represented by `ResearchTask`.

1. Intake: store topic, optional project/thread, source policy, and output format.
2. Plan: create an editable plan with explicit gather/synthesize/artifact steps.
3. Approval/start: user or automation approves the editable plan, then starts the task. Status transitions are explicit: `planned -> approved -> running`; `planned -> running` remains allowed for single-step automation.
4. Gather: use read-only web, academic, project-source, file-search, or MCP search/fetch tools.
5. Synthesize: produce claims that map to evidence records.
6. Artifact: validate report citations against the evidence ledger, then save a Markdown report through `ArtifactStore`; PDF/DOCX export can be added as derived artifacts.
7. Deliver: assistant final message contains a short summary and artifact link, not the full large report body.

The first executable runner is deliberately conservative:

- `PATCH /runtime/research-tasks/{id}` with `action=start` transitions the task to `running`; unless `source_policy.auto_execute=false`, Runtime schedules the Core read-only runner.
- `manage_research_tasks(action="run")` executes the same runner from assistant tools.
- The runner gathers from implemented academic adapters and, when requested, ProjectSource snapshots. It does not mutate sources or send private data to write channels.
- Unsupported adapters are recorded in `metadata.gather_errors`; they do not become citations.
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
- download a completed report artifact through the authenticated `/desktop/artifacts/{artifact_id}/download` proxy.

This UI is a task shell over the durable API and runner. It can create/approve/start a task and later download the completed artifact, but advanced capabilities such as editable multi-agent research plans, long-running progress streams, PDF/DOCX derivation, and web-search integration remain later V5 stages.

## Project Artifacts UI

Completed reports and other generated project outputs are visible from the desktop Project Artifacts popover. The popover calls the project artifact list API through the desktop proxy, shows the active artifact count, allows manual refresh, previews artifact filename, type, status, size, checksum, timestamp, and metadata, and downloads the selected artifact through the authenticated artifact download proxy.

This view is intentionally project-scoped rather than research-panel-scoped. A project artifact may be created by a research task, future document generation, or a later import/export workflow; the UI should therefore list Core artifact records directly instead of rebuilding the list from currently visible research tasks.

## Project Sources

Message snapshots saved from the desktop message menu are persisted through Core as ProjectSource records. The UI only sends the source request for already-persisted messages (`msg_*`) and a currently active project; Core owns the source content, checksum, metadata, and project membership.

The desktop top control dock includes a Project Sources popover for the active project. It calls the Core source list API through the desktop proxy, shows the current active-source count, allows manual refresh, and previews source title, type, status, saved timestamp, content, and selected metadata. Saving a message snapshot triggers a source refresh so research users can immediately confirm material that will be available to project-scoped research tasks.

## Academic Sources

Academic source adapters are read-only adapters for:

- arXiv
- OpenAlex
- Crossref
- Semantic Scholar

The current Core implementation can produce normalized query URLs, fetch adapter results, parse provider payloads into evidence entries, and run under a test-injectable fetcher so CI does not depend on external networks. The `web` adapter remains a planned integration point for the existing web-search capability; until it lands, `web` is recorded as an unsupported adapter during runner execution instead of being cited.
