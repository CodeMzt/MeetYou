#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SERVICE_NAME="${SERVICE_NAME:-meetyou-edge-client}"
UNIT_TEMPLATE="deploy/systemd/meetyou-edge-client.service.template"
ENV_TEMPLATE="deploy/systemd/edge-client.env.example"

export SERVICE_NAME UNIT_TEMPLATE ENV_TEMPLATE

"${SCRIPT_DIR}/install-systemd-unit.sh"
