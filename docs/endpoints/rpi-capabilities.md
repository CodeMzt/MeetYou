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
- Output: hostname, platform, Python version, uptime when available, memory summary when available, disk summary, and CPU temperature when available.
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
