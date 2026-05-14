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
python -m pip install -e 'endpoint_providers/raspberry_pi[gpio]'
meetyou-rpi-endpoint --config user/rpi_endpoint.json
```

## Production health check

```bash
python -m endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.health --config /etc/meetyou/rpi-endpoint.json --env-file /etc/meetyou/rpi-endpoint.env
```

The health check reports `PASS` / `WARN` / `FAIL` for config, token env presence, sandbox writability, `lgpio`, `gpio` group membership, `/dev/gpiochip*` permissions, and systemd status. Token values are never printed.

## Capabilities

- `rpi.echo`
- `rpi.system.info`
- `rpi.gpio.read`
- `rpi.gpio.write`
- `rpi.shell.safe_exec`, disabled unless `security.safe_shell_enabled=true` and `security.safe_shell_allowlist` is non-empty

GPIO uses `gpiozero` with `lgpio` on Raspberry Pi OS. Raspberry Pi 5 must not use the legacy `RPi.GPIO`/native backend; if you see `Cannot determine SOC peripheral base address`, install `lgpio` and set `MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio` in `/etc/meetyou/rpi-endpoint.env`. Local tests and simulation can use the fake GPIO backend.

## Raspberry Pi 5 deployment notes

- Token env key on the Pi: `MEETYOU_RPI_ENDPOINT_TOKEN`.
- GPIO env key on the Pi: `MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio`.
- systemd runs as `meetyou-rpi` with `SupplementaryGroups=gpio`.
- `WorkingDirectory` and `TMPDIR` must stay under `/var/lib/meetyou-rpi`; `lgpio` creates `.lgd-*` runtime files and should not write into `/opt/meetyou/MeetYou`.
- GPIO pins are BCM numbers. Physical header pin 21 is BCM 9; BCM 21 is physical pin 40.

## Safety

The safe shell capability never accepts an arbitrary shell string and never uses `shell=True`. It runs only exact allowlisted argv templates inside the configured sandbox directory. GPIO read/write rejects pins outside `security.gpio_allowed_pins`.

See `docs/endpoints/raspberry-pi.md`, `docs/endpoints/rpi-capabilities.md`, and `docs/endpoints/rpi-security.md` for deployment and security details.

Systemd deployment commands use `bash scripts/rpi/install-systemd.sh` so executable file mode is not required on Windows checkouts.
