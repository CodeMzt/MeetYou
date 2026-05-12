#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SERVICE_NAME="${SERVICE_NAME:-meetyou-research-adapter}"
UNIT_TEMPLATE="deploy/systemd/meetyou-research-adapter.service.template"
ENV_TEMPLATE="deploy/systemd/research-adapter.env.example"

export SERVICE_NAME UNIT_TEMPLATE ENV_TEMPLATE

"${SCRIPT_DIR}/install-systemd-unit.sh"
