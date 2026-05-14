# Raspberry Pi Endpoint Provider

## Inventory Plan

This MVP is implemented as a MeetYou V4/V5 Endpoint Provider, not as a Core runtime. Repository inspection found an existing provider SDK in `endpoint_tool_sdk/`, an executable reference provider in `edge_client/`, and the formal provider checklist in `docs/v4/endpoint-provider-template.md`. The Raspberry Pi provider therefore reuses the existing `/endpoint/ws` envelope and tool-call frames instead of introducing a new protocol.

Implementation decisions:

- Reuse `endpoint_tool_sdk.protocol` frame builders and `EndpointToolRuntimeBase` transport behavior.
- Add a new provider package under `endpoint_providers/raspberry_pi/` because Raspberry Pi has hardware-specific capabilities that do not belong in the generic `edge_client`.
- Advertise a single execution endpoint, `rpi.<endpoint_id>.executor`; do not create Thread, Message, Run, Scheduler, Heartbeat, Delivery, or Operation state on the Pi.
- Map requested operation terms to current MeetYou frames: Core sends `tool.call.request` with `operation_id` and `call_id`; the Pi returns `tool.call.accepted`, `tool.call.progress`, `tool.call.result`, or `tool.call.error`.
- Keep `endpoint.heartbeat` as connection keepalive only. It must not trigger `system.heartbeat`, which remains Scheduler-owned by Core.
- Start with `rpi.echo`, `rpi.system.info`, low-level `rpi.gpio.read` / `rpi.gpio.write`, named device capabilities, and optional `rpi.shell.safe_exec`; camera, audio, display, and sensor streaming remain future work.
- Keep GPIO and shell policies local, explicit, and deny-by-default. GPIO writes require an allowlisted pin. Safe shell is not advertised unless enabled and an allowlist is configured.

## Architecture Summary

Raspberry Pi is an Endpoint Provider. Core owns durable runtime state: Thread, Message, Run, Scheduler, `system.heartbeat`, Delivery, ToolRouter, Operation records, and persistence. The Pi actively connects to Core through `GET /endpoint/ws`, advertises executable local capabilities through EndpointCapability snapshots, executes only Core-routed tool calls, and reports progress or terminal results back to Core.

The Pi endpoint does not own conversation state, thread history, scheduler state, heartbeat jobs, cross-endpoint delivery policy, or final assistant message generation. Final assistant replies must continue to be persisted by Core MessageService.

## Non-Negotiable Boundary

Core owns durable runtime:

- Thread
- Message
- Run
- Scheduler
- `system.heartbeat`
- Delivery
- ToolRouter
- Operation records
- persistence

Raspberry Pi endpoint does not own:

- conversation state
- thread history
- scheduler state
- heartbeat job
- cross-endpoint delivery policy
- final assistant message generation

Raspberry Pi endpoint provides:

- future input surface, if needed
- future delivery surface, if needed
- executable local capabilities
- hardware integration
- local system observations
- safe local actions

Tool execution must go through Core ToolRouter, ExecutionTarget, Operation, and EndpointCapability. The Pi must not add new `/client/ws` dependencies, `source_client_id` / `target_client_id` primary routing, `ClientToolDispatchService`, or `short_reply` as a final reply path. `endpoint.heartbeat` is connection keepalive only and must not trigger `system.heartbeat`.

## Protocol Mapping

The requested operation vocabulary maps to the existing MeetYou V4 endpoint frames:

| MVP term | Current MeetYou frame |
| --- | --- |
| connect | `GET /endpoint/ws` |
| hello/auth | `endpoint.hello` plus Bearer token |
| ready | `endpoint.ready` from Core after capability snapshot |
| keepalive | `endpoint.heartbeat` |
| capability registration | `endpoint.capabilities.snapshot` |
| operation request | `tool.call.request` with `operation_id` and `call_id` |
| operation progress | `tool.call.progress` |
| operation completed | `tool.call.result` |
| operation failed/cancelled | `tool.call.error` |

