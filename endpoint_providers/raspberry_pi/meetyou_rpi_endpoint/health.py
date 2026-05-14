from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .capabilities.base import CapabilityError
from .capabilities.gpio import (
    _configure_gpiozero_pin_factory,
    _looks_like_raspberry_pi,
    _select_gpio_pin_factory_name,
)
from .config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_ENDPOINT_TOKEN_ENV,
    RpiConfigError,
    RpiEndpointConfig,
    load_rpi_endpoint_config,
)


PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
_VALID_STATUSES = {PASS, WARN, FAIL}


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    name: str
    status: str
    message: str

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"invalid health status: {self.status}")


def load_env_file(env_file_path: str | Path | None, *, override: bool = False) -> HealthCheckResult | None:
    if not env_file_path:
        return None
    path = Path(env_file_path)
    if not path.exists():
        return HealthCheckResult("env_file", WARN, f"environment file not found: {path}")
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            if not override and key in os.environ:
                continue
            os.environ[key] = _unquote_env_value(value.strip())
    except OSError as exc:
        return HealthCheckResult("env_file", FAIL, f"failed to read environment file: {path}: {exc}")
    return HealthCheckResult("env_file", PASS, f"loaded environment file: {path}")


def run_health_checks(
    *,
    config_path: str | Path | None = None,
    env_file_path: str | Path | None = None,
    service_name: str = "meetyou-rpi-endpoint",
) -> list[HealthCheckResult]:
    results: list[HealthCheckResult] = []
    env_result = load_env_file(env_file_path)
    if env_result is not None:
        results.append(env_result)

    selected_config_path = Path(config_path or os.environ.get("MEETYOU_RPI_CONFIG") or DEFAULT_CONFIG_PATH)
    results.append(_check_config_file(selected_config_path))

    config: RpiEndpointConfig | None = None
    try:
        config = load_rpi_endpoint_config(str(selected_config_path))
    except RpiConfigError as exc:
        results.append(HealthCheckResult("config_load", FAIL, f"{exc.code}: {exc.message}"))
    except Exception as exc:
        results.append(HealthCheckResult("config_load", FAIL, f"unexpected config load failure: {type(exc).__name__}: {exc}"))

    if config is None:
        results.append(_check_systemd_service(service_name))
        return results

    results.append(_check_token_env(config))
    results.append(_check_sandbox_writable(config.security.sandbox_dir))
    results.append(_check_gpio_backend(config))
    results.append(_check_gpio_group())
    results.append(_check_gpiochip_permissions())
    results.append(_check_systemd_service(service_name))
    return results


def render_health_results(results: Iterable[HealthCheckResult]) -> str:
    return "\n".join(f"[{item.status}] {item.name}: {item.message}" for item in results)


def health_exit_code(results: Iterable[HealthCheckResult]) -> int:
    return 1 if any(item.status == FAIL for item in results) else 0


def _check_config_file(path: Path) -> HealthCheckResult:
    if path.exists() and path.is_file():
        return HealthCheckResult("config_file", PASS, f"found config file: {path}")
    return HealthCheckResult("config_file", FAIL, f"config file is missing: {path}")


def _check_token_env(config: RpiEndpointConfig) -> HealthCheckResult:
    for env_name in _token_env_names(config.endpoint_token_env):
        if str(os.environ.get(env_name, "")).strip():
            return HealthCheckResult(
                "token_env",
                PASS,
                f"token environment variable is set: {env_name} (value redacted)",
            )
    expected = ", ".join(_token_env_names(config.endpoint_token_env))
    return HealthCheckResult("token_env", FAIL, f"no endpoint token environment variable is set; checked: {expected}")


def _check_sandbox_writable(sandbox_dir: str) -> HealthCheckResult:
    path = Path(sandbox_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".meetyou-health-", dir=path, delete=True) as handle:
            handle.write(b"ok")
            handle.flush()
    except OSError as exc:
        return HealthCheckResult("sandbox_dir", FAIL, f"sandbox_dir is not writable: {path}: {exc}")
    return HealthCheckResult("sandbox_dir", PASS, f"sandbox_dir is writable: {path}")


