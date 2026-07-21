#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

supports_studio_python() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)' >/dev/null 2>&1
}

pick_python() {
  if [[ -n "${EDMG_STUDIO_PYTHON:-}" ]] && supports_studio_python "${EDMG_STUDIO_PYTHON}"; then
    printf '%s\n' "${EDMG_STUDIO_PYTHON}"
    return 0
  fi

  for candidate in python3.12 python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1 && supports_studio_python "${candidate}"; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  return 1
}

if ! PYTHON_BIN="$(pick_python)"; then
  echo "Could not find Python 3.10+ to bootstrap the pinned uv toolchain."
  echo "The source launcher uses uv 0.11.28 to acquire and run Python 3.12."
  echo "Set EDMG_STUDIO_PYTHON to a bootstrap interpreter and run again."
  exit 1
fi

exec "${PYTHON_BIN}" tools/run_uv_launcher.py
