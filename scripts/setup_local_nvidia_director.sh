#!/usr/bin/env bash
set -euo pipefail

# Isolated GPU environment; never synchronize Studio's Windows render runtime.
studio_uv="${EDMG_UV:-$HOME/.local/bin/uv}"
studio_env="$HOME/.venvs/studio-nvidia"
studio_scripts="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$studio_uv" ]]; then
  echo "Install the repository-pinned uv 0.11.28 in WSL first." >&2
  exit 1
fi
if [[ ! -x "$studio_env/bin/python" ]]; then
  "$studio_uv" venv --python 3.12 "$studio_env"
fi
export UV_HTTP_TIMEOUT=300
"$studio_uv" pip install --python "$studio_env/bin/python" \
  torch==2.10.0 torchvision==0.25.0 transformers==5.19.0 \
  accelerate kernels==0.17.2 huggingface_hub fastapi uvicorn httpx timm einops \
  librosa soundfile av open_clip_torch setuptools qwen-vl-utils \
  --extra-index-url https://download.pytorch.org/whl/cu128
"$studio_env/bin/python" "$studio_scripts/download_local_nvidia_models.py" "$@"
"$studio_env/bin/python" -c 'import torch; assert torch.cuda.is_available(), "CUDA is required"; print(torch.__version__, torch.cuda.device_count(), "CUDA devices")'
