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
sudo -u meetyou-rpi env PYTHONPATH=/opt/meetyou/MeetYou TMPDIR=/var/lib/meetyou-rpi \
  bash -lc 'cd /var/lib/meetyou-rpi && /opt/meetyou/MeetYou/.venv-rpi/bin/python -m meetyou_rpi_endpoint.health --config /etc/meetyou/rpi-endpoint.json --env-file /etc/meetyou/rpi-endpoint.env'
```

The health check reports `PASS` / `WARN` / `FAIL` for config, token env presence, sandbox writability, `lgpio`, `gpio` group membership, `/dev/gpiochip*` permissions, and systemd status. Token values are never printed.

Manual service-user checks need `PYTHONPATH=/opt/meetyou/MeetYou` because the endpoint package imports the repository-local `endpoint_tool_sdk`. The systemd unit sets this automatically for the running service.

## Capabilities

- `rpi.echo`
- `rpi.system.info`
- `rpi.gpio.read`
- `rpi.gpio.write`
- `rpi.device.list`
- `rpi.device.status`
- `rpi.device.set`
- `rpi.device.pulse`
- `rpi.device.blink`
- `rpi.button.read`
- `rpi.shell.safe_exec`, disabled unless `security.safe_shell_enabled=true` and `security.safe_shell_allowlist` is non-empty

GPIO uses `gpiozero` with `lgpio` on Raspberry Pi OS. Raspberry Pi 5 must not use the legacy `RPi.GPIO`/native backend; if you see `Cannot determine SOC peripheral base address`, install `lgpio` and set `MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio` in `/etc/meetyou/rpi-endpoint.env`. Local tests and simulation can use the fake GPIO backend.

The device capabilities wrap allowlisted BCM GPIO pins with named config records. They are safer for ordinary assistant use than raw GPIO because they validate `device_id`, type/direction, pulse duration, blink count, blink interval, and relay confirmation policy while preserving the low-level `rpi.gpio.read` / `rpi.gpio.write` primitives for diagnostics.

Example device config:

```json
{
  "security": {
    "gpio_allowed_pins": [17, 27, 22]
  },
  "devices": [
    {
      "device_id": "desk_led",
      "type": "led",
      "name": "Desk LED",
      "pin": 17,
      "direction": "out",
      "active_high": true,
      "max_on_ms": 5000,
      "requires_confirmation": false
    },
    {
      "device_id": "relay_1",
      "type": "relay",
      "name": "Relay 1",
      "pin": 27,
      "direction": "out",
      "active_high": true,
      "max_on_ms": 3000
    },
    {
      "device_id": "button_1",
      "type": "button",
      "name": "Button 1",
      "pin": 22,
      "direction": "in",
      "active_high": false,
      "pull": "up"
    }
  ]
}
```

All `pin` values are BCM numbers and must also be present in `security.gpio_allowed_pins`. Relays default to `requires_confirmation=true` when the field is omitted.

## Raspberry Pi 5 deployment notes

- Token env key on the Pi: `MEETYOU_RPI_ENDPOINT_TOKEN`.
- GPIO env key on the Pi: `MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio`.
- systemd runs as `meetyou-rpi` with `SupplementaryGroups=gpio`.
- `WorkingDirectory` and `TMPDIR` must stay under `/var/lib/meetyou-rpi`; `lgpio` creates `.lgd-*` runtime files and should not write into `/opt/meetyou/MeetYou`.
- GPIO pins are BCM numbers. Physical header pin 21 is BCM 9; BCM 21 is physical pin 40.

## Safety

The safe shell capability never accepts an arbitrary shell string and never uses `shell=True`. It runs only exact allowlisted argv templates inside the configured sandbox directory. GPIO read/write rejects pins outside `security.gpio_allowed_pins`. Device operations reject unknown `device_id` values, input-device writes, forbidden pins, unbounded pulses, and excessive blink requests.

See `docs/endpoints/raspberry-pi.md`, `docs/endpoints/rpi-capabilities.md`, and `docs/endpoints/rpi-security.md` for deployment and security details.

Systemd deployment commands use `bash scripts/rpi/install-systemd.sh` so executable file mode is not required on Windows checkouts.
