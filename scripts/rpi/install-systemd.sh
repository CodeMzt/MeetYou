#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/meetyou/MeetYou}"
SERVICE_USER="${SERVICE_USER:-meetyou-rpi}"
CONFIG_DIR="${CONFIG_DIR:-/etc/meetyou}"
STATE_DIR="${STATE_DIR:-/var/lib/meetyou-rpi}"
VENV_DIR="${VENV_DIR:-${REPO_DIR}/.venv-rpi}"
SERVICE_FILE="/etc/systemd/system/meetyou-rpi-endpoint.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo scripts/rpi/install-systemd.sh" >&2
  exit 1
fi

if [[ ! -d "${REPO_DIR}" ]]; then
  echo "Repository directory not found: ${REPO_DIR}" >&2
  exit 1
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "${STATE_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

if ! getent group gpio >/dev/null 2>&1; then
  groupadd --system gpio
fi
usermod -aG gpio "${SERVICE_USER}"

mkdir -p "${CONFIG_DIR}" "${STATE_DIR}/sandbox"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${STATE_DIR}"

if [[ ! -f "${CONFIG_DIR}/rpi-endpoint.json" ]]; then
  cp "${REPO_DIR}/user/rpi_endpoint.example.json" "${CONFIG_DIR}/rpi-endpoint.json"
  chmod 0640 "${CONFIG_DIR}/rpi-endpoint.json"
  chown root:"${SERVICE_USER}" "${CONFIG_DIR}/rpi-endpoint.json"
  echo "Created ${CONFIG_DIR}/rpi-endpoint.json from example. Edit it before starting the service."
else
  echo "Keeping existing ${CONFIG_DIR}/rpi-endpoint.json"
fi

if [[ ! -f "${CONFIG_DIR}/rpi-endpoint.env" ]]; then
  umask 0077
  cat >"${CONFIG_DIR}/rpi-endpoint.env" <<'ENV'
# Set the real token before starting:
# MEETYOU_RPI_ENDPOINT_TOKEN=
# Raspberry Pi 5 GPIO should use lgpio instead of legacy RPi.GPIO/native backends:
MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio
ENV
  chown root:"${SERVICE_USER}" "${CONFIG_DIR}/rpi-endpoint.env"
  echo "Created ${CONFIG_DIR}/rpi-endpoint.env without secrets. Add MEETYOU_RPI_ENDPOINT_TOKEN manually."
else
  echo "Keeping existing ${CONFIG_DIR}/rpi-endpoint.env"
  if ! grep -Eq '^[[:space:]]*(export[[:space:]]+)?MEETYOU_RPI_GPIO_PIN_FACTORY=' "${CONFIG_DIR}/rpi-endpoint.env"; then
    {
      echo
      echo "# Raspberry Pi 5 GPIO should use lgpio instead of legacy RPi.GPIO/native backends:"
      echo "MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio"
    } >>"${CONFIG_DIR}/rpi-endpoint.env"
    echo "Added MEETYOU_RPI_GPIO_PIN_FACTORY=lgpio to existing ${CONFIG_DIR}/rpi-endpoint.env"
  fi
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv --system-site-packages "${VENV_DIR}"
fi
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -e "${REPO_DIR}/endpoint_providers/raspberry_pi[gpio]"

cp "${REPO_DIR}/deploy/systemd/meetyou-rpi-endpoint.service" "${SERVICE_FILE}"
systemctl daemon-reload
systemctl enable meetyou-rpi-endpoint.service

echo "Installed meetyou-rpi-endpoint.service"
echo "Next:"
echo "  1. Edit ${CONFIG_DIR}/rpi-endpoint.json"
echo "  2. Set MEETYOU_RPI_ENDPOINT_TOKEN in ${CONFIG_DIR}/rpi-endpoint.env"
echo "  3. sudo systemctl start meetyou-rpi-endpoint"
