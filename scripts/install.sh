#!/usr/bin/env bash
# Thin Unix wrapper — forwards to the cross-platform Python installer.
#
# Windows users: run  py scripts\install.py  instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

if ! command -v "${PYTHON}" >/dev/null 2>&1; then
    echo "error: python3 not found. Install Python 3.8+ and retry." >&2
    exit 1
fi

exec "${PYTHON}" "${SCRIPT_DIR}/install.py" "$@"
