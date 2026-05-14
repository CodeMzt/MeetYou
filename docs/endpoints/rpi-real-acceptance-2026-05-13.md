# Raspberry Pi 5 Real Acceptance - 2026-05-13

This record captures the real hardware acceptance path completed on 2026-05-13. It is not a simulation report.

## Scope

- Device: Raspberry Pi 5.
- Role: MeetYou Endpoint Provider only.
- Protocol: `GET /endpoint/ws` using `meetyou.endpoint.ws.v4`.
- Capabilities validated: `rpi.echo`, `rpi.gpio.write`, and endpoint capability registration.
- Not included: camera, audio, display, sensor streaming, provider-owned final replies, Core redesign, or endpoint protocol redesign.

## Acceptance Evidence

- Core saw the endpoint online after `endpoint.hello`; hello was acknowledged.
- Core sent ready after capability snapshot; `registered_capability_count = 4`.
- `rpi.echo` executed successfully through Core-routed tool execution.
- `rpi.gpio.write` executed successfully on real Raspberry Pi GPIO.
- GPIO backend was `lgpio`.
- systemd unit used `SupplementaryGroups=gpio`.
- Runtime state and working directory used `/var/lib/meetyou-rpi`.
- GPIO pin arguments used BCM numbering.
- A `can not open gpiochip` failure was diagnosed as a `/dev/gpiochip*` permission or group problem, not a ToolRouter or Core routing problem.

## Production Invariants Confirmed

- Core owns Thread, Message, Run, Scheduler, Delivery, ToolRouter, Operation records, and persistence.
- Raspberry Pi endpoint actively connects to Core and does not expose an inbound Pi server.
- The Pi advertises EndpointCapability snapshots and executes only Core-routed `tool.call.request` frames.
- Results return through `tool.call.accepted`, `tool.call.progress`, `tool.call.result`, or `tool.call.error`.
- `endpoint.heartbeat` remains connection keepalive only and does not trigger Scheduler-owned `system.heartbeat`.
- `/client/ws` was not reintroduced.
- `source_client_id` and `target_client_id` were not reintroduced as primary routing concepts.
- Arbitrary shell execution stayed disabled.
- GPIO writes stayed constrained by `security.gpio_allowed_pins`.
- Tokens stayed in environment/configuration paths and were not committed.

## Follow-Up Operational Baseline

Before treating a new Pi image, new circuit, or new Core deployment as production-ready, rerun:

```bash
bash scripts/rpi/smoke-test.sh /etc/meetyou/rpi-endpoint.json
```

Then verify from Core:

- Endpoint online.
- `registered_capability_count = 4` when safe shell is disabled.
- `rpi.echo` succeeds.
- `rpi.system.info` reports `gpio.backend` and endpoint metadata.
- `rpi.gpio.write` succeeds on an allowlisted BCM pin and rejects a non-allowlisted pin.

Keep this acceptance record separate from local fake-GPIO tests. Fake GPIO proves local dispatch behavior only; it does not prove Raspberry Pi 5 device permissions or `lgpio` runtime behavior.
