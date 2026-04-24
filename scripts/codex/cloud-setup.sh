#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV_DIR="${MEETYOU_CODEX_VENV_DIR:-${REPO_ROOT}/.venv-codex}"
INSTALL_FRONTEND="${MEETYOU_CODEX_INSTALL_FRONTEND:-1}"
INSTALL_DESKTOP="${MEETYOU_CODEX_INSTALL_DESKTOP_AGENT:-1}"
INSTALL_EDGE="${MEETYOU_CODEX_INSTALL_EDGE_AGENT:-0}"
UPGRADE_BOOTSTRAP="${MEETYOU_CODEX_UPGRADE_BOOTSTRAP:-1}"

pick_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return
  fi
  echo "python3 or python is required" >&2
  exit 1
}

PYTHON_BIN="$(pick_python)"

echo "[codex-cloud] repo_root=${REPO_ROOT}"
echo "[codex-cloud] python=${PYTHON_BIN}"
echo "[codex-cloud] venv=${VENV_DIR}"

"${PYTHON_BIN}" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required for MeetYou cloud development")
PY

if [ ! -d "${VENV_DIR}" ]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"

if [ "${UPGRADE_BOOTSTRAP}" = "1" ]; then
  python -m pip install --upgrade pip setuptools wheel
fi

python -m pip install -r "${REPO_ROOT}/requirements-core.txt"

if [ "${INSTALL_DESKTOP}" = "1" ]; then
  python -m pip install -r "${REPO_ROOT}/requirements-desktop-agent.txt"
fi

if [ "${INSTALL_EDGE}" = "1" ]; then
  python -m pip install -r "${REPO_ROOT}/requirements-edge-agent.txt"
fi

if [ "${INSTALL_FRONTEND}" = "1" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required when MEETYOU_CODEX_INSTALL_FRONTEND=1" >&2
    exit 1
  fi
  pushd "${REPO_ROOT}/meetyou-ui" >/dev/null
  npm ci
  popd >/dev/null
fi

python "${REPO_ROOT}/scripts/check_codex_cloud_readiness.py" --profile=cloud-dev

echo "[codex-cloud] setup complete"
