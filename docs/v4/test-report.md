# MeetYou V4 Test Report

Status: in progress

## Build Under Test

- Commit sha: pending
- Branch: main
- CI status: pending
- Deploy status: pending

## Local Automated Tests

- Python tests: passed (`python -m unittest discover -s tests -p "test_*.py"`, 507 tests, 1 skipped)
- Frontend typecheck: passed (`npm run typecheck`)
- Frontend build: passed (`npm run build`; build completed with existing chunk-size / metadata warnings)
- Frontend tests: passed (`npm run test`, 16 files / 72 tests)
- Migration tests: passed (`tests.test_db_bootstrap`, `tests.test_db_phase1` through full discovery and V4 targeted ladder)
- Endpoint protocol tests: passed (`tests.test_endpoint_protocol_v4`, `tests.test_endpoint_provider_protocols`, `tests.test_gateway_surface_routes`)
- Scheduler tests: passed (`tests.test_scheduler_v4`)
- Tool router tests: passed (`tests.test_tool_router_v4`)
- Delivery tests: passed (`tests.test_delivery_v4`)

## Local Core + Desktop + UI Real Tests

- Core target: local Core `http://127.0.0.1:8000` with process-level local DB override; `.env` remote Core values were not edited.
- Desktop/UI target: local Desktop bridge reported `core_base_url=http://127.0.0.1:8000`.
- Endpoint provider: `/operator/endpoints` showed both `desktop.mzt-desktop-client.ui` and `desktop.mzt-desktop-client.executor` connected.
- Thread: passed (`thr_6bef39a8951a44c7aa36c12b4e93b611`, `thr_f8643a532d4543f487746169f989bafc`)
- Streaming: passed (`V4_STREAM_OK_20260427022546`, 65 `message.delta` events, `message.completed`)
- `assistant.progress_notice`: passed (`V4_PROGRESS_OK_20260427022633`, received `assistant.progress_notice` RunEvent before final message)
- ToolRouter: passed (`utility.echo` to `desktop.mzt-desktop-client.executor`, operation `op_2cf9e4387f9641f4a597addd50fc3a17`, status `succeeded`)
- Scheduler: passed (`system.heartbeat` service checks exercised enable / disable and interval update / restore)
- `system.heartbeat`: passed (non-deletable; delete rejected with `scheduled job is not deletable: system.heartbeat`; restored interval `600`)
- Endpoint heartbeat separation: passed (`endpoint.heartbeat` did not create any `system.heartbeat` scheduled job run)
- Disconnect / reconnect: passed (new endpoint subscription replayed durable `message.completed` from RunEventLog)

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
