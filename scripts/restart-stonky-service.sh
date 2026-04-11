#!/usr/bin/env bash
# Restarts the stonky-backend Windows service from Git Bash.
# Delegates to the PowerShell script so all logic lives in one place.
#
# Usage:  ./scripts/restart-stonky-service.sh
#
# The Release Manager (TC-002b) can call this from Git Bash or directly
# call the PowerShell script from a PowerShell context.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Convert Git Bash path to Windows path for PowerShell
PS_SCRIPT="$(cygpath -w "$SCRIPT_DIR/restart-stonky-service.ps1")"

echo "[*] Delegating restart to PowerShell: $PS_SCRIPT"
powershell.exe -ExecutionPolicy Bypass -File "$PS_SCRIPT"
