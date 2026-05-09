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

## Evidence Ledger

Every research report must carry an evidence ledger. The ledger records source id, adapter, URL or project-source id, title, verification status, and freshness notes.

Allowed verification statuses:

- `query_url`: adapter produced a query URL but content is not read yet.
- `read`: source content was fetched/read.
- `project_source`: source came from durable project source material.
- `derived`: source is a derived artifact, not primary evidence.

Final research claims should cite only `read` or `project_source` evidence unless the report explicitly labels the gap. The current guard validates numeric inline citations such as `[1]` and `[2]`; every cited id must exist in `evidence_ledger[].source_id`, or the API/tool request fails with `research_report_citation_invalid` before any report artifact is written.

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

## Project Sources

Message snapshots saved from the desktop message menu are persisted through Core as ProjectSource records. The UI only sends the source request for already-persisted messages (`msg_*`) and a currently active project; Core owns the source content, checksum, metadata, and project membership.

## Academic Sources

First-stage academic source adapters are read-only query adapters for:

- arXiv
- OpenAlex
- Crossref
- Semantic Scholar

The initial adapter returns normalized query URLs and ledger entries. A later worker can fetch, rank, and read source records through the same evidence ledger shape.
