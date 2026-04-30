# AGENT

Canonical repository instructions live in `AGENTS.md`.

V4 non-negotiable rules:

- Core owns Thread / Message / Run / Scheduler / Heartbeat / Memory / Operation / Delivery.
- Client is only Endpoint Provider.
- Core is not Client; `core.local` is an in-process `ExecutionTarget`, not a Client.
- Scheduler is the only system-level scheduling clock.
- `system.heartbeat` is a Scheduler-owned, non-deletable, enable/disable-able system Job with editable interval.
- Scheduled Workflow is the generic user-facing scheduling protocol: `kind=scheduled_workflow`, `action_ref=core.workflow.scheduled_workflow`, `run_template.schema=meetyou.scheduler.workflow.v1`. Message delivery is one output policy, not the Scheduler core model.
- Use `create_scheduled_workflow` / `manage_scheduled_workflows` for ordinary recurring work, and `create_scheduled_delivery` / `manage_scheduled_deliveries` only when the workflow output must be delivered to an `EndpointAddress`.
- Scheduled Workflow assistant output must persist the final assistant Message. `persist_message=false` is invalid; `create_thread=false` requires an existing `thread_id` or `session_id`.
- Gateway startup must wait for Uvicorn readiness before external Endpoint Providers self-connect. Lifecycle supervision must recover transient external Provider startup failures instead of leaving Feishu/WeChat permanently offline.
- Heart may execute a single `system.heartbeat` run when Scheduler calls it, but Heart must not own a repeating scheduler or heartbeat clock.
- `endpoint.heartbeat` is connection keepalive only and must not trigger `system.heartbeat`.
- `short_reply` is removed as a directed tool and replaced by `assistant.progress_notice` RunEvent / Runtime Action.
- Delivery delivers `message`, `run_event`, `notice`, and `operation_update`; it does not generate replies.
- Final assistant reply must be an assistant Message persisted by MessageService.
- Streaming must flow through RunEventLog plus Delivery fan-out.
- Tool dispatch must flow through ToolRouter plus ExecutionTarget.
- Permissions live on Actor / Workspace / RunPolicy. Execution ability lives on EndpointCapability.
- V4 HTTP facade is `/runtime/*`; local Desktop `/desktop/*` may proxy to `/runtime/*`, `/operator/*`, or `/developer/*`, never to old `/client/*`.
- Do not keep `/client/ws`, `source_client_id`, `target_client_id`, or `ClientToolDispatchService` compatibility paths.
- Runtime assistant modes are limited to `general`, `automation`, and `danxi`. Legacy mode names normalize at the boundary only and must not be persisted as runtime modes.
- Procedure is removed in V4. Do not reintroduce Procedure API, table, tool, pinned fields, prompt layer, or UI; reusable workflow guidance must use SKILL.
- SKILL is the only reusable workflow guide layer. Use `list_skills`, `load_skill`, and `create_skill` plus the capability registry/semantic router path; skill lookup must match titles, summaries, scenarios, and recommended tools.
- This environment rejects `rg`; use PowerShell `Get-ChildItem` / `Select-String`, `git ls-files`, or focused tooling for searches.
- Frontend acceptance must include real browser or Electron execution with screenshot verification, not only typecheck/unit tests.
- Completed tasks must be committed, pushed, and merged back to `main`; keep old plan/design docs for traceability.

Follow `AGENTS.md` for directory boundaries, verification order, and the V4 real-test ladder.
