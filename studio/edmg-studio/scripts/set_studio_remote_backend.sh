#!/usr/bin/env bash
set -euo pipefail

# Linux/macOS helper for pointing Studio at a managed local backend or a remote URL.
# Wraps `pnpm backend:use`, which updates .env, launcher_env.json, runtime-defaults.json,
# and the Electron bootstrap config under ~/.config/EDMG Studio (Linux) or %APPDATA% (Windows).

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STUDIO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/set_studio_remote_backend.sh external https://7863-...cloudspaces.litng.ai
  bash scripts/set_studio_remote_backend.sh managed 7863

Examples:
  # Lightning / Vast / GCP public backend URL
  bash scripts/set_studio_remote_backend.sh external https://7863-example.cloudspaces.litng.ai

  # Local managed backend on the same machine
  bash scripts/set_studio_remote_backend.sh managed 7863
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

cd "${STUDIO_ROOT}"
corepack enable >/dev/null 2>&1 || true
exec pnpm backend:use "$@"
