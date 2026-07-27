#!/usr/bin/env bash
set -euo pipefail

# Linux/Lightning Ollama sidecar setup for EDMG Studio.
#
# Cloud models such as nemotron-3-ultra:cloud require an authenticated Ollama
# installation. Run this once with OLLAMA_SIGNIN=1 for an interactive headless
# sign-in URL, then rerun or let the script continue to pull the model.

EDMG_STUDIO_HOME="${EDMG_STUDIO_HOME:-${HOME}/edmg-studio-home}"
EDMG_STUDIO_DATA_DIR="${EDMG_STUDIO_DATA_DIR:-${EDMG_STUDIO_HOME}/data}"
EDMG_STUDIO_MODELS_DIR="${EDMG_STUDIO_MODELS_DIR:-${EDMG_STUDIO_HOME}/models}"
EDMG_STUDIO_CACHE_DIR="${EDMG_STUDIO_CACHE_DIR:-${EDMG_STUDIO_HOME}/cache}"
EDMG_STUDIO_LOGS_DIR="${EDMG_STUDIO_LOGS_DIR:-${EDMG_STUDIO_HOME}/logs}"
EDMG_STUDIO_EXTERNAL_DIR="${EDMG_STUDIO_EXTERNAL_DIR:-${EDMG_STUDIO_HOME}/external}"
OLLAMA_HOST_VALUE="${OLLAMA_HOST:-127.0.0.1:${OLLAMA_PORT:-11434}}"
OLLAMA_MODELS="${OLLAMA_MODELS:-${EDMG_STUDIO_MODELS_DIR}/ollama}"
OLLAMA_LOG_DIR="${OLLAMA_LOG_DIR:-${EDMG_STUDIO_LOGS_DIR}}"
OLLAMA_LOG_FILE="${OLLAMA_LOG_FILE:-${OLLAMA_LOG_DIR}/ollama.log}"
EDMG_AI_OLLAMA_MODEL="${EDMG_AI_OLLAMA_MODEL:-nemotron-3-ultra:cloud}"
OLLAMA_INSTALL_SCRIPT_URL="${OLLAMA_INSTALL_SCRIPT_URL:-https://ollama.com/install.sh}"
OLLAMA_START="${OLLAMA_START:-1}"
OLLAMA_PULL_MODEL="${OLLAMA_PULL_MODEL:-1}"
OLLAMA_SIGNIN="${OLLAMA_SIGNIN:-0}"
OLLAMA_START_PUBLIC="${OLLAMA_START_PUBLIC:-0}"

export EDMG_STUDIO_HOME
export OLLAMA_MODELS
export EDMG_AI_MODE="${EDMG_AI_MODE:-local}"
export EDMG_AI_PROVIDER="${EDMG_AI_PROVIDER:-ollama}"
export EDMG_AI_OLLAMA_URL="${EDMG_AI_OLLAMA_URL:-http://127.0.0.1:${OLLAMA_PORT:-11434}}"
export EDMG_AI_OLLAMA_MODEL

log() {
  echo "[ollama-linux] $*"
}

warn() {
  echo "[ollama-linux][warn] $*" >&2
}

fail() {
  echo "[ollama-linux][error] $*" >&2
  exit 1
}

if [[ "${OLLAMA_START_PUBLIC}" == "1" ]]; then
  warn "OLLAMA_START_PUBLIC=1 exposes Ollama beyond localhost. Only use this behind a firewall."
else
  OLLAMA_HOST_VALUE="127.0.0.1:${OLLAMA_PORT:-11434}"
fi
export OLLAMA_HOST="${OLLAMA_HOST_VALUE}"

mkdir -p \
  "${OLLAMA_MODELS}" \
  "${OLLAMA_LOG_DIR}" \
  "${EDMG_STUDIO_DATA_DIR}" \
  "${EDMG_STUDIO_CACHE_DIR}" \
  "${EDMG_STUDIO_EXTERNAL_DIR}"

if ! command -v ollama >/dev/null 2>&1; then
  log "Installing Ollama from ${OLLAMA_INSTALL_SCRIPT_URL}"
  curl -fsSL "${OLLAMA_INSTALL_SCRIPT_URL}" | sh
