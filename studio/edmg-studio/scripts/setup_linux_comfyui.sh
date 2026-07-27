#!/usr/bin/env bash
set -euo pipefail

# Linux/Lightning ComfyUI sidecar setup for EDMG Studio.
#
# This script intentionally uses the active Python environment by default,
# because managed cloud workspaces such as Lightning may not allow creating a
# project-local venv. Use COMFY_PYTHON_BIN to point at another interpreter.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COMFY_REPO_URL="${COMFY_REPO_URL:-https://github.com/Comfy-Org/ComfyUI.git}"
EDMG_STUDIO_HOME="${EDMG_STUDIO_HOME:-${HOME}/edmg-studio-home}"
EDMG_STUDIO_EXTERNAL_DIR="${EDMG_STUDIO_EXTERNAL_DIR:-${EDMG_STUDIO_HOME}/external}"
EDMG_STUDIO_LOGS_DIR="${EDMG_STUDIO_LOGS_DIR:-${EDMG_STUDIO_HOME}/logs}"
COMFY_ROOT="${COMFY_ROOT:-${EDMG_STUDIO_EXTERNAL_DIR}/ComfyUI}"
COMFY_HOST="${COMFY_HOST:-127.0.0.1}"
COMFY_PORT="${COMFY_PORT:-8188}"
COMFY_PYTHON_BIN="${COMFY_PYTHON_BIN:-python}"
COMFY_LOG_DIR="${COMFY_LOG_DIR:-${EDMG_STUDIO_LOGS_DIR}}"
COMFY_LOG_FILE="${COMFY_LOG_FILE:-${COMFY_LOG_DIR}/comfyui.log}"
COMFY_INSTALL_MODELS="${COMFY_INSTALL_MODELS:-0}"
COMFY_START="${COMFY_START:-1}"
COMFY_INSTALL_NODES="${COMFY_INSTALL_NODES:-1}"
HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-1}"
export HF_HUB_ENABLE_HF_TRANSFER

log() {
  echo "[comfyui-linux] $*"
}

warn() {
  echo "[comfyui-linux][warn] $*" >&2
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[comfyui-linux][error] Missing required command: $1" >&2
    exit 1
  fi
}

clone_or_pull() {
  local repo_url="$1"
  local dest="$2"
  if [[ -d "${dest}/.git" ]]; then
    log "Updating ${dest}"
    git -C "${dest}" pull --ff-only || warn "Could not fast-forward ${dest}; leaving existing checkout."
  else
    log "Cloning ${repo_url} -> ${dest}"
    git clone "${repo_url}" "${dest}"
  fi
}

install_requirements_if_present() {
  local dir="$1"
  if [[ -f "${dir}/requirements.txt" ]]; then
    log "Installing Python requirements in ${dir}"
    "${UV_BIN}" pip install --python "${COMFY_PYTHON_BIN}" -r "${dir}/requirements.txt"
  fi
}

download_hf_file() {
  local repo_id="$1"
  local filename="$2"
  local dest_dir="$3"
  mkdir -p "${dest_dir}"
  log "Downloading ${repo_id}/${filename}"
  if ! huggingface-cli download "${repo_id}" "${filename}" --local-dir "${dest_dir}"; then
    warn "Download failed for ${repo_id}/${filename}. If this is gated, accept the model license and set HF_TOKEN."
  fi
}

require_cmd git
# shellcheck source=uv_toolchain.sh
source "${SCRIPT_DIR}/uv_toolchain.sh"
UV_BIN="$(edmg_require_uv)"
require_cmd "${COMFY_PYTHON_BIN}"

mkdir -p "$(dirname "${COMFY_ROOT}")" "${COMFY_LOG_DIR}"

clone_or_pull "${COMFY_REPO_URL}" "${COMFY_ROOT}"

cd "${COMFY_ROOT}"

install_requirements_if_present "${COMFY_ROOT}"

