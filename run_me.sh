#!/usr/bin/env bash
set -euo pipefail

# Get the directory of the current script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Change to that directory
cd "$SCRIPT_DIR" || exit 1

# Run the target script
exec bash "$SCRIPT_DIR/studio/edmg-studio/run_me.sh" "$@"
