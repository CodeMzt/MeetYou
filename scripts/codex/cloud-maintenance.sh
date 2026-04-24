#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MEETYOU_CODEX_UPGRADE_BOOTSTRAP="${MEETYOU_CODEX_UPGRADE_BOOTSTRAP:-0}"

bash "${SCRIPT_DIR}/cloud-setup.sh"