def _check_gpio_backend(config: RpiEndpointConfig) -> HealthCheckResult:
    if _env_truthy("MEETYOU_RPI_FAKE_GPIO"):
        return HealthCheckResult("gpio_backend", WARN, "fake GPIO is enabled; hardware GPIO is not validated")

    selected = _select_gpio_pin_factory_name()
    is_pi = _looks_like_raspberry_pi()
    if selected != "lgpio":
        status = FAIL if is_pi else WARN
        return HealthCheckResult(
            "gpio_backend",
            status,
            f"selected GPIO pin factory is {selected}; Raspberry Pi 5 production should use lgpio",
        )

    original_cwd = os.getcwd()
    try:
        from gpiozero import Device

        label = _configure_gpiozero_pin_factory(
            Device,
            "lgpio",
            working_dir=config.security.sandbox_dir,
        )
    except CapabilityError as exc:
        return HealthCheckResult("gpio_backend", FAIL, f"{exc.code}: {exc.message}")
    except Exception as exc:
        return HealthCheckResult("gpio_backend", FAIL, f"GPIO lgpio backend check failed: {type(exc).__name__}: {exc}")
    finally:
        try:
            os.chdir(original_cwd)
        except OSError:
            pass
    return HealthCheckResult("gpio_backend", PASS, f"GPIO backend available: gpiozero:{label}")


def _check_gpio_group(group_name: str = "gpio") -> HealthCheckResult:
    if platform.system().lower() != "linux":
        return HealthCheckResult("gpio_group", WARN, "gpio group check is only applicable on Linux")
    try:
        import grp
        import pwd

        group = grp.getgrnam(group_name)
        user = pwd.getpwuid(os.geteuid()).pw_name
        gids = set(os.getgroups())
        gids.add(os.getegid())
    except KeyError:
        return HealthCheckResult("gpio_group", FAIL, f"required group does not exist: {group_name}")
    except Exception as exc:
        return HealthCheckResult("gpio_group", WARN, f"could not inspect current user groups: {type(exc).__name__}: {exc}")

    if group.gr_gid in gids or user in group.gr_mem:
        return HealthCheckResult("gpio_group", PASS, f"current user {user} is in group {group_name}")
    return HealthCheckResult(
        "gpio_group",
        FAIL,
        f"current user {user} is not in group {group_name}; systemd should set SupplementaryGroups=gpio",
    )


def _check_gpiochip_permissions() -> HealthCheckResult:
    if platform.system().lower() != "linux":
        return HealthCheckResult("gpiochip_permissions", WARN, "/dev/gpiochip* check is only applicable on Linux")
    paths = sorted(Path("/dev").glob("gpiochip*"))
    if not paths:
        status = FAIL if _looks_like_raspberry_pi() else WARN
        return HealthCheckResult("gpiochip_permissions", status, "no /dev/gpiochip* devices found")

    accessible = [path for path in paths if os.access(path, os.R_OK | os.W_OK)]
    if accessible:
        names = ", ".join(path.name for path in accessible[:4])
        return HealthCheckResult("gpiochip_permissions", PASS, f"current user can read/write gpiochip devices: {names}")

    names = ", ".join(path.name for path in paths[:4])
    return HealthCheckResult(
        "gpiochip_permissions",
        FAIL,
        f"found {names} but current user lacks read/write permission; can not open gpiochip means a device permission/group problem",
    )


def _check_systemd_service(service_name: str) -> HealthCheckResult:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return HealthCheckResult("systemd_service", WARN, "systemctl not found; service state not checked")
    try:
        completed = subprocess.run(
            [systemctl, "is-active", service_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return HealthCheckResult("systemd_service", WARN, f"systemd service check failed: {type(exc).__name__}: {exc}")

    state = (completed.stdout or completed.stderr or "unknown").strip()
    if state == "active":
        return HealthCheckResult("systemd_service", PASS, f"{service_name}.service is active")
    if state == "failed":
        return HealthCheckResult("systemd_service", FAIL, f"{service_name}.service is failed")
    return HealthCheckResult("systemd_service", WARN, f"{service_name}.service is {state or 'unknown'}")


def _token_env_names(endpoint_token_env: str) -> list[str]:
    names = [
        DEFAULT_ENDPOINT_TOKEN_ENV,
        str(endpoint_token_env or "").strip(),
        "MEETYOU_CLIENT_ACCESS_TOKEN",
        "MEETYOU_GATEWAY_ACCESS_TOKEN",
    ]
    result: list[str] = []
    for name in names:
        if name and name not in result:
            result.append(name)
    return result


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MeetYou Raspberry Pi Endpoint health check")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to rpi endpoint JSON config")
    parser.add_argument("--env-file", default="", help="Optional systemd EnvironmentFile to load before checks")
    parser.add_argument("--service-name", default="meetyou-rpi-endpoint", help="systemd service name without .service")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    results = run_health_checks(
        config_path=args.config,
        env_file_path=args.env_file or None,
        service_name=args.service_name,
    )
    print(render_health_results(results))
    raise SystemExit(health_exit_code(results))


if __name__ == "__main__":
    main()
