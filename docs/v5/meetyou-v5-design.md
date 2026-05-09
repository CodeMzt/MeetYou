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
- Checkpoint/rollback is no longer only session-memory reply control. Durable checkpoints live in PostgreSQL and can survive service restarts.
- Retry is no longer limited to the latest assistant reply. Historical user-message edit retry creates a new branch and message revision.
- Projects are not just Workspaces. Do not overload Workspace governance fields for user-facing project source management.

## Public Interfaces

V5 adds `/runtime/projects`, `/runtime/research-tasks`, `/runtime/artifacts/*`, thread branch/checkpoint endpoints, and message edit retry endpoints. Desktop `/desktop/*` may proxy these routes to `/runtime/*`.

First-stage implementation provides durable API/data skeleton and local ArtifactStore. Full background research execution and full project/branch UI are follow-up work.
