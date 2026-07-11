#!/usr/bin/env bash
set -euo pipefail

LABEL="com.claude.trmnl.usage"
TARGET_PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [[ -f "${TARGET_PLIST}" ]]; then
    launchctl unload "${TARGET_PLIST}" 2>/dev/null || true
    rm -f "${TARGET_PLIST}"
    echo "removed: ${TARGET_PLIST}"
else
    echo "nothing to do: ${TARGET_PLIST} does not exist"
fi
