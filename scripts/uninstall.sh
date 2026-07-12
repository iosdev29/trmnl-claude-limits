#!/usr/bin/env bash
# Thin Unix wrapper — forwards to the cross-platform Python installer.
#
# Windows users: run  py scripts\install.py --uninstall  instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

exec "${PYTHON}" "${SCRIPT_DIR}/install.py" --uninstall "$@"
