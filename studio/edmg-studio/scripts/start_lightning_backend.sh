#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STUDIO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${STUDIO_ROOT}/python_backend"
BACKEND_ENV_MODE="${EDMG_BACKEND_ENV_MODE:-auto}" # auto|active
BACKEND_ACCELERATOR_PROFILE="${EDMG_BACKEND_ACCELERATOR_PROFILE:-cpu}"

warn_if_unset() {
  local key="$1"
  local fallback="$2"
  if [[ -z "${!key:-}" ]]; then
    echo "[warn] ${key} is unset. Backend will fall back to ${fallback}."
  fi
}

# shellcheck source=uv_toolchain.sh
source "${SCRIPT_DIR}/uv_toolchain.sh"
UV_BIN="$(edmg_require_uv)"
UV_ACTIVE_ARGS=()

case "${BACKEND_ACCELERATOR_PROFILE}" in
  cpu|cuda) ;;
  *) echo "Unsupported EDMG_BACKEND_ACCELERATOR_PROFILE=${BACKEND_ACCELERATOR_PROFILE}. Use cpu or cuda on Linux." >&2; exit 1 ;;
esac

export EDMG_STUDIO_HOME="${EDMG_STUDIO_HOME:-${HOME}/edmg-studio-home}"
export EDMG_STUDIO_BACKEND_HOST="${EDMG_STUDIO_BACKEND_HOST:-0.0.0.0}"
export EDMG_STUDIO_BACKEND_PORT="${EDMG_STUDIO_BACKEND_PORT:-7863}"
export EDMG_FFMPEG_PATH="${EDMG_FFMPEG_PATH:-ffmpeg}"
export EDMG_BACKEND_ACCELERATOR_PROFILE="${BACKEND_ACCELERATOR_PROFILE}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${EDMG_STUDIO_HOME}/cache/uv}"

mkdir -p \
  "${EDMG_STUDIO_HOME}/data" \
  "${EDMG_STUDIO_HOME}/models" \
  "${EDMG_STUDIO_HOME}/cache" \
  "${EDMG_STUDIO_HOME}/logs" \
  "${EDMG_STUDIO_HOME}/external" \
  "${EDMG_STUDIO_HOME}/config"

if [[ "${EDMG_STUDIO_BACKEND_HOST}" != "127.0.0.1" && "${EDMG_STUDIO_BACKEND_HOST}" != "localhost" && "${EDMG_STUDIO_BACKEND_HOST}" != "::1" ]]; then
  export EDMG_BACKEND_AUTH_MODE="${EDMG_BACKEND_AUTH_MODE:-required}"
  AUTH_TOKEN_FILE="${EDMG_BACKEND_AUTH_TOKEN_FILE:-${EDMG_STUDIO_HOME}/config/backend-auth-token}"
  if [[ -z "${EDMG_BACKEND_AUTH_TOKEN:-}" ]]; then
    if [[ ! -s "${AUTH_TOKEN_FILE}" ]]; then
      umask 077
      head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n' >"${AUTH_TOKEN_FILE}"
    fi
    export EDMG_BACKEND_AUTH_TOKEN="$(<"${AUTH_TOKEN_FILE}")"
  fi
  export EDMG_BACKEND_CORS_ORIGIN_REGEX="${EDMG_BACKEND_CORS_ORIGIN_REGEX:-^https://[A-Za-z0-9.-]+\\.litng\\.ai$}"
  echo "[edmg] backend authentication: required"
  echo "[edmg] backend token file: ${AUTH_TOKEN_FILE}"
else
  export EDMG_BACKEND_AUTH_MODE="${EDMG_BACKEND_AUTH_MODE:-auto}"
fi

cd "${BACKEND_DIR}"

if [[ "${BACKEND_ENV_MODE}" == "active" ]]; then
  if [[ -z "${VIRTUAL_ENV:-}" && -z "${CONDA_PREFIX:-}" ]]; then
    echo "EDMG_BACKEND_ENV_MODE=active requires an active virtualenv or conda environment." >&2
    exit 1
  fi
  echo "[setup] synchronizing the active Python environment"
  UV_ACTIVE_ARGS=(--active)