The local `OperationRunner` keeps first-MVP idempotency in memory by `operation_id`. Repeated completed operation ids return the stored final summary instead of executing the capability again.

## Local Development

Run focused tests from the repository root:

```bash
python -m pytest endpoint_providers/raspberry_pi/tests -q
```

Run local simulation without a Core token:

```bash
python -m endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.main --config user/rpi_endpoint.example.json --simulate --fake-gpio
```

Run against a real Core:

```bash
cp user/rpi_endpoint.example.json user/rpi_endpoint.json
export MEETYOU_RPI_ENDPOINT_TOKEN='<gateway token>'
python -m endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.main --config user/rpi_endpoint.json
```

Install the package for CLI use:

```bash
python -m pip install -e 'endpoint_providers/raspberry_pi[gpio]'
meetyou-rpi-endpoint --config user/rpi_endpoint.json
```

## Configuration

Example config lives at `user/rpi_endpoint.example.json`. Real local config should be copied to an ignored path such as `user/rpi_endpoint.json`; do not commit real tokens.

Key fields:

- `core_base_url`: Core HTTP base URL; the endpoint converts it to WebSocket for `connect_path`.
- `endpoint_id`: stable provider id, used in `rpi.<endpoint_id>.executor`.
- `endpoint_name`: display name shown in Core endpoint metadata.
- `endpoint_token_env`: environment variable containing the Bearer token.
- `connect_path`: defaults to `/endpoint/ws`.
- `workspace_ids`: workspace seed ids for Core endpoint membership.
- `reconnect`: exponential reconnect backoff.
- `keepalive`: endpoint connection heartbeat interval and timeout policy.
- `operation`: default and max local operation timeout.
- `security`: sandbox, safe-shell allowlist, GPIO allowlist, and default GPIO write duration.
- `devices`: named device abstraction records. Each record uses a stable `device_id`, BCM `pin`, `type`, `direction`, `active_high`, and optional output/input safety fields.

Environment overrides:

- `MEETYOU_RPI_CONFIG`
- `MEETYOU_RPI_CORE_BASE_URL`
- `MEETYOU_RPI_ENDPOINT_ID`
- `MEETYOU_RPI_ENDPOINT_TOKEN`
- `MEETYOU_RPI_SAFE_SHELL_ENABLED`
- `MEETYOU_RPI_FAKE_GPIO`
- `MEETYOU_RPI_GPIO_PIN_FACTORY`, defaults to `lgpio` on Raspberry Pi hardware

## Raspberry Pi Deployment

On Raspberry Pi OS / Linux ARM64:

```bash
sudo apt install -y python3-gpiozero python3-lgpio
sudo REPO_DIR=/opt/meetyou/MeetYou bash scripts/rpi/install-systemd.sh
sudo nano /etc/meetyou/rpi-endpoint.json
sudo nano /etc/meetyou/rpi-endpoint.env
sudo systemctl start meetyou-rpi-endpoint
sudo systemctl status meetyou-rpi-endpoint
journalctl -u meetyou-rpi-endpoint -f
```

A healthy startup shows `hello acknowledged` followed by `ready: {'registered_capability_count': 10}` when safe shell is disabled and the default device capability set is advertised. That confirms Core accepted the endpoint and capability snapshot.

Smoke test before starting systemd:

```bash
bash scripts/rpi/smoke-test.sh
```

The smoke wrapper first runs the production health check, which verifies config presence, token env presence without printing the token, sandbox writability, `lgpio`, `gpio` group membership, `/dev/gpiochip*` permissions, and systemd status with explicit `PASS` / `WARN` / `FAIL` lines. See `docs/endpoints/rpi-operations.md` for the operations runbook and `docs/endpoints/rpi-real-acceptance-2026-05-13.md` for the real Raspberry Pi 5 acceptance record.

When running the health module manually as `meetyou-rpi` from `/var/lib/meetyou-rpi`, include `PYTHONPATH=/opt/meetyou/MeetYou`. The systemd unit already sets it, but manual commands need it so `meetyou_rpi_endpoint` can import the repository-local `endpoint_tool_sdk`.

