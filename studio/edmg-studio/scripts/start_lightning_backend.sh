#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STUDIO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${STUDIO_ROOT}/python_backend"
BACKEND_SETUPTOOLS_CONSTRAINT="setuptools<82"
BACKEND_NUMPY_CONSTRAINT="${EDMG_BACKEND_NUMPY_CONSTRAINT:-numpy>=1.26,<2}"
BACKEND_ENV_MODE="${EDMG_BACKEND_ENV_MODE:-auto}" # auto|venv|active
BACKEND_TORCH_INDEX_URL="${EDMG_BACKEND_TORCH_INDEX_URL:-${PIP_TORCH_INDEX_URL:-}}"
BACKEND_BUNDLE_EXTRA="${EDMG_BACKEND_BUNDLE_EXTRA:-studio_bundle}"
if [[ "${EDMG_BACKEND_CUDA_BUNDLE:-0}" == "1" || "${EDMG_STUDIO_CUDA_BUNDLE:-0}" == "1" ]]; then
  BACKEND_BUNDLE_EXTRA="studio_bundle_cuda"
fi

pick_python_bin() {
  if [[ -n "${EDMG_PYTHON_BIN:-}" ]]; then
    printf '%s\n' "${EDMG_PYTHON_BIN}"
    return 0
  fi

  local candidate
  for candidate in python3.12 python3.11 python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  echo "No usable Python interpreter found. Set EDMG_PYTHON_BIN or install python3.11." >&2
  return 1
}

warn_if_unset() {
  local key="$1"
  local fallback="$2"
  if [[ -z "${!key:-}" ]]; then
    echo "[warn] ${key} is unset. Backend will fall back to ${fallback}."
  fi
}

PYTHON_BIN="$(pick_python_bin)"
PYTHON_CMD="python"

export EDMG_STUDIO_HOME="${EDMG_STUDIO_HOME:-${HOME}/edmg-studio-home}"
export EDMG_STUDIO_BACKEND_HOST="${EDMG_STUDIO_BACKEND_HOST:-0.0.0.0}"
export EDMG_STUDIO_BACKEND_PORT="${EDMG_STUDIO_BACKEND_PORT:-7863}"
export EDMG_FFMPEG_PATH="${EDMG_FFMPEG_PATH:-ffmpeg}"

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
      "${PYTHON_BIN}" -c "import secrets,sys; open(sys.argv[1], 'w', encoding='utf-8').write(secrets.token_urlsafe(48))" "${AUTH_TOKEN_FILE}"
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
  echo "[setup] using active python environment"
  PYTHON_CMD="${EDMG_ACTIVE_PYTHON_BIN:-python}"
elif [[ -d "${BACKEND_DIR}/venv" ]]; then
  # shellcheck source=/dev/null
  source "${BACKEND_DIR}/venv/bin/activate"
  PYTHON_CMD="python"
elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
  echo "[setup] using active virtualenv at ${VIRTUAL_ENV}"
  PYTHON_CMD="python"
elif [[ -n "${CONDA_PREFIX:-}" ]]; then
  echo "[setup] using active conda environment at ${CONDA_PREFIX}"
  PYTHON_CMD="python"
else
  if [[ "${BACKEND_ENV_MODE}" != "auto" && "${BACKEND_ENV_MODE}" != "venv" ]]; then
    echo "Unsupported EDMG_BACKEND_ENV_MODE=${BACKEND_ENV_MODE}. Use auto, venv, or active." >&2
    exit 1
  fi
  echo "[setup] creating virtualenv with ${PYTHON_BIN}"
  "${PYTHON_BIN}" -m venv venv
  # shellcheck source=/dev/null
  source "${BACKEND_DIR}/venv/bin/activate"
  PYTHON_CMD="python"
fi

if [[ "${EDMG_SKIP_BOOTSTRAP:-0}" != "1" ]]; then
  echo "[setup] upgrading pip tooling"
  "${PYTHON_CMD}" -m pip install -U pip "${BACKEND_SETUPTOOLS_CONSTRAINT}" wheel
  if [[ -n "${BACKEND_TORCH_INDEX_URL}" ]]; then
    echo "[setup] installing CUDA PyTorch stack from ${BACKEND_TORCH_INDEX_URL}"
    "${PYTHON_CMD}" -m pip install --upgrade torch torchvision torchaudio --index-url "${BACKEND_TORCH_INDEX_URL}"
  fi
  echo "[setup] installing backend bundle extra: ${BACKEND_BUNDLE_EXTRA}"
  "${PYTHON_CMD}" -m pip install -e ".[${BACKEND_BUNDLE_EXTRA}]" "${BACKEND_NUMPY_CONSTRAINT}"
fi

echo "[edmg] studio root: ${STUDIO_ROOT}"
echo "[edmg] backend dir: ${BACKEND_DIR}"
echo "[edmg] studio home: ${EDMG_STUDIO_HOME}"
echo "[edmg] backend url: http://${EDMG_STUDIO_BACKEND_HOST}:${EDMG_STUDIO_BACKEND_PORT}"
echo "[edmg] python env mode: ${BACKEND_ENV_MODE}"
echo "[edmg] python cmd: ${PYTHON_CMD}"
echo "[edmg] numpy constraint: ${BACKEND_NUMPY_CONSTRAINT}"
echo "[edmg] backend bundle extra: ${BACKEND_BUNDLE_EXTRA}"
echo "[edmg] backend auth mode: ${EDMG_BACKEND_AUTH_MODE}"
if [[ -n "${BACKEND_TORCH_INDEX_URL}" ]]; then
  echo "[edmg] torch index: ${BACKEND_TORCH_INDEX_URL}"
fi
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

exec "${PYTHON_CMD}" -m edmg_studio_backend serve \
  --host "${EDMG_STUDIO_BACKEND_HOST}" \
  --port "${EDMG_STUDIO_BACKEND_PORT}"