if [[ "${COMFY_INSTALL_NODES}" == "1" ]]; then
  mkdir -p "${COMFY_ROOT}/custom_nodes"
  cd "${COMFY_ROOT}/custom_nodes"

  clone_or_pull "https://github.com/Comfy-Org/ComfyUI-Manager" "comfyui-manager"
  install_requirements_if_present "${COMFY_ROOT}/custom_nodes/comfyui-manager"

  clone_or_pull "https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git" "ComfyUI-AnimateDiff-Evolved"
  install_requirements_if_present "${COMFY_ROOT}/custom_nodes/ComfyUI-AnimateDiff-Evolved"

  clone_or_pull "https://github.com/thecooltechguy/ComfyUI-Stable-Video-Diffusion.git" "ComfyUI-Stable-Video-Diffusion"
  if [[ -f "${COMFY_ROOT}/custom_nodes/ComfyUI-Stable-Video-Diffusion/install.py" ]]; then
    log "Running Stable Video Diffusion node installer"
    (cd "${COMFY_ROOT}/custom_nodes/ComfyUI-Stable-Video-Diffusion" && "${COMFY_PYTHON_BIN}" install.py)
  else
    install_requirements_if_present "${COMFY_ROOT}/custom_nodes/ComfyUI-Stable-Video-Diffusion"
  fi
fi

mkdir -p \
  "${COMFY_ROOT}/models/checkpoints" \
  "${COMFY_ROOT}/models/svd" \
  "${COMFY_ROOT}/models/animatediff_models"

if [[ "${COMFY_INSTALL_MODELS}" == "1" ]]; then
  log "Installing Hugging Face download helpers"
  "${UV_BIN}" pip install --python "${COMFY_PYTHON_BIN}" -U \
    "huggingface_hub>=0.34.0,<1.0" \
    "hf_transfer==0.1.9" \
    "hf_xet==1.5.1"

  download_hf_file "stabilityai/stable-diffusion-xl-base-1.0" "sd_xl_base_1.0.safetensors" "${COMFY_ROOT}/models/checkpoints"
  download_hf_file "stabilityai/stable-video-diffusion-img2vid-xt-1-1" "svd_xt_1_1.safetensors" "${COMFY_ROOT}/models/svd"
  if [[ -f "${COMFY_ROOT}/models/svd/svd_xt_1_1.safetensors" && ! -e "${COMFY_ROOT}/models/svd/svd_xt.safetensors" ]]; then
    ln -s "svd_xt_1_1.safetensors" "${COMFY_ROOT}/models/svd/svd_xt.safetensors"
  fi
  download_hf_file "guoyww/animatediff" "mm_sd_v15_v2.ckpt" "${COMFY_ROOT}/models/animatediff_models"
fi

log "Validating PyTorch"
"${COMFY_PYTHON_BIN}" - <<'PY'
try:
    import torch
    print("torch", torch.__version__)
    print("cuda_build", torch.version.cuda)
    print("cuda_available", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("device_0", torch.cuda.get_device_name(0))
except Exception as exc:
    print("torch_check_error", repr(exc))
PY

if [[ "${COMFY_START}" == "1" ]]; then
  if curl -fsS "http://${COMFY_HOST}:${COMFY_PORT}/object_info" >/dev/null 2>&1; then
    log "ComfyUI is already reachable at http://${COMFY_HOST}:${COMFY_PORT}"
  else
    log "Starting ComfyUI at http://${COMFY_HOST}:${COMFY_PORT}"
    cd "${COMFY_ROOT}"
    nohup "${COMFY_PYTHON_BIN}" main.py --listen "${COMFY_HOST}" --port "${COMFY_PORT}" >"${COMFY_LOG_FILE}" 2>&1 &
    for _ in $(seq 1 90); do
      if curl -fsS "http://${COMFY_HOST}:${COMFY_PORT}/object_info" >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
  fi
fi

if curl -fsS "http://${COMFY_HOST}:${COMFY_PORT}/object_info" >/tmp/edmg-comfy-object-info.json 2>/dev/null; then
  log "ComfyUI capability summary"
  "${COMFY_PYTHON_BIN}" - <<'PY'
import json
from pathlib import Path

obj = json.loads(Path("/tmp/edmg-comfy-object-info.json").read_text(encoding="utf-8"))
for node in ("ADE_AnimateDiffLoaderGen1", "ADE_StandardStaticContextOptions", "SVDSimpleImg2Vid"):
    print(f"{node}={node in obj}")
PY
else
  warn "ComfyUI is not reachable yet. Check ${COMFY_LOG_FILE}."
fi

log "Done"
log "ComfyUI root: ${COMFY_ROOT}"
log "ComfyUI URL for EDMG backend: http://${COMFY_HOST}:${COMFY_PORT}"
log "Log file: ${COMFY_LOG_FILE}"
