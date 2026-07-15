#!/usr/bin/env bash
set -euo pipefail

# Linux/Lightning Hugging Face bucket model-cache setup for EDMG Studio.
#
# Auth uses the locally saved token from `hf auth login` (or HF_TOKEN for probes).
# Project defaults ship in launcher_env.defaults.json; this helper writes a
# sourceable env file for Lightning shells.

EDMG_STUDIO_HOME="${EDMG_STUDIO_HOME:-${HOME}/edmg-studio-home}"
HF_PYTHON_BIN="${HF_PYTHON_BIN:-python}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=uv_toolchain.sh
source "${SCRIPT_DIR}/uv_toolchain.sh"
UV_BIN="$(edmg_require_uv)"
EDMG_HF_BUCKET_ID="${EDMG_HF_BUCKET_ID:-gulle1155/DWCTedmgAIStudioModels}"
EDMG_HF_BUCKET_PREFIX="${EDMG_HF_BUCKET_PREFIX:-}"
EDMG_MODEL_STORAGE_MODE="${EDMG_MODEL_STORAGE_MODE:-cloud_only}" # local_cache|cloud_only
HF_INSTALL_HUB="${HF_INSTALL_HUB:-1}"
HF_ENV_FILE="${HF_ENV_FILE:-${EDMG_STUDIO_HOME}/hf-bucket.env}"

export EDMG_STUDIO_HOME
export EDMG_HF_BUCKET_MODEL_CACHE=1
export EDMG_HF_BUCKET_ID
export EDMG_HF_BUCKET_PREFIX
export EDMG_MODEL_STORAGE_MODE

log() {
  echo "[hf-bucket] $*"
}

fail() {
  echo "[hf-bucket][error] $*" >&2
  exit 1
}

if [[ -z "${EDMG_HF_BUCKET_ID}" ]]; then
  fail "Set EDMG_HF_BUCKET_ID to your Hugging Face dataset or bucket id."
fi

case "${EDMG_MODEL_STORAGE_MODE}" in
  local_cache|cloud_only) ;;
  s3_only|remote_only)
    EDMG_MODEL_STORAGE_MODE="cloud_only"
    export EDMG_MODEL_STORAGE_MODE
    ;;
  *)
    fail "Unsupported EDMG_MODEL_STORAGE_MODE=${EDMG_MODEL_STORAGE_MODE}. Use local_cache or cloud_only."
    ;;
esac

mkdir -p "${EDMG_STUDIO_HOME}"

if [[ "${HF_INSTALL_HUB}" == "1" ]]; then
  log "Ensuring huggingface_hub is installed"
  "${UV_BIN}" pip install --python "${HF_PYTHON_BIN}" -U "huggingface_hub>=0.34,<1.0"
fi

log "Validating Hugging Face auth"
"${HF_PYTHON_BIN}" - <<'PY'
from __future__ import annotations

import os

from huggingface_hub import HfApi

api = HfApi()
who = api.whoami()
print(f"hf_user={who.get('name') or who.get('fullname') or 'ok'}")
print(f"bucket_id={os.environ['EDMG_HF_BUCKET_ID']}")
print("auth_probe=ok")
PY

cat >"${HF_ENV_FILE}" <<EOF
export EDMG_HF_BUCKET_MODEL_CACHE=1
export EDMG_HF_BUCKET_ID=${EDMG_HF_BUCKET_ID}
export EDMG_HF_BUCKET_PREFIX=${EDMG_HF_BUCKET_PREFIX}
export EDMG_MODEL_STORAGE_MODE=${EDMG_MODEL_STORAGE_MODE}
EOF

chmod 600 "${HF_ENV_FILE}" || true

log "Done"
log "Env file: ${HF_ENV_FILE}"
log "Storage mode: ${EDMG_MODEL_STORAGE_MODE}"
log "Restart backend with:"
echo "  source \"${HF_ENV_FILE}\""
echo "  EDMG_BACKEND_ENV_MODE=active EDMG_SKIP_BOOTSTRAP=1 bash scripts/start_lightning_backend.sh"
