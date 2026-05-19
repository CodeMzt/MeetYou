#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SERVICE_NAME="${SERVICE_NAME:-meetyou-clawbot-wechat-provider}"
UNIT_TEMPLATE="deploy/systemd/meetyou-clawbot-wechat-provider.service.template"
ENV_TEMPLATE="deploy/systemd/external-provider.env.example"

export SERVICE_NAME UNIT_TEMPLATE ENV_TEMPLATE

bash "${SCRIPT_DIR}/install-systemd-unit.sh"
