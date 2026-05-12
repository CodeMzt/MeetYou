#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CONFIG_PATH="${1:-${REPO_DIR}/user/rpi_endpoint.example.json}"

cd "${REPO_DIR}"
"${PYTHON_BIN}" -m endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.main \
  --config "${CONFIG_PATH}" \
  --simulate \
  --fake-gpio

