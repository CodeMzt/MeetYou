# Desktop Endpoint Regression Matrix V4

## Core / Endpoint

- `/endpoint/ws` lifecycle and subscription.
- EndpointCapability registration and replacement on reconnect.
- ToolRouter routes local tools to Desktop Endpoint when policy allows.
- `core.local` tools stay in-process and are not treated as Client calls.

## Conversation

- Thread continuity across UI reconnect.
- User Message persistence.
- Run creation and status updates.
- RunEvent streaming and replay.
- Final assistant Message persistence.
- Non-streaming adapters send only final `message.completed`.

## Scheduler

- `create_scheduled_workflow` / `manage_scheduled_workflows` ordinary scheduled workflow CRUD; `manage_scheduled_jobs` remains low-level Scheduler maintenance.
- `system.heartbeat` list/detail/enable/disable/update interval/trigger.
- `system.heartbeat` delete/create/shape mutation rejected.
- `endpoint.heartbeat` does not trigger system heartbeat.

## UI

- Chinese labels and connection status.
- No Procedure UI.
- Workspace governance exposes mode, memory policy, source profile, endpoint preferences and SKILL guidance.
- Attachments, context usage, runtime debug, Danxi, settings windows open correctly.

## External

- Feishu unique message, human confirms receipt.
- WeChatBot unique message, human confirms receipt.
