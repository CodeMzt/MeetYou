#!/usr/bin/env bash
set -euo pipefail

SERVICE_FILE="/etc/systemd/system/meetyou-rpi-endpoint.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo scripts/rpi/uninstall-systemd.sh" >&2
  exit 1
fi

systemctl stop meetyou-rpi-endpoint.service >/dev/null 2>&1 || true
systemctl disable meetyou-rpi-endpoint.service >/dev/null 2>&1 || true

if [[ -f "${SERVICE_FILE}" ]]; then
  rm -f "${SERVICE_FILE}"
fi

systemctl daemon-reload

echo "Removed meetyou-rpi-endpoint.service"
echo "Configuration and state were left in /etc/meetyou and /var/lib/meetyou-rpi."

