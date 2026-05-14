# Raspberry Pi Capability Catalog

Raspberry Pi capabilities are endpoint-local executable tools advertised through `endpoint.capabilities.snapshot`. Core still owns ToolRouter, ExecutionTarget, Operation records, permissions, and final assistant messages.

## Registered By Default

### `rpi.echo`

- Risk: `read`
- Confirmation: no
- Input: `{ "text": string }`
- Output: `{ "text": string }`
- Purpose: safe local routing and operation smoke test.

### `rpi.system.info`

- Risk: `read`
- Confirmation: no
- Input: empty object
- Output: hostname, platform, Python version, uptime when available, memory summary when available, disk summary, CPU temperature when available, GPIO backend info, endpoint version, and git commit when available.
- Notes: CPU temperature and `/proc` data are optional. The capability must not fail on non-Pi development machines just because those files are absent.

### `rpi.gpio.read`

- Risk: `read`
- Confirmation: no
- Input: `{ "pin": integer }`
- Output: `{ "pin": integer, "value": boolean }`
- Policy: rejects any pin not listed in `security.gpio_allowed_pins`.
- Local dev: fake backend is available through `--fake-gpio` or `MEETYOU_RPI_FAKE_GPIO=1`.
- Raspberry Pi 5: uses the `lgpio` gpiozero pin factory. Set `MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio`; `Cannot determine SOC peripheral base address` means a legacy GPIO backend was selected.
- Pin numbering: all GPIO capability arguments use BCM numbers, not physical header pin numbers. Physical pin 21 is BCM 9; BCM 21 is physical pin 40.

### `rpi.gpio.write`

- Risk: `local_write`
- Confirmation: yes
- Input: `{ "pin": integer, "value": boolean|0|1, "duration_ms"?: integer }`
- Output: pin, value, duration, backend, and whether reset was performed.
- Policy: rejects any pin not listed in `security.gpio_allowed_pins`.
- Duration: if `duration_ms` is omitted, `security.gpio_write_default_duration_ms` is used. A duration of `0` leaves the value set until a later call changes it.
- Raspberry Pi 5: requires `lgpio`; install `python3-lgpio` or pip package `lgpio` and keep the service env set to `MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio`.
- Device access: `can not open gpiochip` means the service user lacks `/dev/gpiochip*` permission. The deployment path adds `meetyou-rpi` to the `gpio` group and the systemd unit uses `SupplementaryGroups=gpio`.

### Device abstraction capabilities

These wrap allowlisted GPIO pins with named, typed device records from `devices` in the Raspberry Pi endpoint config. They do not replace `rpi.gpio.read` / `rpi.gpio.write`; the low-level primitives remain available for diagnostics and controlled one-off operations.

Device config fields:

- `device_id`: stable identifier used in operation arguments, for example `desk_led`.
- `type`: `led`, `relay`, `output`, `button`, or `input`.
- `name`: human-readable display name.
- `pin`: BCM GPIO number; it must also appear in `security.gpio_allowed_pins`.
- `direction`: `out` for `led` / `relay` / `output`; `in` for `button` / `input`.
- `active_high`: logical `true` maps to physical high when true, and to physical low when false.
- `max_on_ms`: optional output safety limit used by pulse and blink.
- `requires_confirmation`: optional output confirmation override. Relays default to true when omitted.
- `pull`: optional input pull mode, one of `up`, `down`, or `none`.

Example:

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

### `rpi.device.list`

- Risk: `read`
- Confirmation: no
- Input: empty object
- Output: configured device records with `device_id`, type, name, BCM pin, direction, `active_high`, and non-secret safety metadata.
- Policy: never returns tokens or endpoint secrets.

### `rpi.device.status`

- Risk: `read`
- Confirmation: no
- Input: `{ "device_id": string }`
- Output: device metadata, logical `value`, and raw GPIO `raw_value`.
- Policy: rejects unknown devices and rejects any config drift that places the device pin outside `security.gpio_allowed_pins`.

### `rpi.device.set`

- Risk: `local_write`
- Confirmation: yes when any configured output device requires confirmation; otherwise no.
- Input: `{ "device_id": string, "value": boolean|0|1|"on"|"off" }`
- Output: device metadata, logical value, raw GPIO value, and backend name.
- Policy: only `direction=out` devices can be set. Input devices fail with `device_permission_denied`.

### `rpi.device.pulse`

- Risk: `local_write`
- Confirmation: yes when any configured output device requires confirmation; otherwise no.
- Input: `{ "device_id": string, "duration_ms": integer }`
- Output: device metadata, duration, backend, and `reset_performed=true`.
- Policy: only output devices are allowed. `duration_ms` must be positive and must not exceed the device `max_on_ms`, or `5000` ms when no per-device limit is configured.

### `rpi.device.blink`

- Risk: `local_write`
- Confirmation: yes when any configured output device requires confirmation; otherwise no.
- Input: `{ "device_id": string, "count": integer, "interval_ms": integer }`
- Output: device metadata, count, interval, maximum total duration, backend, and final logical value false.
- Policy: only output devices are allowed. Count is capped at 20, interval is capped at 10000 ms and by output `max_on_ms`, and total duration is capped at 60000 ms.

### `rpi.button.read`

- Risk: `read`
- Confirmation: no
- Input: `{ "device_id": string }`
- Output: same shape as `rpi.device.status`.
- Policy: only configured `type=button`, `direction=in` devices are accepted.

## Disabled By Default

### `rpi.shell.safe_exec`

- Risk: `destructive`
- Confirmation: yes
- Advertised only when `security.safe_shell_enabled=true` and `security.safe_shell_allowlist` contains at least one valid template.
- Input: `{ "command": string, "timeout_seconds"?: integer }`
- Output: command name, return code, stdout, stderr, truncation flag, and sandbox path.
- Policy: no arbitrary shell strings, no user-controlled argv, no `shell=True`, output size-limited and redacted, execution cwd forced to `security.sandbox_dir`.

Allowlist example:

```json
{
  "security": {
    "safe_shell_enabled": true,
    "safe_shell_allowlist": [
      {
        "name": "uname",
        "argv": ["uname", "-a"],
        "timeout_seconds": 5
      }
    ]
  }
}
```

## Future Capabilities

These are intentionally not implemented in the MVP:

- camera capture
- microphone/audio playback
- display or LED matrix rendering
- sensor streaming
- Bluetooth or serial device control
- provider-owned human-visible delivery surfaces

Add future capabilities only through EndpointCapability snapshots and Core ToolRouter/ExecutionTarget routing.
