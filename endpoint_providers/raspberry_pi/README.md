# MeetYou Raspberry Pi Endpoint Provider

This package runs a Raspberry Pi as a MeetYou Endpoint Provider. It connects outward to Core through `/endpoint/ws`, registers local executable capabilities, handles Core-routed tool calls, and reports progress/result/error frames. It does not own Core runtime state.

## Local simulation

From the repository root:

```bash
python -m endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.main --config user/rpi_endpoint.example.json --simulate --fake-gpio
```

Simulation does not require a Core token and runs local capability checks only.

## Run against Core

```bash
export MEETYOU_RPI_ENDPOINT_TOKEN='<token from Core/Gateway config>'
python -m endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.main --config user/rpi_endpoint.json
```

Installable CLI form after editable install:

```bash
python -m pip install -e endpoint_providers/raspberry_pi
meetyou-rpi-endpoint --config user/rpi_endpoint.json
```

## Capabilities

- `rpi.echo`
- `rpi.system.info`
- `rpi.gpio.read`
- `rpi.gpio.write`
- `rpi.shell.safe_exec`, disabled unless `security.safe_shell_enabled=true` and `security.safe_shell_allowlist` is non-empty

GPIO uses `gpiozero` on Raspberry Pi OS when available. Local tests and simulation can use the fake GPIO backend.

## Safety

The safe shell capability never accepts an arbitrary shell string and never uses `shell=True`. It runs only exact allowlisted argv templates inside the configured sandbox directory. GPIO read/write rejects pins outside `security.gpio_allowed_pins`.

See `docs/endpoints/raspberry-pi.md`, `docs/endpoints/rpi-capabilities.md`, and `docs/endpoints/rpi-security.md` for deployment and security details.

Systemd deployment commands use `bash scripts/rpi/install-systemd.sh` so executable file mode is not required on Windows checkouts.
