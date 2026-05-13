# Raspberry Pi Endpoint Security

The Raspberry Pi endpoint is an execution provider. It must not become Core, must not own conversation state, and must not generate final assistant replies. Its security model is local execution containment plus Core-governed routing.

## Runtime Boundary

- Core owns Thread, Message, Run, Scheduler, `system.heartbeat`, Delivery, ToolRouter, Operation records, and persistence.
- The Pi owns only its local process, local capability registry, local hardware access, and in-memory first-MVP operation idempotency.
- All executable calls arrive through `tool.call.request` after Core resolves ToolRouter and ExecutionTarget.
- The Pi sends `tool.call.accepted`, `tool.call.progress`, `tool.call.result`, or `tool.call.error`; it does not write Core database rows directly.
- `endpoint.heartbeat` is connection keepalive only and must not trigger Scheduler-owned `system.heartbeat`.

## Token Handling

- Real tokens must live in environment variables, not committed JSON files.
- `user/rpi_endpoint.example.json` names `MEETYOU_RPI_ENDPOINT_TOKEN` but does not contain a token.
- Loader precedence is environment first: `MEETYOU_RPI_ENDPOINT_TOKEN`, configured `endpoint_token_env`, `MEETYOU_CLIENT_ACCESS_TOKEN`, then `MEETYOU_GATEWAY_ACCESS_TOKEN`.
- Missing-token errors report only the expected environment variable names, never token values.
- Logs use a redacting filter for token, secret, password, cookie, authorization, and API key fields.

## Safe Shell Policy

`rpi.shell.safe_exec` is deny-by-default:

- Not advertised unless `safe_shell_enabled=true` and a non-empty allowlist exists.
- Accepts only a configured command name.
- Rejects user-supplied `argv`, `cmd`, and `shell` fields.
- Executes with `asyncio.create_subprocess_exec`, never `shell=True`.
- Runs inside `security.sandbox_dir`.
- Truncates stdout/stderr to 8192 bytes each.
- Redacts sensitive output patterns before returning results.

This capability is still high risk. Keep it disabled until a specific Pi deployment has a reviewed allowlist.

## GPIO Policy

- GPIO read/write validate the pin against `security.gpio_allowed_pins` before touching the backend.
- GPIO write requires confirmation in the advertised EndpointCapability.
- On non-Pi development machines, use fake GPIO. Do not treat fake GPIO success as hardware validation.
- Raspberry Pi 5 must use the `lgpio` backend. Set `MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio`; otherwise legacy backends can fail with `Cannot determine SOC peripheral base address`.
- GPIO may require Linux group/device permissions depending on Raspberry Pi OS setup; avoid running the endpoint as root unless a deployment explicitly justifies it.

## Filesystem And Process Policy

- No inbound server port is opened on the Pi.
- The provider actively connects to Core over WebSocket.
- systemd runs as dedicated user `meetyou-rpi`.
- The service template enables `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`, `ProtectHome=true`, and limits write access to `/var/lib/meetyou-rpi`.
- The installer does not overwrite existing config or environment files and never writes secrets.

## Forbidden Regressions

- Do not add `/client/ws`.
- Do not reintroduce `source_client_id` or `target_client_id` as primary routing concepts.
- Do not route through `ClientToolDispatchService`.
- Do not treat `short_reply` as a final reply path.
- Do not move local shell, GPIO, file, or hardware execution into Core.
