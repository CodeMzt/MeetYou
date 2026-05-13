# Raspberry Pi Endpoint Test Report

## 2026-05-12 MVP Progress

Implemented:

- Added `endpoint_providers/raspberry_pi/` package with config loading, protocol mapping, connection runtime, capability registry, OperationRunner, and CLI.
- Added capabilities: `rpi.echo`, `rpi.system.info`, `rpi.gpio.read`, `rpi.gpio.write`, and disabled-by-default `rpi.shell.safe_exec`.
- Added fake GPIO backend for non-Pi local testing.
- Added config example, systemd unit, install/uninstall scripts, and smoke-test script.
- Documented Pi-as-endpoint boundary, capability policy, security model, local simulation, and Pi deployment.

Validation run locally:

```bash
python -m pytest endpoint_providers/raspberry_pi/tests -q
```

Result: `18 passed`.

```bash
python -m pytest tests/test_endpoint_tool_protocol.py tests/test_endpoint_provider_protocols.py -q
```

Result: `10 passed`.

```bash
python -m pytest tests/test_rpi_core_integration.py -q
```

Result: `6 passed`.

## 2026-05-13 Raspberry Pi GPIO Device Permission Fix

Issue observed on hardware:

- `can not open gpiochip` during `rpi.gpio.write`.

Resolution:

- The install script now ensures a `gpio` group exists and adds `meetyou-rpi` to it.
- The systemd unit now declares `SupplementaryGroups=gpio`.
- The GPIO backend can switch to the configured sandbox directory before importing `lgpio`, so manual or non-systemd runs avoid `.lgd-*` files in `/opt/meetyou/MeetYou`.

Manual validation commands:

```bash
id meetyou-rpi
ls -l /dev/gpiochip*
systemctl cat meetyou-rpi-endpoint | grep -E 'User=|Group=|SupplementaryGroups|WorkingDirectory|TMPDIR'
```

## 2026-05-13 Raspberry Pi 5 lgpio Working Directory Fix

Issue observed on hardware:

- `xCreatePipe: Can't set permissions ... /opt/meetyou/MeetYou/.lgd-nfy0` at service startup.

Resolution:

- The systemd unit now uses `WorkingDirectory=/var/lib/meetyou-rpi` and `TMPDIR=/var/lib/meetyou-rpi`.
- This keeps `lgpio` notification pipe files in the writable state directory instead of the protected application checkout under `/opt/meetyou/MeetYou`.

```bash
python -m pytest tests/test_endpoint_tool_protocol.py tests/test_endpoint_provider_protocols.py tests/test_endpoint_protocol_v4.py tests/test_tool_router_v4.py tests/test_rpi_core_integration.py -q
```

Result: `35 passed`.

Core-side issue fixed during integration:

- `ToolRouterService._call_latency_ms()` now handles mixed timezone-aware/timezone-naive datetimes when local SQLite returns one timestamp form and SQLAlchemy defaults produce another. Before the fix, Core could accept endpoint `tool.call.result` / `tool.call.error` but fail while recording endpoint routing latency in local tests.

```bash
python -m endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.main --config user/rpi_endpoint.example.json --simulate --fake-gpio
```

Result: succeeded. Simulation listed `rpi.echo`, `rpi.gpio.read`, `rpi.gpio.write`, and `rpi.system.info`; token status was safely reported as not configured.

```bash
PYTHONPATH=endpoint_providers/raspberry_pi:. python -m meetyou_rpi_endpoint.main --config user/rpi_endpoint.example.json --simulate --fake-gpio
```

Result: succeeded. This verifies the installed-module entrypoint used by the systemd template.

Security checks covered by tests:

- Safe shell is disabled by default.
- Safe shell rejects arbitrary argv input.
- Safe shell executes only a configured template.
- Safe shell is not advertised without enablement plus allowlist.
- GPIO rejects pins outside the allowlist.
- Fake GPIO write/read works on a non-Pi machine.
- Missing token error does not include secret material.

Remaining manual Raspberry Pi validation:

- Install on Raspberry Pi OS / Linux ARM64.
- Confirm `gpiozero` access with the dedicated `meetyou-rpi` user.
- Verify real GPIO read/write with safe pins and physical load.
- Connect to a real Core `/endpoint/ws` with a real token.
- Confirm Core records the `rpi.<endpoint_id>.executor` EndpointCapability snapshot and routes a real Operation through ToolRouter/ExecutionTarget.
- Review systemd journal redaction with real deployment logs.

## 2026-05-13 Raspberry Pi 5 GPIO Backend Fix

Issue observed on hardware:

- `Cannot determine SOC peripheral base address` during `rpi.gpio.write`.

Resolution:

- Default GPIO backend selection now uses gpiozero `lgpio` on Raspberry Pi hardware.
- Added `MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio` deployment guidance and systemd env template comment.
- Updated install script to create the venv with `--system-site-packages` and install the package with GPIO extras.
- GPIO backend failures now return an explicit `gpio_backend_error` / `gpio_lgpio_*` error with remediation guidance instead of surfacing only the low-level SOC message.

Validation:

```bash
python -m pytest endpoint_providers/raspberry_pi/tests -q
```

Result: `21 passed`.

```bash
python -m pytest tests/test_rpi_core_integration.py -q
```

Result: `6 passed`.
