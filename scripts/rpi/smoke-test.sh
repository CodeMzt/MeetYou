#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DEFAULT_CONFIG_PATH="/etc/meetyou/rpi-endpoint.json"
if [[ ! -f "${DEFAULT_CONFIG_PATH}" ]]; then
  DEFAULT_CONFIG_PATH="${REPO_DIR}/user/rpi_endpoint.example.json"
fi
CONFIG_PATH="${1:-${CONFIG_PATH:-${DEFAULT_CONFIG_PATH}}}"
ENV_FILE="${ENV_FILE:-/etc/meetyou/rpi-endpoint.env}"

cd "${REPO_DIR}"
export PYTHONPATH="${REPO_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
HEALTH_ARGS=(--config "${CONFIG_PATH}")
if [[ -f "${ENV_FILE}" ]]; then
  HEALTH_ARGS+=(--env-file "${ENV_FILE}")
fi

"${PYTHON_BIN}" -m endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.health "${HEALTH_ARGS[@]}"

"${PYTHON_BIN}" -m endpoint_providers.raspberry_pi.meetyou_rpi_endpoint.main \
  --config "${CONFIG_PATH}" \
  --simulate \
  --fake-gpio
