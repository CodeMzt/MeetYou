# MeetYou V5 Design

## Summary

V5 extends V4 instead of replacing the Core-owned runtime boundary. Core still owns durable Thread, Message, Run, Scheduler, Delivery, ToolRouter, and persistence. Endpoint Providers still provide input, delivery surfaces, and executable endpoint capabilities.

V5 adds four user-facing capabilities:

- Deep Research mode and task API.
- Durable conversation branches and checkpoints.
- Edit-and-retry from historical messages.
- Projects as user work containers with shared sources and artifacts.

V5 intentionally does not treat Project as Workspace. Workspace remains the governance and execution boundary. Project is a user organization layer that can sit inside a Workspace and collect threads, sources, artifacts, and project instructions.

## Core Concepts

- `Project`: user-facing work container. It owns project sources, project instructions, artifacts, and optional project-scoped memory policy.
- `ProjectSource`: immutable or versioned source material saved into a project. A source can be a note, message snapshot, file/artifact pointer, or imported document.
- `Artifact`: downloadable generated output. V5 uses an `ArtifactStore` abstraction; local development stores under `user/artifacts/`, production may use S3/R2/object storage.
- `ThreadBranch`: durable conversation branch. Branches make retry/edit/checkpoint non-destructive.
- `ConversationCheckpoint`: named or automatic pointer to a thread branch and leaf message.
- `ResearchTask`: long-running research task state with plan, source policy, evidence ledger, report summary, and output artifact.

## V4 Rules Kept

- Core owns durable runtime state.
- Endpoint Providers do not own conversations, projects, scheduler state, or cross-provider delivery semantics.
- Streaming and progress still use RunEvent/Delivery.
- Tool execution still routes through ToolRouter/ExecutionTarget.
- Local file, general shell, and local MCP capabilities remain endpoint capabilities. `exec_core_cmd` is the explicit Core-host shell exception and remains constrained by the Core whitelist policy.

## V4 Rules Changed

- `research` is a public assistant mode in V5. It must not normalize to `general`.
- Checkpoint/rollback is no longer only session-memory reply control. Durable checkpoints live in PostgreSQL and can survive service restarts. Core automatically creates message-boundary checkpoints as threads advance, so checkout does not rely on users manually preparing checkpoints.
- Retry is no longer limited to the latest assistant reply. Historical user-message edit retry creates a new branch and message revision.
- Projects are not just Workspaces. Do not overload Workspace governance fields for user-facing project source management.

## Public Interfaces

V5 adds `/runtime/projects`, `/runtime/projects/{project_id}/threads`, `/runtime/research-tasks`, `/runtime/artifacts/*`, thread branch/checkpoint endpoints, `POST /runtime/threads/{thread_id}/branches/{branch_id}/activate`, and message edit retry endpoints. Thread create/list/patch routes understand optional `project_id` so a thread can be created inside a project, moved into a project, or detached without changing Workspace governance.

Assistant-facing project operations use `manage_projects` and `manage_project_sources`. These tools expose project CRUD, project thread membership, project source listing/viewing, note creation, and message snapshot saving through Core-owned services, and they are included in the general/research assistant tool exposure paths so the model can manage project context without relying on frontend-only controls. They do not grant endpoint-local file access; imported files must come through separate approved read/file tools and then be saved as project sources or artifacts.

Assistant-facing endpoint listing tools must match the workspace device topology. `list_active_endpoints`, `list_endpoint_tool_targets`, and `/runtime/workspaces/{workspace_id}/endpoints` use managed endpoint-workspace membership first, then legacy `workspace_scope` only as fallback. For online/executable filtering, live WebSocket connection state is authoritative; a connected Raspberry Pi or other endpoint must not be dropped only because its persisted `status` or legacy scope is stale. Endpoint inventory answers must be grounded in these tools, not memory or assumptions, and should report returned endpoint ids, provider types, status, workspace ids, and executable tools compactly without dropping connected providers. Assistant tools return `tool_target_lines`, `executable_tools_by_endpoint`, `endpoint_ids`, and `compact_endpoints` before detailed payloads, with executable endpoints sorted first, so models can still see every connected target when detailed capability records are long.

Assistant-facing list/search tools must be complete before they are verbose. Tool results should put ids, compact lines, counts, and summary maps before long detail records, and should expose explicit detail flags such as `include_details`, `include_endpoint_details`, or `include_address_details` for follow-up inspection. JSON tool-call content must not duplicate the same large payload in both string text and structured data, because that burns model context and can hide later records. Long source summaries, memory facts, job metadata, and address metadata should be returned as bounded previews with `*_truncated` or omitted-count fields, while item-specific detail APIs remain the path for full text.

