#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SERVICE_NAME="${SERVICE_NAME:-meetyou-desktop-agent}"
UNIT_TEMPLATE="deploy/systemd/meetyou-desktop-agent.service.template"
ENV_TEMPLATE="deploy/systemd/desktop-agent.env.example"

export SERVICE_NAME UNIT_TEMPLATE ENV_TEMPLATE

"${SCRIPT_DIR}/install-systemd-unit.sh"
