#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/meetyou/MeetYou}"
PYTHON_BIN="${PYTHON_BIN:-${REPO_DIR}/.venv-rpi/bin/python}"
CONFIG_PATH="${1:-${CONFIG_PATH:-/etc/meetyou/rpi-endpoint.json}}"
ENV_FILE="${ENV_FILE:-/etc/meetyou/rpi-endpoint.env}"
SERVICE_NAME="${SERVICE_NAME:-meetyou-rpi-endpoint.service}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

echo "== Raspberry Pi device capability diagnostics =="
date -Is
echo

echo "== Repository =="
echo "REPO_DIR=${REPO_DIR}"
if [[ -d "${REPO_DIR}/.git" ]]; then
  git -C "${REPO_DIR}" branch --show-current || true
  git -C "${REPO_DIR}" rev-parse --short HEAD || true
  git -C "${REPO_DIR}" log -1 --oneline || true
else
  echo "No git checkout found at ${REPO_DIR}"
fi
echo

echo "== Service =="
systemctl show "${SERVICE_NAME}" -p ActiveState -p SubState -p ExecMainStartTimestamp -p FragmentPath --no-pager || true
systemctl cat "${SERVICE_NAME}" --no-pager | grep -E 'ExecStart=|WorkingDirectory=|EnvironmentFile=|User=|Group=|SupplementaryGroups=' || true
echo

echo "== Python registry =="
export PYTHONPATH="${REPO_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
export MEETYOU_RPI_DIAGNOSTIC_ENV_FILE="${ENV_FILE}"
"${PYTHON_BIN}" - "${CONFIG_PATH}" <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

config_path = sys.argv[1]
env_file = os.environ.get("MEETYOU_RPI_DIAGNOSTIC_ENV_FILE", "")

if env_file and Path(env_file).exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    except Exception:
        pass

try:
    import meetyou_rpi_endpoint
    from meetyou_rpi_endpoint.config import load_rpi_endpoint_config
    from meetyou_rpi_endpoint.registry import build_default_registry
except Exception as exc:
    print(f"import_failed: {type(exc).__name__}: {exc}")
    raise SystemExit(1)

print(f"package_path={Path(meetyou_rpi_endpoint.__file__).resolve()}")
config = load_rpi_endpoint_config(config_path)
registry = build_default_registry(config, force_fake_gpio=True)
names = registry.names()
print(f"endpoint_id={config.executor_endpoint_id}")
print(f"device_count={len(config.devices)}")
print(f"capability_count={len(names)}")
print("capabilities=" + json.dumps(names, ensure_ascii=False))
print(
    "device_capability_confirmation="
    + json.dumps(
        {
            item["tool_key"]: item["requires_confirmation"]
            for item in registry.tool_definitions()
            if item["tool_key"].startswith("rpi.device") or item["tool_key"].startswith("rpi.button")
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
print("devices=" + json.dumps([device.device_id for device in config.devices], ensure_ascii=False))
PY
echo

echo "== Recent capability logs =="
journalctl -u "${SERVICE_NAME}" --since "30 minutes ago" --no-pager | grep -E 'advertising|registered_capability_count|rpi.device|rpi.button' || true
