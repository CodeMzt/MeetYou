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

V5 adds `/runtime/projects`, `/runtime/projects/{project_id}/threads`, `/runtime/research-tasks`, `/runtime/artifacts/*`, thread branch/checkpoint endpoints, and message edit retry endpoints. Thread create/list/patch routes understand optional `project_id` so a thread can be created inside a project, moved into a project, or detached without changing Workspace governance.

Assistant-facing project operations use `manage_projects` and `manage_project_sources`. These tools expose project CRUD, project thread membership, project source listing/viewing, note creation, and message snapshot saving through Core-owned services. They do not grant endpoint-local file access; imported files must come through separate approved read/file tools and then be saved as project sources or artifacts.

## Frontend Project Scope

The desktop main window exposes Project as a lightweight scope selector next to the thread selector. Selecting a project filters the thread list to that project. Creating a thread while a project is active sends `project_id` through the runtime thread create API. Selecting an empty project creates and selects the first project thread before switching context, so the message view never shows an unrelated thread under an active project.

Persisted messages expose a compact action menu in the message bubble. The menu can save any persisted message as a ProjectSource when a project is active, and it can edit-and-retry persisted user messages through `/runtime/messages/{message_id}/edit-retry`. The edit dialog submits the current textarea value and relies on Core to create the message revision and branch; it must not mutate the original message locally.

Conversation version controls live next to the project/thread selectors in the floating desktop window. The first branch/checkpoint UI slice lists branch and checkpoint counts, exposes automatic checkpoints created by Core, supports optional manual checkpoints, restores the active thread leaf to a checkpoint, and checks out a new branch from a checkpoint. Restore/checkout must reload visible thread history through Core instead of filtering messages locally; Core owns active branch path projection.

Project source controls also live in the top desktop control dock. The first UI slice lists active ProjectSource records for the selected project, refreshes after saving a message snapshot, and shows a compact source preview with metadata. The control is disabled when no project is active; source truth remains Core-owned and the UI must reload from `/runtime/projects/{project_id}/sources` rather than caching message-derived content as project state.

Project artifact controls sit beside project sources. The first UI slice lists active project artifacts, shows artifact type, status, size, checksum, timestamp, and selected metadata, and downloads through `/runtime/artifacts/{artifact_id}/download`. The UI must not infer artifact availability only from the current ResearchTask list; artifacts are Core-owned project outputs and can outlive or come from outside the current thread panel.

Research mode is selectable from the desktop composer. The first research UI slice exposes ResearchTask intake, plan viewing/editing before start, approve/start/cancel actions, task refresh, and artifact download. `start` now reaches a conservative Core read-only runner that can gather implemented academic adapters and project sources into an evidence ledger and persist a Markdown report artifact. Full deep-research parity still requires later progress streaming, richer ranking/reading, web-search integration, and PDF/DOCX derivation.

The main Electron window is a constrained floating surface (`400x620` by default, `340x460` minimum). Project/Thread UI must be validated at the real main-window size, not only in wide browser viewports. At the default width the project trigger may collapse to an icon while preserving the full project title in the button tooltip.

Message menus, edit dialogs, version menus, project source popovers, and project artifact popovers must also be validated at the real main-window size. Menus render through a portal and clamp to the visible viewport so bottom-of-thread actions, version popovers, source previews, and artifact previews do not render outside the floating window.

## Delivery And Verification Workflow

V5 development uses `v5` as the integration branch until the full V5 target is ready for final merge to `main`.

Each phase must produce a concrete phase plan, make scoped changes, run local tests, commit, push `v5`, wait for GitHub Actions CI, wait for the Core deploy workflow to deploy `v5`, then run real runtime/API validation against the deployed Core. Frontend changes additionally require a real browser or Electron screenshot acceptance run.

The Core deploy workflow is branch-aware. CI success on `main` deploys `main`; CI success on `v5` deploys `v5`. Manual deployment dispatch accepts an explicit branch input, validates it as a Git branch name, fetches that branch on the Core host, and resets the remote working tree to `origin/<branch>` before invoking the host deploy script.

First-stage implementation provides durable API/data skeleton and local ArtifactStore. Full background research execution and a complete sibling-variant browser are follow-up work.
