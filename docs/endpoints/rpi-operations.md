# Raspberry Pi Endpoint Operations

This runbook is for operating the Raspberry Pi 5 Endpoint Provider after the MVP hardware path has been validated. The Pi remains an Endpoint Provider only: Core owns Thread, Message, Run, Scheduler, Delivery, ToolRouter, Operation records, and persistence.

## Health And Smoke Test

Run the production health check as the service user on the Pi:

```bash
sudo -u meetyou-rpi env PYTHONPATH=/opt/meetyou/MeetYou TMPDIR=/var/lib/meetyou-rpi \
  bash -lc 'cd /var/lib/meetyou-rpi && /opt/meetyou/MeetYou/.venv-rpi/bin/python -m meetyou_rpi_endpoint.health --config /etc/meetyou/rpi-endpoint.json --env-file /etc/meetyou/rpi-endpoint.env'
```

Keep `PYTHONPATH=/opt/meetyou/MeetYou` in manual commands that run from `/var/lib/meetyou-rpi`. The installed Pi package imports the repository-local `endpoint_tool_sdk`; the systemd unit already sets `PYTHONPATH`, but ad hoc `sudo -u meetyou-rpi ... python -m meetyou_rpi_endpoint.health` commands must set it explicitly.

Or use the wrapper:

```bash
sudo REPO_DIR=/opt/meetyou/MeetYou PYTHON_BIN=/opt/meetyou/MeetYou/.venv-rpi/bin/python PYTHONPATH=/opt/meetyou/MeetYou \
  bash /opt/meetyou/MeetYou/scripts/rpi/smoke-test.sh /etc/meetyou/rpi-endpoint.json
```

The health check prints one line per check with `PASS`, `WARN`, or `FAIL`. It verifies:

- Config file exists and loads.
- Token environment variable exists; the value is never printed.
- `security.sandbox_dir` is writable.
- GPIO backend is available and Raspberry Pi 5 uses `gpiozero` with `lgpio`.
- Current user is in the `gpio` group.
- `/dev/gpiochip*` devices are readable and writable by the process user.
- `meetyou-rpi-endpoint.service` state is visible through systemd.

`FAIL` means the endpoint is not production-ready. `WARN` means the check is not applicable or not fully validated in the current shell, for example running on a non-Pi development machine.

## Expected Production Shape

- Service user: `meetyou-rpi`.
- Supplementary group: `gpio`.
- Working directory: `/var/lib/meetyou-rpi`.
- Sandbox directory: `/var/lib/meetyou-rpi/sandbox`.
- GPIO factory: `MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio`.
- Token env: `MEETYOU_RPI_ENDPOINT_TOKEN` in `/etc/meetyou/rpi-endpoint.env`.
- Config: `/etc/meetyou/rpi-endpoint.json`.
- No inbound Pi server. The endpoint connects outward to Core with `GET /endpoint/ws`.

Check the unit:

```bash
systemctl cat meetyou-rpi-endpoint | grep -E 'User=|Group=|SupplementaryGroups|WorkingDirectory|TMPDIR|EnvironmentFile'
systemctl status meetyou-rpi-endpoint
journalctl -u meetyou-rpi-endpoint -n 100 --no-pager
```

Do not print or paste tokens from `/etc/meetyou/rpi-endpoint.env` into logs, tickets, or commits.

## GPIO Diagnostics

Raspberry Pi GPIO arguments use BCM numbering, not physical header pin numbers. Physical header pin 21 is BCM 9; BCM 21 is physical header pin 40.

If a GPIO operation fails with `can not open gpiochip`, treat it as a Linux device permission or group problem, not as a ToolRouter problem. Verify:

```bash
id meetyou-rpi
ls -l /dev/gpiochip*
systemctl cat meetyou-rpi-endpoint | grep -E 'SupplementaryGroups|User=|Group='
```