## Frontend Project Scope

The desktop main window exposes Project as a lightweight scope selector next to the thread selector. Selecting a project filters the thread list to that project. Creating a thread while a project is active sends `project_id` through the runtime thread create API. Selecting an empty project creates and selects the first project thread before switching context, so the message view never shows an unrelated thread under an active project.

The project selector also owns the compact Project settings surface for the active project. Title, description, and project instructions are edited through Core `PATCH /runtime/projects/{project_id}` via the desktop proxy; the UI must not keep a separate frontend-only instruction copy. At the 400x620 desktop size this settings surface stays inside the selector popover so it does not add another top-dock control or force the dock to wrap.

Core injects active Project context into ordinary conversation turns for threads that belong to a project. The injected context includes Project title, description, instructions, and a bounded set of recent active ProjectSource snapshots. This is assembled by Core from durable Project records at turn time and passed as read-only system context; clients must not build their own project prompt layer or send hidden project instructions independently.

Default thread titles are generated by the configured main model after the first user message is persisted. Message persistence only marks eligible default-title threads as `auto_title_pending`; Runtime then runs a small background title-generation call, applies the generated Chinese title without setting `manual_title`, emits `thread.updated`, and lets desktop refresh the thread list. This keeps title generation asynchronous and avoids blocking the first response. It also avoids the poor UX of directly copying the user's full first question into the title. If the model call fails, Core records the failure metadata and leaves the user-editable title unchanged.

Persisted messages expose a compact action menu in the message bubble. The menu can save any persisted message as a ProjectSource when a project is active, edit-and-retry persisted user messages through `/runtime/messages/{message_id}/edit-retry`, and restore or checkout from the automatic checkpoint attached to that message boundary. The edit dialog submits the current textarea value and relies on Core to create the message revision and branch; it must not mutate the original message locally. Message-level restore/checkout must still call Core checkpoint APIs and reload history, not hide later messages locally.

Conversation version controls live next to the project/thread selectors in the floating desktop window. The first branch/checkpoint UI slice lists branch and checkpoint counts, exposes automatic checkpoints created by Core, supports optional manual checkpoints, restores the active thread leaf to a checkpoint, checks out a new branch from a checkpoint, and activates existing branches from the compact branch tree. Restore/checkout/branch activation must reload visible thread history through Core instead of filtering messages locally; Core owns active branch path projection.

Project source controls also live in the top desktop control dock. The first UI slice lists active ProjectSource records for the selected project, can create compact user note sources, archives/deletes active sources through Core, refreshes after saving or deleting a source, and shows a compact source preview with metadata. Delete is an archive operation on the ProjectSource record; it does not delete the original message or artifact referenced by a snapshot. The control is disabled when no project is active; source truth remains Core-owned and the UI must reload from `/runtime/projects/{project_id}/sources` rather than caching note or message-derived content as project state.

Project artifact controls sit beside project sources. The first UI slice lists active project artifacts, shows artifact type, status, size, checksum, timestamp, and selected metadata, and downloads through `/runtime/artifacts/{artifact_id}/download`. The UI must not infer artifact availability only from the current ResearchTask list; artifacts are Core-owned project outputs and can outlive or come from outside the current thread panel.

Research mode remains a protocol value and persisted Core model, but default desktop product UX hides the research composer entry while execution is disabled. The self-maintained adapter path produced user-facing connection failures and is not stable enough to ship as the default deep research experience. `POST /runtime/messages` with `preferred_mode=research` now returns a clear disabled assistant message unless `MEETYOU_RESEARCH_ENABLED=true`; it must not create a stale plan that cannot be executed. When explicitly enabled for a validated provider deployment, research UX is chat-native rather than panel-driven: the first user message is the active-thread topic, Runtime creates/refines a thread-bound `ResearchTask`, persists an editable Chinese plan, suppresses the normal LLM queue, and waits for confirmation before long-running execution. A later explicit confirmation such as `确认开始` starts the task and persists a start acknowledgement in the same thread. Visible research state is bound to the active thread, while project sources and project artifacts remain project-scoped. Running progress is shown as a compact assistant-style status bubble derived from Core state. The UI must not mount a standalone research panel above the message list, display default academic chips, or show stale plan-step statuses as if they were live progress.

