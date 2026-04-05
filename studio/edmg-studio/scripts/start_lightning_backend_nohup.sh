#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export EDMG_STUDIO_HOME="${EDMG_STUDIO_HOME:-${HOME}/edmg-studio-home}"

LOG_DIR="${EDMG_LIGHTNING_LOG_DIR:-${EDMG_STUDIO_HOME}/logs/lightning-backend}"
LOG_FILE="${EDMG_LIGHTNING_LOG_FILE:-${LOG_DIR}/backend.log}"
PID_FILE="${EDMG_LIGHTNING_PID_FILE:-${LOG_DIR}/backend.pid}"

mkdir -p "${LOG_DIR}"

if [[ -f "${PID_FILE}" ]]; then
  EXISTING_PID="$(cat "${PID_FILE}")"
  if [[ -n "${EXISTING_PID}" ]] && kill -0 "${EXISTING_PID}" >/dev/null 2>&1; then
    echo "[edmg] backend already running with pid ${EXISTING_PID}"
    echo "[edmg] log file: ${LOG_FILE}"
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

nohup bash "${SCRIPT_DIR}/start_lightning_backend.sh" >"${LOG_FILE}" 2>&1 &
PID=$!
echo "${PID}" >"${PID_FILE}"

sleep 2

if ! kill -0 "${PID}" >/dev/null 2>&1; then
  echo "[edmg] backend failed to start"
  echo "[edmg] recent log output:"
  tail -n 40 "${LOG_FILE}" || true
  rm -f "${PID_FILE}"
  exit 1
fi

echo "[edmg] backend started"
echo "[edmg] pid: ${PID}"
echo "[edmg] log file: ${LOG_FILE}"
echo "[edmg] pid file: ${PID_FILE}"
echo "[edmg] tail logs with: tail -f ${LOG_FILE}"
