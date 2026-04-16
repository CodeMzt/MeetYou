#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SERVICE_NAME="${SERVICE_NAME:?SERVICE_NAME is required}"
UNIT_TEMPLATE="${UNIT_TEMPLATE:?UNIT_TEMPLATE is required}"
ENV_TEMPLATE="${ENV_TEMPLATE:?ENV_TEMPLATE is required}"

MEETYOU_USER="${MEETYOU_USER:-meetyou}"
MEETYOU_GROUP="${MEETYOU_GROUP:-${MEETYOU_USER}}"
WORKDIR="${WORKDIR:-/opt/meetyou/${SERVICE_NAME}}"
VENV_DIR="${VENV_DIR:-${WORKDIR}/.venv}"
PYTHON_BIN="${PYTHON_BIN:-${VENV_DIR}/bin/python}"
ENV_DIR="${ENV_DIR:-/etc/meetyou}"
ENV_FILE="${ENV_FILE:-${ENV_DIR}/${SERVICE_NAME}.env}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

UNIT_SOURCE="${REPO_ROOT}/${UNIT_TEMPLATE}"
ENV_SOURCE="${REPO_ROOT}/${ENV_TEMPLATE}"
UNIT_TARGET="${SYSTEMD_DIR}/${SERVICE_NAME}.service"

if [[ ! -f "${UNIT_SOURCE}" ]]; then
  echo "Unit template not found: ${UNIT_SOURCE}" >&2
  exit 1
fi

if [[ ! -f "${ENV_SOURCE}" ]]; then
  echo "Env template not found: ${ENV_SOURCE}" >&2
  exit 1
fi

install -d "${SYSTEMD_DIR}" "${ENV_DIR}"

TMP_UNIT="$(mktemp)"
trap 'rm -f "${TMP_UNIT}"' EXIT

sed \
  -e "s|{{MEETYOU_USER}}|${MEETYOU_USER}|g" \
  -e "s|{{MEETYOU_GROUP}}|${MEETYOU_GROUP}|g" \
  -e "s|{{WORKDIR}}|${WORKDIR}|g" \
  -e "s|{{PYTHON_BIN}}|${PYTHON_BIN}|g" \
  -e "s|{{ENV_FILE}}|${ENV_FILE}|g" \
  "${UNIT_SOURCE}" > "${TMP_UNIT}"

install -m 0644 "${TMP_UNIT}" "${UNIT_TARGET}"

if [[ ! -f "${ENV_FILE}" ]]; then
  install -m 0640 "${ENV_SOURCE}" "${ENV_FILE}"
  echo "Created env file template: ${ENV_FILE}"
else
  echo "Keeping existing env file: ${ENV_FILE}"
fi

systemctl daemon-reload

cat <<EOF
Installed unit: ${UNIT_TARGET}
Environment file: ${ENV_FILE}

Next steps:
1. Edit ${ENV_FILE}
2. Ensure ${PYTHON_BIN} exists and ${WORKDIR} is correct
3. sudo systemctl enable --now ${SERVICE_NAME}.service
4. sudo systemctl status ${SERVICE_NAME}.service
5. sudo journalctl -u ${SERVICE_NAME}.service -f
EOF
