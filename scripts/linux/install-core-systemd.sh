#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SERVICE_NAME="${SERVICE_NAME:-meetyou-core}"
UNIT_TEMPLATE="deploy/systemd/meetyou-core.service.template"
ENV_TEMPLATE="deploy/systemd/core.env.example"

export SERVICE_NAME UNIT_TEMPLATE ENV_TEMPLATE

"${SCRIPT_DIR}/install-systemd-unit.sh"