else
  log "Ollama already installed: $(ollama --version 2>/dev/null || true)"
fi

if [[ "${OLLAMA_SIGNIN}" == "1" ]]; then
  log "Starting Ollama sign-in. Open the printed URL in your browser."
  ollama signin
fi

if [[ "${OLLAMA_START}" == "1" ]]; then
  if curl -fsS "http://127.0.0.1:${OLLAMA_PORT:-11434}/api/version" >/dev/null 2>&1; then
    log "Ollama is already reachable at http://127.0.0.1:${OLLAMA_PORT:-11434}"
  else
    log "Starting Ollama at ${OLLAMA_HOST}"
    pkill -f "ollama serve" >/dev/null 2>&1 || true
    nohup env OLLAMA_HOST="${OLLAMA_HOST}" OLLAMA_MODELS="${OLLAMA_MODELS}" ollama serve >"${OLLAMA_LOG_FILE}" 2>&1 &
    for _ in $(seq 1 60); do
      if curl -fsS "http://127.0.0.1:${OLLAMA_PORT:-11434}/api/version" >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
  fi
fi

if ! curl -fsS "http://127.0.0.1:${OLLAMA_PORT:-11434}/api/version" >/dev/null 2>&1; then
  fail "Ollama is not reachable. Check ${OLLAMA_LOG_FILE}."
fi

log "Ollama API is reachable"
curl -fsS "http://127.0.0.1:${OLLAMA_PORT:-11434}/api/version" || true
echo

if [[ "${OLLAMA_PULL_MODEL}" == "1" ]]; then
  log "Pulling ${EDMG_AI_OLLAMA_MODEL}"
  if ! OLLAMA_HOST="http://127.0.0.1:${OLLAMA_PORT:-11434}" OLLAMA_MODELS="${OLLAMA_MODELS}" ollama pull "${EDMG_AI_OLLAMA_MODEL}"; then
    if [[ "${EDMG_AI_OLLAMA_MODEL}" == *":cloud"* ]]; then
      cat >&2 <<EOF
[ollama-linux][error] Failed to pull cloud model ${EDMG_AI_OLLAMA_MODEL}.

Cloud models require Ollama sign-in on this machine:

  OLLAMA_SIGNIN=1 bash scripts/setup_linux_ollama.sh

Open the printed URL, complete sign-in, then rerun this script.
EOF
    fi
    exit 1
  fi
fi

cat >"${EDMG_STUDIO_HOME}/ollama.env" <<EOF
export EDMG_AI_MODE=local
export EDMG_AI_PROVIDER=ollama
export EDMG_AI_OLLAMA_URL=http://127.0.0.1:${OLLAMA_PORT:-11434}
export EDMG_AI_OLLAMA_MODEL=${EDMG_AI_OLLAMA_MODEL}
export OLLAMA_MODELS=${OLLAMA_MODELS}
EOF

log "Testing ${EDMG_AI_OLLAMA_MODEL}"
if ! curl -fsS "http://127.0.0.1:${OLLAMA_PORT:-11434}/api/chat" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${EDMG_AI_OLLAMA_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Say ok.\"}],\"stream\":false}" >/tmp/edmg-ollama-chat-test.json; then
  if [[ "${EDMG_AI_OLLAMA_MODEL}" == *":cloud"* ]]; then
    warn "Chat test failed. If the response is Unauthorized, rerun with OLLAMA_SIGNIN=1 and restart Ollama."
  else
    warn "Chat test failed. Inspect ${OLLAMA_LOG_FILE}."
  fi
else
  log "Chat test response written to /tmp/edmg-ollama-chat-test.json"
fi

log "Done"
log "EDMG Ollama env: ${EDMG_STUDIO_HOME}/ollama.env"
log "Backend exports:"
echo "  export EDMG_AI_MODE=local"
echo "  export EDMG_AI_PROVIDER=ollama"
echo "  export EDMG_AI_OLLAMA_URL=http://127.0.0.1:${OLLAMA_PORT:-11434}"
echo "  export EDMG_AI_OLLAMA_MODEL=${EDMG_AI_OLLAMA_MODEL}"
