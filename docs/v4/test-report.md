# MeetYou V4 Test Report

Status: in progress

## Build Under Test

- Commit sha: pending
- Branch: main
- CI status: pending
- Deploy status: pending

## Local Automated Tests

- Python tests: passed (`python -m unittest discover -s tests -p "test_*.py"`, 504 tests, 7 skipped)
- Frontend typecheck: passed (`npm run typecheck`)
- Frontend build: passed (`npm run build`; build completed with existing chunk-size / metadata warnings)
- Frontend tests: passed (`npm run test`, 17 files / 71 tests)
- Migration tests: passed (`tests.test_db_bootstrap`, `tests.test_db_phase1` through full discovery and V4 targeted ladder)
- Endpoint protocol tests: passed (`tests.test_endpoint_protocol_v4`, `tests.test_endpoint_provider_protocols`, `tests.test_gateway_surface_routes`, `tests.test_endpoint_tool_protocol`)
- Scheduler tests: passed (`tests.test_scheduler_job_runtime_v4`, `tests.test_scheduler_tools_v4`)
- Tool router tests: passed (`tests.test_tool_router_v4`)
- Delivery tests: passed (`tests.test_delivery_v4`)

## Local Core + Desktop + UI Real Tests

- Core target: local Core `http://127.0.0.1:8000` with process-level local DB override; `.env` remote Core values were not edited.
- Desktop/UI target: local Desktop bridge reported `core_base_url=http://127.0.0.1:8000`.
- Endpoint provider: `/operator/endpoints` showed both `desktop.mzt-desktop-client.ui` and `desktop.mzt-desktop-client.executor` connected.
- Real acceptance script: passed (`.venv\Scripts\python.exe scripts\v4_real_acceptance.py --base-url http://127.0.0.1:8000 --ui-url http://localhost:5173`)
- Unique marker: `V4OK_20260428173924_5391e3`
- Thread: passed (`thr_ce922defd260453cb9602576faf1aa89`)
- Non-streaming final delivery: passed (`delivery.message` delivered once; persisted assistant message `msg_3bf832a57b7f41beb3d672bac8ca5776`; marker appeared once, not duplicated)
- `assistant.progress_notice`: passed (received `assistant.progress_notice` RunEvent before final message)
- Final assistant Message persistence: passed (final reply came from MessageService-persisted assistant message)
- ToolRouter: passed (`utility.echo` routed to synthetic V4 endpoint provider `desktop.v4check-5d9ea2a8.executor`; operation `op_3c70806f85ed49bcb0a5ca70736b9264`; `delivery.operation_update` completed)
- Scheduler: passed (`system.heartbeat` interval round-trip and disposable user scheduled job create / delete)
- `system.heartbeat`: passed (non-deletable; delete rejected; interval `600`)
- Endpoint heartbeat separation: passed (`endpoint.heartbeat` was accepted as connection keepalive and did not trigger system heartbeat behavior)
- Disconnect / reconnect: passed (new endpoint subscription replayed durable RunEventLog event, seq `15`)
- UI dev server: passed (`http://localhost:5173/` returned 200; stale waiting placeholder was not present in HTML)
- Note: one preceding run timed out waiting for final model output after progress notice; rerun passed with the marker above. No duplicate delivery was observed in the passing non-streaming run.

## Remote Core Verification

- `/health`: pending
- Version / commit sha: pending

## Local Desktop -> Remote Core Real Tests

- Conversation: pending
- Streaming: pending
- `assistant.progress_notice`: pending
- Local tools: pending
- Scheduler: pending
- Heartbeat: pending
- Disconnect / reconnect: pending

## External Delivery Human Feedback

- Feishu unique message: pending
- Feishu human confirmation: pending
- WeChatBot unique message: pending
- WeChatBot human confirmation: pending
