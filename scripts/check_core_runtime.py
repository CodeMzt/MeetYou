from __future__ import annotations

import argparse
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _check_file(path: Path, issues: list[str]) -> None:
    if not path.exists():
        issues.append(f"missing file: {path.relative_to(REPO_ROOT)}")


def _check_dir(path: Path, issues: list[str]) -> None:
    if not path.exists():
        issues.append(f"missing directory: {path.relative_to(REPO_ROOT)}")


def _check_env_value(values: dict[str, str], key: str, issues: list[str], *, allow_empty: bool = False) -> None:
    value = values.get(key, os.environ.get(key, ""))
    if allow_empty:
        return
    if not str(value or "").strip() or "replace_with" in str(value):
        issues.append(f"missing or placeholder env: {key}")


def check_host(env_file: Path) -> list[str]:
    issues: list[str] = []
    for path in (
        REPO_ROOT / "user" / "config.json",
        REPO_ROOT / "user" / "tools.json",
        REPO_ROOT / "user" / "cmd_policy.json",
        REPO_ROOT / "user" / "source_catalog.json",
        REPO_ROOT / "user" / "memory_graph.json",
        env_file,
    ):
        _check_file(path, issues)
    return issues


def check_docker(runtime_root: Path) -> list[str]:
    issues: list[str] = []
    compose_env = REPO_ROOT / "deploy" / "docker" / "compose.env"
    core_env = runtime_root / "core.env"
    for path in (
        REPO_ROOT / "Dockerfile",
        REPO_ROOT / "deploy" / "docker" / "compose.core-postgres.yml",
        compose_env,
        core_env,
        runtime_root / "user" / "config.json",
        runtime_root / "user" / "tools.json",
        runtime_root / "user" / "cmd_policy.json",
        runtime_root / "user" / "source_catalog.json",
        runtime_root / "user" / "memory_graph.json",
    ):
        _check_file(path, issues)
    for path in (runtime_root / "logs",):
        _check_dir(path, issues)

    compose_values = _read_env(compose_env)
    core_values = _read_env(core_env)
    merged = {**compose_values, **core_values}
    for key in (
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "MEETYOU_DATABASE_URL",
        "MEETYOU_GATEWAY_ACCESS_TOKEN",
    ):
        _check_env_value(merged, key, issues)
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Check MeetYou Core runtime files.")
    parser.add_argument("--profile", choices=("host", "docker"), default="host")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--runtime-root", default="deploy/docker/runtime")
    args = parser.parse_args()

    if args.profile == "host":
        issues = check_host(REPO_ROOT / args.env_file)
    else:
        issues = check_docker(REPO_ROOT / args.runtime_root)

    if issues:
        print("runtime check failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("runtime check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