If imports fail, rebuild the Pi venv after installing OS GPIO packages:

```bash
sudo apt install -y python3-gpiozero python3-lgpio
sudo systemctl stop meetyou-rpi-endpoint
sudo rm -rf /opt/meetyou/MeetYou/.venv-rpi
sudo REPO_DIR=/opt/meetyou/MeetYou bash /opt/meetyou/MeetYou/scripts/rpi/install-systemd.sh
sudo systemctl restart meetyou-rpi-endpoint
```

Run GPIO diagnostics from `/var/lib/meetyou-rpi`, not from `/opt/meetyou/MeetYou`, because `lgpio` creates short-lived `.lgd-*` files in the process working directory.

## Device Configuration And Diagnostics

Named devices live in the Raspberry Pi endpoint config under `devices`. Every configured device pin must also be listed in `security.gpio_allowed_pins`; startup rejects duplicate `device_id` values, pins outside the allowlist, invalid direction/type pairs, and invalid input pull modes.

Minimal examples:

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

Operational checks after editing `/etc/meetyou/rpi-endpoint.json`:

```bash
sudo -u meetyou-rpi env PYTHONPATH=/opt/meetyou/MeetYou TMPDIR=/var/lib/meetyou-rpi \
  bash -lc 'cd /var/lib/meetyou-rpi && /opt/meetyou/MeetYou/.venv-rpi/bin/python -m meetyou_rpi_endpoint.health --config /etc/meetyou/rpi-endpoint.json --env-file /etc/meetyou/rpi-endpoint.env'
sudo systemctl restart meetyou-rpi-endpoint
journalctl -u meetyou-rpi-endpoint -n 100 --no-pager
```

Device capability failures are intentionally specific:

- `device_not_found`: the requested `device_id` is not configured.
- `device_pin_not_allowed` or `gpio_pin_not_allowed`: config or runtime pin is outside `security.gpio_allowed_pins`.
- `device_permission_denied`: a write was attempted on an input device or a button read targeted a non-button device.
- `invalid_device_*`: malformed value, duration, blink count, interval, or config.
- `gpio_unavailable` / `gpio_backend_*`: `gpiozero` / `lgpio` is missing or cannot access `/dev/gpiochip*`.

Relay devices default to requiring Core confirmation. Because the endpoint protocol does not include a per-operation confirmation receipt, the Pi advertises write-class device capabilities with `requires_confirmation=true` whenever any configured output device requires confirmation. If a deployment has only LEDs or explicitly sets a relay `requires_confirmation=false`, the advertised flag can be false.

## Runtime Acceptance Signals

A healthy Pi endpoint shows:

- Core acknowledges `endpoint.hello`.
- Core sends `endpoint.ready` with `registered_capability_count = 10` when safe shell is disabled and the default device capability set is advertised.
- `rpi.echo` returns the requested text.
- `rpi.system.info` returns hostname, platform, Python version, uptime, memory, disk, optional CPU temperature, GPIO backend info, endpoint version, and git commit when available.
- `rpi.gpio.write` succeeds only for pins in `security.gpio_allowed_pins`.
- `rpi.device.list` returns configured devices without tokens or secrets.
- `rpi.device.set`, `rpi.device.pulse`, and `rpi.device.blink` operate only on `direction=out` devices and enforce duration/count limits.
- `rpi.button.read` operates only on configured button inputs.

`rpi.shell.safe_exec` must remain absent unless both `security.safe_shell_enabled=true` and a reviewed allowlist are configured.

## Restart And Rollback

Restart the endpoint only:

```bash
sudo systemctl restart meetyou-rpi-endpoint
```

This does not touch Core database state because the Pi provider owns no durable Thread, Message, Run, Scheduler, Delivery, ToolRouter, Operation, or persistence records. If Core itself is rolled back, Core Service still owns database migration and protocol negotiation; keep a matching PostgreSQL snapshot for safe Core rollback.
