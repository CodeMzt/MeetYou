# Raspberry Pi Core Integration Report

## Status

The local integration path is covered by `tests/test_rpi_core_integration.py`. It does not start the full Core service process or a real WebSocket server, but it uses the real Core gateway frame handlers, `EndpointWebSocketManager`, `EndpointCapabilityService`, `ToolRouterService`, `OperationService`, and `OperationCallService`.

The test simulates a Raspberry Pi endpoint connecting through the existing `meetyou.endpoint.ws.v4` frames, registering Pi capabilities, receiving a Core-routed `tool.call.request`, executing the request through the Pi capability registry/OperationRunner, and sending `tool.call.accepted`, `tool.call.progress`, `tool.call.result`, or `tool.call.error` back through Core gateway handlers.

## Chain Verified Locally

Verified:

- Core accepts Raspberry Pi `endpoint.hello` and creates `rpi.<endpoint_id>.executor`.
- Core accepts Raspberry Pi `endpoint.capabilities.snapshot`.
- `EndpointCapabilityService` records `rpi.echo`, `rpi.system.info`, `rpi.gpio.read`, and `rpi.gpio.write`.
- `rpi.shell.safe_exec` remains absent by default.
- ToolRouter resolves `rpi.echo` to the Raspberry Pi endpoint as an `ExecutionTarget`.
- ToolRouter creates an Operation and OperationCall before dispatch.
- Core sends `tool.call.request` through the endpoint WebSocket manager to the Pi endpoint.
- Fake Pi execution returns `tool.call.accepted`, `tool.call.progress`, and `tool.call.result` for `rpi.echo`.
- Core records the completed Operation/OperationCall result.
- Fake Pi execution returns `tool.call.error` for a denied GPIO pin.
- Core records the failed Operation/OperationCall error.
- Core publishes `delivery.operation_update` to an operation subscription for accepted, running, completed, and failed phases.
- Disconnected Pi endpoint resolution returns a clear `target_endpoint_unavailable` ToolRouter error.
- GPIO allowlist remains enforced in the Pi runner.

The integration test also found and fixed a Core-side SQLite/local-test bug: endpoint routing latency calculation could subtract one timezone-aware datetime from one timezone-naive datetime. `ToolRouterService._call_latency_ms()` now falls back to timestamp subtraction for mixed timezone values.

## Simulation Boundary

Simulated:

- No real Uvicorn/FastAPI server is started.
- No real network WebSocket is opened.
- No real Raspberry Pi GPIO hardware is used.
- The Pi endpoint response is driven by the local Pi registry and OperationRunner inside the test process.
- Operation updates are delivered through the in-process `EndpointWebSocketManager`, not across an actual desktop/Electron subscription.

Not simulated:

- Gateway authentication.
- Real Core process lifecycle.
- Physical GPIO permissions on Raspberry Pi OS.
- Real assistant turn orchestration or final assistant Message persistence.
- Remote deployment, CI, or systemd process supervision.

## How To Trigger From Core

With a real Pi endpoint connected and capability snapshot registered, Core can dispatch through ToolRouter with an explicit endpoint:

```python
result = await core_domain.services.tool_router.dispatch_tool_call(
    tool_key="rpi.echo",
    arguments={"text": "hello pi"},
    workspace_id="personal",
    target_endpoint_id="rpi.raspberry-pi-dev.executor",
    confirmed=True,
    return_operation=True,
)
```

For system info:

```python
result = await core_domain.services.tool_router.dispatch_tool_call(
    tool_key="rpi.system.info",
    arguments={},
    workspace_id="personal",
    target_endpoint_id="rpi.raspberry-pi-dev.executor",
    confirmed=True,
    return_operation=True,
)
```

Without an explicit endpoint, ToolRouter can auto-select a connected endpoint that advertises the requested `tool_key`, subject to Workspace policy, connectivity, risk/confirmation, and routing scores:

```python
result = await core_domain.services.tool_router.dispatch_tool_call(
    tool_key="rpi.echo",
    arguments={"text": "auto target"},
    workspace_id="personal",
    confirmed=True,
    return_operation=True,
)
```

For HTTP-facing/manual validation, use the existing runtime operation route once Core is running and the Pi endpoint is connected:

```http
POST /runtime/operations
Authorization: Bearer <token>
Content-Type: application/json

{
  "workspace_id": "personal",
  "tool_key": "rpi.echo",
  "arguments": {"text": "hello pi"},
  "target_endpoint_id": "rpi.raspberry-pi-dev.executor",
  "confirmed": true
}
```

If the runtime route shape changes, prefer the ToolRouter service call above as the authoritative internal contract and inspect `gateway/routes/runtime.py` for the current facade fields.

## Validation Commands

```bash
python -m pytest tests/test_rpi_core_integration.py -q
```

Result: `6 passed`.

```bash
python -m pytest endpoint_providers/raspberry_pi/tests -q
```

Result: `18 passed`.

```bash
python -m pytest tests/test_endpoint_tool_protocol.py tests/test_endpoint_provider_protocols.py tests/test_endpoint_protocol_v4.py tests/test_tool_router_v4.py tests/test_rpi_core_integration.py -q
```

Result: `35 passed`.

## Remaining Real Raspberry Pi Validation

- Start Core normally and confirm `/endpoint/ws` accepts the real Pi token.
- Start the Pi endpoint under systemd on Raspberry Pi OS.
- Confirm Core lists `rpi.<endpoint_id>.executor` as connected.
- Confirm Core lists `rpi.echo`, `rpi.system.info`, and `rpi.gpio.read` as enabled EndpointCapabilities.
- Trigger `rpi.echo` from Core and confirm the Operation transitions through queued/dispatching/running/succeeded.
- Trigger `rpi.system.info` and verify non-Pi-optional fields such as temperature are handled safely.
- Trigger `rpi.gpio.read` on an allowed physical pin.
- Trigger `rpi.gpio.read` on a denied pin and confirm Core records a failed Operation with `gpio_pin_not_allowed`.
- Confirm a subscribed Desktop/Electron surface receives `delivery.operation_update`.
- Confirm `endpoint.heartbeat` updates connection state only and does not trigger Scheduler-owned `system.heartbeat`.