Runtime `start` binds a ResearchTask to a Core Run and writes durable `research.*` RunEvents; clients can read `/runtime/research-tasks/{id}/events` with `after_seq` for resumable progress, while compact progress remains available in task metadata. `start` reaches the external `research_adapter` HTTP service by default; GPT Researcher is the first provider, and future providers such as Open Deep Research must use the same adapter contract. Core starts the adapter run, persists `external_run_id`, polls progress/status, and does not cancel the research solely because a fixed total timeout elapsed. Temporary adapter poll failures stay `running` until the configured poll-error budget is exhausted, so a long research run is not failed after only a few transient connection errors. GPT Researcher does not expose reliable per-source live progress through the current adapter path; MeetYou surfaces only real adapter stages/events and does not fabricate per-source or chain-of-thought details. Core still owns source safety, citation validation, Artifact records, derived PDF/DOCX generation, final thread delivery messages, and automatic checkpoints. If the adapter is required but missing, fails, or returns no citeable sources, Core fails the task rather than generating an uncited fallback report. Evidence ledger entries are marked as untrusted evidence-only source text so embedded source instructions are ignored during synthesis. Runtime cancellation is cooperative: Core records cancellation and requests adapter cancellation when possible, and does not create report artifacts or thread delivery messages after cancellation is observed. Thread-bound completed tasks also deliver a persisted assistant Message with a short summary and artifact link(s); the message is attached to the active branch for checkpoint/version visibility, and desktop Markdown rendering routes those artifact links through the authenticated artifact download proxy. Full deep-research parity still requires richer provider controls and production hardening of the external service.

The main Electron window is a constrained floating surface (`400x620` by default, `340x460` minimum). Project/Thread UI must be validated at the real main-window size, not only in wide browser viewports. At the default width the original titlebar remains the window/tool row and must keep pin, memory graph, workspace, Danxi, context/usage, developer tools, settings, minimize, and close visible and clickable. The V5 Project / Thread / Branch / Source / Artifact dock lives in the chat surface below the titlebar as one compact row; controls may collapse to icons and the thread selector may shrink, but the dock must remain visible, non-overlapping, clickable, and must not wrap into another row or steal unnecessary chat vertical space.

Message menus, edit dialogs, version menus, project source popovers, and project artifact popovers must also be validated at the real main-window size. Menus render through a portal and clamp to the visible viewport so bottom-of-thread actions, version popovers, source previews, and artifact previews do not render outside the floating window.

Desktop V5 UI text is Chinese-first. Protocol field names, artifact filenames, ids, and provider-returned metadata can remain in their native form, but visible control labels, empty states, tooltips, and status notices should use Chinese by default.

## Delivery And Verification Workflow

V5 development uses `v5` as the integration branch until the full V5 target is ready for final merge to `main`.

Each phase must produce a concrete phase plan, make scoped changes, run local tests, commit, push `v5`, wait for GitHub Actions CI, wait for the Core deploy workflow to deploy `v5`, then run real runtime/API validation against the deployed Core. Frontend changes additionally require a real browser or Electron screenshot acceptance run.

Full deployed V5 main-chain validation is captured by `scripts/v5_real_acceptance.py`. Run it as `python scripts/v5_real_acceptance.py --base-url <core-url> --expected-branch v5` after `v5` deploys when a phase touches Project, ProjectSource, Artifact, ResearchTask, checkpoint, branch, or edit-retry behavior. The runner creates temporary Core records, validates Project/thread/source APIs including ProjectSource archive/delete, automatic checkpoints, restore/checkout, edit-retry branching, research cancellation and disabled research-mode handling, and archives its temporary project afterward. Full adapter execution/report artifact validation should be run only in deployments where `MEETYOU_RESEARCH_ENABLED=true` and a stable provider has passed separate acceptance. `--cleanup-only` removes leaked acceptance projects/threads by metadata/title marker and asserts no active test resources remain.

The Core deploy workflow is branch-aware. CI success on `main` deploys `main`; CI success on `v5` deploys `v5`. Manual deployment dispatch accepts an explicit branch input, validates it as a Git branch name, fetches that branch on the Core host, and resets the remote working tree to `origin/<branch>` before invoking the host deploy script.

First-stage implementation provides durable API/data skeleton, local ArtifactStore, an external research adapter boundary with a GPT Researcher provider path, and compact branch tree activation/path/sibling variant visibility. A richer visual graph editor remains follow-up work.
