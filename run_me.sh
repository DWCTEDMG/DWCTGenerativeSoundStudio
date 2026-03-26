#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

supports_studio_python() {
  "$1" -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 14) else 1)' >/dev/null 2>&1
}

pick_python() {
  if [[ -n "${EDMG_STUDIO_PYTHON:-}" ]] && supports_studio_python "${EDMG_STUDIO_PYTHON}"; then
    printf '%s\n' "${EDMG_STUDIO_PYTHON}"
    return 0
  fi

  for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1 && supports_studio_python "${candidate}"; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  return 1
}

if ! PYTHON_BIN="$(pick_python)"; then
  echo "Could not find a supported Python interpreter."
  echo "EDMG Studio requires Python 3.10 - 3.13 for the dev launcher."
  echo "If you already have one installed, set EDMG_STUDIO_PYTHON to that interpreter and run again."
  exit 1
fi

exec "${PYTHON_BIN}" tools/launcher_gui.py
