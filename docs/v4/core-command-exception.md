# Core Command Execution Exception

`exec_core_cmd` is an explicit exception to the V4/V5 rule that shell execution normally belongs to an Endpoint Provider.

## Boundary

- `exec_core_cmd` runs only on the Core Service host through `core.local`.
- Its working directory is fixed to the Core process `Path.cwd()`.
- It does not add arbitrary Core file access, Workspace I/O, or local MCP lifecycle.
- `exec_sys_cmd` keeps its existing Desktop/Endpoint meaning and continues to require Endpoint shell capability routing.

## Configuration

Core command execution is controlled by:

- `core_shell_exec_enabled`, default `true`.
- `core_cmd_policy_path`, default `user/core_cmd_policy.json`.
- `core_command_timeout_seconds`, default `120`.
- `core_command_output_max_chars`, default `20000`.

Environment overrides:

- `MEETYOU_CORE_SHELL_EXEC_ENABLED`
- `MEETYOU_CORE_CMD_POLICY_PATH`
- `MEETYOU_CORE_COMMAND_TIMEOUT_SECONDS`
- `MEETYOU_CORE_COMMAND_OUTPUT_MAX_CHARS`

If the Core policy file is missing or invalid, Core uses the built-in whitelist. It must not fall back to `mode:none`.

## Default Policy

The built-in policy is whitelist-first. It allows low-risk host inspection commands such as `dir`, `echo`, `hostname`, `whoami`, `date`, `time`, `ver`, `where`, version probes, and read-only Git inspection (`git status`, `git log`, `git diff`, `git branch`).

Network read helpers are allowed only as stdout reads:

- `curl` / `curl.exe`
- `wget -qO-` / `wget.exe -qO-`

The shared hard guard always runs before whitelist matching. It rejects shell control and redirection operators, encoded PowerShell, destructive delete/shutdown/registry/permission/firewall patterns, destructive Git and container cleanup commands, and curl/wget options that write files, upload data, read local files, or switch to non-HTTP local/file protocols.

## Tool Exposure

- `exec_core_cmd` is registered as a Core-owned tool on `core.local`.
- It is marked `destructive`, not parallel-safe, and order-required.
- It belongs to the `automation` assistant mode tool bundle only.
- It is hidden when `core_shell_exec_enabled=false`; direct calls are rejected by policy as well.
