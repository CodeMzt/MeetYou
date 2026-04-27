from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def _run_text(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return (completed.stdout or completed.stderr).strip()


def _parse_semver(raw: str | None) -> tuple[int, ...] | None:
    if not raw:
        return None
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", raw)
    if not match:
        return None
    parts = [int(match.group(1)), int(match.group(2))]
    if match.group(3) is not None:
        parts.append(int(match.group(3)))
    return tuple(parts)


def _check_file(path: Path, label: str) -> CheckResult:
    if path.exists():
        return CheckResult(label, "ok", f"found: {path}")
    return CheckResult(label, "fail", f"missing: {path}")


def _check_command_version(
    label: str,
    command_name: str,
    version_args: list[str],
    minimum: tuple[int, ...] | None = None,
) -> CheckResult:
    binary = shutil.which(command_name)
    if not binary:
        return CheckResult(label, "fail", f"{command_name} is not installed")
    output = _run_text([binary, *version_args])
    version = _parse_semver(output)
    if minimum is not None and version is not None and version < minimum:
        return CheckResult(
            label,
            "fail",
            f"{command_name} version {output!r} is below required minimum {minimum}",
        )
    if minimum is not None and version is None:
        return CheckResult(
            label,
            "warn",
            f"{command_name} is installed at {binary}, but version could not be parsed from {output!r}",
        )
    return CheckResult(label, "ok", f"{command_name}: {output or binary}")


def _check_python() -> CheckResult:
    version = sys.version_info
    if version < (3, 10):
        return CheckResult(
            "python",
            "fail",
            f"Python {version.major}.{version.minor}.{version.micro} is below required minimum 3.10",
        )
    return CheckResult(
        "python",
        "ok",
        f"Python {version.major}.{version.minor}.{version.micro}",
    )


def _check_database_env() -> CheckResult:
    value = os.environ.get("MEETYOU_DATABASE_URL", "").strip()
    if not value:
        return CheckResult(
            "database_url",
            "fail",
            "MEETYOU_DATABASE_URL is missing; Core startup and DB-backed tests will not work in cloud mode",
        )
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        return CheckResult(
            "database_url",
            "fail",
            "MEETYOU_DATABASE_URL is set but does not look like a valid SQLAlchemy/psycopg URL",
        )
    detail = f"configured for host {parsed.hostname}"
    if parsed.hostname in {"127.0.0.1", "localhost"}:
        detail += "; cloud mode requires a PostgreSQL server inside the container or otherwise reachable from it"
    return CheckResult("database_url", "ok", detail)


def _check_env_presence(name: str, required: bool, reason: str) -> CheckResult:
    value = os.environ.get(name, "").strip()
    if value:
        return CheckResult(name, "ok", reason)
    status = "fail" if required else "warn"
    prefix = "missing" if required else "not set"
    return CheckResult(name, status, f"{prefix}: {reason}")


def _check_platform_constraints() -> Iterable[CheckResult]:
    system = platform.system()
    yield CheckResult("platform", "ok", f"running on {system}")
    if system != "Windows":
        yield CheckResult(
            "desktop_windows_capabilities",
            "warn",
            "desktop_client Windows-only capabilities (pywin32, uiautomation, screen capture, local desktop UX acceptance) are not available in a Linux cloud container",
        )
        yield CheckResult(
            "electron_windows_build",
            "warn",
            "Linux cloud tasks can typecheck/test the renderer, but they are not a substitute for Windows Electron packaging and UI acceptance",
        )


def _check_optional_binaries() -> Iterable[CheckResult]:
    for name, label, reason in (
        ("bash", "bash", "Codex cloud setup and maintenance scripts run in Bash"),
        ("git", "git", "cloud tasks check out the repository into a container"),
        ("npm", "npm", "frontend install/typecheck/test depend on npm"),
        ("psql", "psql", "useful for DB diagnostics; full backend verification still needs PostgreSQL service availability"),
        ("tesseract", "tesseract", "needed only if OCR/document parsing coverage is required"),
    ):
        binary = shutil.which(name)
        if binary:
            yield CheckResult(label, "ok", reason)
        else:
            yield CheckResult(label, "warn", f"not installed: {reason}")


def run_checks(profile: str) -> list[CheckResult]:
    checks: list[CheckResult] = []
    checks.append(_check_python())
    checks.append(_check_command_version("node", "node", ["--version"], minimum=(18, 0, 0)))
    checks.append(_check_command_version("npm_version", "npm", ["--version"]))
    checks.append(_check_file(REPO_ROOT / "requirements-core.txt", "requirements_core"))
    checks.append(_check_file(REPO_ROOT / "requirements-desktop-client.txt", "requirements_desktop"))
    checks.append(_check_file(REPO_ROOT / "meetyou-ui" / "package.json", "frontend_package_json"))
    checks.append(_check_file(REPO_ROOT / "scripts" / "manual-acceptance.cmd", "windows_manual_acceptance"))
    checks.extend(_check_platform_constraints())
    checks.extend(_check_optional_binaries())
    database_check = _check_database_env()
    if profile == "cloud-dev" and database_check.status == "fail":
        database_check = CheckResult(
            database_check.name,
            "warn",
            "MEETYOU_DATABASE_URL is missing; cloud code analysis is still possible, but Core startup and DB-backed tests will not work",
        )
    checks.append(database_check)
    checks.append(
        _check_env_presence(
            "MEETYOU_GATEWAY_ACCESS_TOKEN",
            required=False,
            reason="recommended when cloud verification needs protected HTTP/WebSocket surfaces",
        )
    )
    checks.append(
        _check_env_presence(
            "MEETYOU_API_KEY",
            required=False,
            reason="recommended if cloud tasks will run live Core message flows instead of pure unit tests",
        )
    )
    checks.append(
        _check_env_presence(
            "MEETYOU_CLIENT_ACCESS_TOKEN",
            required=False,
            reason="recommended only if cloud verification will exercise /endpoint/ws with a real endpoint token",
        )
    )
    if profile == "desktop-local-acceptance" and platform.system() != "Windows":
        checks.append(
            CheckResult(
                "desktop_local_acceptance",
                "fail",
                "desktop local acceptance requires a Windows desktop session; Codex cloud containers are not sufficient",
            )
        )
    return checks


def main() -> int:
    json_mode = "--json" in sys.argv[1:]
    profile = "cloud-dev"
    for arg in sys.argv[1:]:
        if arg.startswith("--profile="):
            profile = arg.split("=", 1)[1].strip() or profile

    if profile not in {"cloud-dev", "cloud-core-test", "desktop-local-acceptance"}:
        print(
            "Unsupported profile. Use one of: cloud-dev, cloud-core-test, desktop-local-acceptance",
            file=sys.stderr,
        )
        return 2

    results = run_checks(profile)
    if json_mode:
        print(json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2))
    else:
        print(f"profile={profile}")
        for item in results:
            print(f"[{item.status.upper():4}] {item.name}: {item.detail}")

    if any(item.status == "fail" for item in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