elif [[ "${BACKEND_ENV_MODE}" == "auto" ]]; then
  echo "[setup] using the uv-managed project environment"
  "${UV_BIN}" python install 3.12
else
  echo "Unsupported EDMG_BACKEND_ENV_MODE=${BACKEND_ENV_MODE}. Use auto or active." >&2
  exit 1
fi

"${UV_BIN}" lock --check
if [[ "${EDMG_SKIP_BOOTSTRAP:-0}" != "1" ]]; then
  echo "[setup] synchronizing frozen ${BACKEND_ACCELERATOR_PROFILE} backend profile"
  "${UV_BIN}" sync --frozen "${UV_ACTIVE_ARGS[@]}" \
    --extra "${BACKEND_ACCELERATOR_PROFILE}" \
    --extra core --extra audio --extra asr --extra internal-video --extra aws
else
  echo "[setup] verifying the existing environment matches the frozen ${BACKEND_ACCELERATOR_PROFILE} profile"
  "${UV_BIN}" sync --frozen --check "${UV_ACTIVE_ARGS[@]}" \
    --extra "${BACKEND_ACCELERATOR_PROFILE}" \
    --extra core --extra audio --extra asr --extra internal-video --extra aws
fi

"${UV_BIN}" run --project "${BACKEND_DIR}" --frozen --no-sync "${UV_ACTIVE_ARGS[@]}" python -c \
  'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else f"EDMG Studio requires Python 3.12, got {sys.version.split()[0]}")'

echo "[edmg] studio root: ${STUDIO_ROOT}"
echo "[edmg] backend dir: ${BACKEND_DIR}"
echo "[edmg] studio home: ${EDMG_STUDIO_HOME}"
echo "[edmg] backend url: http://${EDMG_STUDIO_BACKEND_HOST}:${EDMG_STUDIO_BACKEND_PORT}"
echo "[edmg] python env mode: ${BACKEND_ENV_MODE}"
echo "[edmg] uv: $("${UV_BIN}" --version)"
echo "[edmg] accelerator profile: ${BACKEND_ACCELERATOR_PROFILE}"
echo "[edmg] backend auth mode: ${EDMG_BACKEND_AUTH_MODE}"
echo "[edmg] ai provider: ${EDMG_AI_PROVIDER:-nemotron_cloud}"
echo "[edmg] comfyui url: ${EDMG_COMFYUI_URL:-http://127.0.0.1:8188}"

if [[ "${EDMG_AI_PROVIDER:-nemotron_cloud}" == "openai_compat" || "${EDMG_AI_PROVIDER:-nemotron_cloud}" == "nemotron_cloud" ]]; then
  warn_if_unset "EDMG_AI_OPENAI_COMPAT_BASE_URL" "https://integrate.api.nvidia.com/v1"
  warn_if_unset "EDMG_AI_OPENAI_COMPAT_MODEL" "nvidia/llama-3.1-nemotron-ultra-253b-v1"
elif [[ "${EDMG_AI_PROVIDER:-}" == "ollama" ]]; then
  warn_if_unset "EDMG_AI_OLLAMA_URL" "http://127.0.0.1:11434"
  warn_if_unset "EDMG_AI_OLLAMA_MODEL" "nemotron-3-ultra:cloud"
else
  warn_if_unset "EDMG_AI_OLLAMA_URL" "http://127.0.0.1:11434"
  warn_if_unset "EDMG_AI_OLLAMA_MODEL" "qwen3:8b"
fi

exec "${UV_BIN}" run --project "${BACKEND_DIR}" --frozen --no-sync "${UV_ACTIVE_ARGS[@]}" python -m edmg_studio_backend serve \
  --host "${EDMG_STUDIO_BACKEND_HOST}" \
  --port "${EDMG_STUDIO_BACKEND_PORT}"
