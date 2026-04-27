# AGENT

Canonical repository instructions live in `AGENTS.md`.

V4 non-negotiable rules:

- Core owns Thread / Message / Run / Scheduler / Heartbeat / Memory / Operation / Delivery.
- Client is only Endpoint Provider.
- Core is not Client; `core.local` is an in-process `ExecutionTarget`, not a Client.
- Scheduler is the only system-level scheduling clock.
- `system.heartbeat` is a Scheduler-owned, non-deletable, enable/disable-able system Job with editable interval.
- `endpoint.heartbeat` is connection keepalive only and must not trigger `system.heartbeat`.
- `short_reply` is removed as a directed tool and replaced by `assistant.progress_notice` RunEvent / Runtime Action.
- Delivery delivers `message`, `run_event`, `notice`, and `operation_update`; it does not generate replies.
- Final assistant reply must be an assistant Message persisted by MessageService.
- Streaming must flow through RunEventLog plus Delivery fan-out.
- Tool dispatch must flow through ToolRouter plus ExecutionTarget.
- Permissions live on Actor / Workspace / RunPolicy. Execution ability lives on EndpointCapability.
- Do not keep `/client/ws`, `source_client_id`, `target_client_id`, or `ClientToolDispatchService` compatibility paths.

Follow `AGENTS.md` for directory boundaries, verification order, and the V4 real-test ladder.
