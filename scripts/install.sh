#!/usr/bin/env bash
# Install the TRMNL Claude usage LaunchAgent.
#
# Usage:
#   ./scripts/install.sh <TRMNL_WEBHOOK_URL>
#
# Reads the template plist, substitutes paths and the webhook URL, writes it
# to ~/Library/LaunchAgents, loads it. Re-running re-installs cleanly.

set -euo pipefail

LABEL="com.claude.trmnl.usage"
PLIST_NAME="${LABEL}.plist"
AGENTS_DIR="${HOME}/Library/LaunchAgents"
TARGET_PLIST="${AGENTS_DIR}/${PLIST_NAME}"
LOG_PATH="${HOME}/Library/Logs/trmnl-claude-usage.log"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/${PLIST_NAME}.tmpl"
SCRIPT_PATH="${SCRIPT_DIR}/push_usage.py"

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <TRMNL_WEBHOOK_URL>" >&2
    exit 2
fi
WEBHOOK_URL="$1"

if [[ ! -f "${TEMPLATE}" ]]; then
    echo "error: template not found at ${TEMPLATE}" >&2
    exit 1
fi
if [[ ! -f "${SCRIPT_PATH}" ]]; then
    echo "error: push script not found at ${SCRIPT_PATH}" >&2
    exit 1
fi

mkdir -p "${AGENTS_DIR}"

# Unload existing instance if loaded (ignore errors)
launchctl unload "${TARGET_PLIST}" 2>/dev/null || true

# Substitute placeholders. Use sed -e for portability.
sed \
    -e "s|__SCRIPT_PATH__|${SCRIPT_PATH}|g" \
    -e "s|__WEBHOOK_URL__|${WEBHOOK_URL}|g" \
    -e "s|__HOME__|${HOME}|g" \
    -e "s|__USER__|${USER}|g" \
    -e "s|__LOG_PATH__|${LOG_PATH}|g" \
    "${TEMPLATE}" > "${TARGET_PLIST}"

launchctl load "${TARGET_PLIST}"

echo "installed: ${TARGET_PLIST}"
echo "logs:      ${LOG_PATH}"
echo "interval:  every 600s (runs immediately, then on schedule)"
echo
echo "tail logs with:  tail -f ${LOG_PATH}"
echo "uninstall with:  ./scripts/uninstall.sh"
