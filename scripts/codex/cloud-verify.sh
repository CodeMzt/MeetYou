#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV_DIR="${MEETYOU_CODEX_VENV_DIR:-${REPO_ROOT}/.venv-codex}"
VERIFY_PROFILE="${MEETYOU_CODEX_VERIFY_PROFILE:-cloud-dev}"
VERIFY_FRONTEND="${MEETYOU_CODEX_VERIFY_FRONTEND:-1}"

if [ ! -d "${VENV_DIR}" ]; then
  echo "Virtual environment not found: ${VENV_DIR}" >&2
  echo "Run bash scripts/codex/cloud-setup.sh first." >&2
  exit 1
fi

source "${VENV_DIR}/bin/activate"

python "${REPO_ROOT}/scripts/check_codex_cloud_readiness.py" --profile="${VERIFY_PROFILE}"
python -m unittest \
  tests.test_runtime_entrypoints \
  tests.test_config_manager \
  tests.test_mcp_command_resolution

if [ "${VERIFY_FRONTEND}" = "1" ]; then
  pushd "${REPO_ROOT}/meetyou-ui" >/dev/null
  npm run typecheck
  npm run test
  popd >/dev/null
fi

echo "[codex-cloud] verify complete"