Raspberry Pi 5 GPIO must use the `lgpio` pin factory. `/etc/meetyou/rpi-endpoint.env` should include:

```bash
MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio
```

If an existing deployment reports `Cannot determine SOC peripheral base address`, the process is using a legacy GPIO backend. Install `python3-lgpio` / `lgpio`, ensure the venv can import it, then restart `meetyou-rpi-endpoint`.

The systemd unit runs with `WorkingDirectory=/var/lib/meetyou-rpi` and `TMPDIR=/var/lib/meetyou-rpi` because `lgpio` creates short-lived `.lgd-*` notification files in the process working directory. Keep runtime files out of `/opt/meetyou/MeetYou`, which is treated as application code and protected read-only by systemd.

To distinguish a missing environment variable from a missing Python dependency, run this on the Pi. Run it from `/var/lib/meetyou-rpi`, not from `/opt/meetyou/MeetYou`, because `lgpio` creates `.lgd-*` notification files in the current working directory:

```bash
sudo install -d -o meetyou-rpi -g meetyou-rpi -m 0750 /var/lib/meetyou-rpi /var/lib/meetyou-rpi/sandbox
sudo -u meetyou-rpi env MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio TMPDIR=/var/lib/meetyou-rpi \
  bash -lc 'cd /var/lib/meetyou-rpi && /opt/meetyou/MeetYou/.venv-rpi/bin/python - <<'"'"'PY'"'"'
import os
print("MEETYOU_RPI_GPIO_PIN_FACTORY=", os.getenv("MEETYOU_RPI_GPIO_PIN_FACTORY"))
for module_name in ("gpiozero", "lgpio"):
    try:
        module = __import__(module_name)
        print(module_name, "OK", getattr(module, "__file__", ""))
    except Exception as exc:
        print(module_name, "FAIL", type(exc).__name__, exc)
try:
    from gpiozero.pins.lgpio import LGPIOFactory
    print("LGPIOFactory OK", LGPIOFactory)
except Exception as exc:
    print("LGPIOFactory FAIL", type(exc).__name__, exc)
PY
'
```

If `MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio` is present but `lgpio` or `LGPIOFactory` fails, rebuild the venv with system site packages after installing OS GPIO packages:

```bash
sudo systemctl stop meetyou-rpi-endpoint
sudo apt install -y python3-gpiozero python3-lgpio
sudo rm -rf /opt/meetyou/MeetYou/.venv-rpi
sudo REPO_DIR=/opt/meetyou/MeetYou bash /opt/meetyou/MeetYou/scripts/rpi/install-systemd.sh
sudo systemctl restart meetyou-rpi-endpoint
```

If GPIO operations fail with `can not open gpiochip`, the service user can import `lgpio` but lacks device permission for `/dev/gpiochip*`. The install script adds `meetyou-rpi` to the `gpio` group and the systemd unit declares `SupplementaryGroups=gpio`. Verify with:

```bash
id meetyou-rpi
ls -l /dev/gpiochip*
systemctl cat meetyou-rpi-endpoint | grep -E 'User=|Group=|SupplementaryGroups|WorkingDirectory|TMPDIR'
```

Remove the systemd unit without deleting config/state:

```bash
sudo bash scripts/rpi/uninstall-systemd.sh
```

## Known Limitations

- Real Raspberry Pi 5 endpoint connection and GPIO write have been manually validated once. Each new circuit, pin allowlist, OS image, and Core deployment still needs local smoke validation.
- `rpi.shell.safe_exec` is disabled by default and only supports exact allowlisted argv templates.
- Camera, audio, display, sensor streaming, and provider-owned human-visible delivery surfaces are intentionally not implemented in this MVP.
- Operation idempotency is process-memory only; reconnect or process restart loses the cache.
- The Pi endpoint does not expose an inbound server port. It only connects outward to Core.
