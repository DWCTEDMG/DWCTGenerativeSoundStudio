# EDMG Studio Backend (v1.1.0)

## Run
```bash
pip install -e ".[studio_bundle]"
edmg-studio-backend serve --host 127.0.0.1 --port 7863
```

## Docker (backend only)

This Docker path runs the FastAPI backend only. The Electron desktop shell still runs natively on the host.

Build from `studio/edmg-studio/python_backend`:

```bash
docker build -t edmg-studio-backend .
```

Run the backend container with persistent Studio storage:

```bash
docker run --rm -it \
  -p 7863:7863 \
  -v "$(pwd)/data:/studio/data" \
  -v "$(pwd)/models:/studio/models" \
  -v "$(pwd)/cache:/studio/cache" \
  -v "$(pwd)/logs:/studio/logs" \
  -v "$(pwd)/external:/studio/external" \
  -e EDMG_AI_OLLAMA_URL=http://host.docker.internal:11434 \
  -e EDMG_COMFYUI_URL=http://host.docker.internal:8188 \
  edmg-studio-backend
```

Notes:

- On Docker Desktop, `host.docker.internal` is usually the easiest way to reach Ollama and ComfyUI running on the host.
- On native Linux Docker installs, use the host IP or `--network=host` instead.
- The image installs the Studio backend bundle plus FFmpeg, `libsndfile`, and OpenMP runtime support for the current analysis/transcription stack.

## Tests
Install the same backend bundle Studio uses, plus the test extra:

```bash
pip install -e ".[studio_bundle,test]"
python -m pytest
```

Run that command from `studio/edmg-studio/python_backend/`. The backend-local
pytest scope covers both:

- `enhanced_deforum_music_generator/tests`
- `edmg_studio_backend/tests`

From the repo root:

- `python -m pytest` runs repo-level tests only
- `python scripts/run_pytest_scopes.py` runs repo-level tests, then backend-local tests

## S3-backed model hosting

Install the Studio backend bundle or the `aws` extra so `boto3` is available, then enable the cache with normal AWS credentials:

```bash
EDMG_AWS_MODEL_CACHE=1
EDMG_AWS_MODEL_CACHE_BUCKET=your-model-bucket
EDMG_AWS_MODEL_CACHE_PREFIX=models
EDMG_MODEL_STORAGE_MODE=local_cache
```

`local_cache` keeps local model files and mirrors supported installs into S3. `cloud_only` stores supported single-file ComfyUI assets and internal Diffusers snapshots in S3 without keeping a local copy, then restores them on demand through `resolve_installed_path(...)` or `/v1/models/restore_local`.

Catalog entries can use `source: "s3"` with `s3_uri: "s3://bucket/key"` or `s3_key: "prefix/model.safetensors"` plus the configured bucket. Single-file ComfyUI assets restore directly into the Studio models directory. Internal renderer entries (`target.engine: "internal"`) must point at a `.zip`, `.tar`, `.tar.gz`, or `.tgz` archive containing the Diffusers snapshot contents, with `model_index.json` either at the archive root or inside one top-level directory.

For S3-compatible storage, set `EDMG_S3_ENDPOINT_URL`.

## Compatibility shims

The repo-root `sitecustomize.py` and repo-root `librosa/` package are
source-tree compatibility shims for development and tests. The packaged Studio
backend relies on the declared dependencies in this `pyproject.toml` and does
not package those repo-root shims.

## AI (NVIDIA Nemotron cloud by default)

The backend defaults to **EDMG_AI_MODE=local** with **EDMG_AI_PROVIDER=nemotron_cloud** and calls NVIDIA NIM through the OpenAI-compatible API. No separate AI server is required when `EDMG_AI_OPENAI_COMPAT_API_KEY` (or Studio Settings → Tokens) is configured.

Recommended env vars:

```bash
EDMG_AI_MODE=local
EDMG_AI_PROVIDER=nemotron_cloud
EDMG_AI_OPENAI_COMPAT_BASE_URL=https://integrate.api.nvidia.com/v1
EDMG_AI_OPENAI_COMPAT_MODEL=nvidia/llama-3.1-nemotron-ultra-253b-v1
```

Local Ollama option:

```bash
EDMG_AI_MODE=local
EDMG_AI_PROVIDER=ollama
EDMG_AI_OLLAMA_URL=http://127.0.0.1:11434
EDMG_AI_OLLAMA_MODEL=nemotron-3-ultra:cloud
```

Use `qwen3:4b` instead on lighter CPU-only or low-memory systems.

If you want an external AI service instead:

```bash
EDMG_AI_MODE=http
EDMG_AI_BASE_URL=http://127.0.0.1:7862
```

OpenAI-compatible option (NVIDIA NIM / LM Studio / llama.cpp server / vLLM / Groq / Together, etc.):

```bash
EDMG_AI_MODE=local
EDMG_AI_PROVIDER=openai_compat
EDMG_AI_OPENAI_COMPAT_BASE_URL=https://integrate.api.nvidia.com/v1
EDMG_AI_OPENAI_COMPAT_MODEL=nvidia/llama-3.1-nemotron-ultra-253b-v1
EDMG_AI_OPENAI_COMPAT_API_KEY=...  # if required
```

If your OpenAI-compatible gateway exposes a different endpoint or model alias, override
`EDMG_AI_OPENAI_COMPAT_BASE_URL` and `EDMG_AI_OPENAI_COMPAT_MODEL` to match that server.

## Recommended local model stack

- Planner default: NVIDIA Nemotron Ultra via `nemotron_cloud` (NIM)
- Local Ollama planner: `nemotron-3-ultra:cloud` or low-resource `qwen3:4b`
- Broad still-image default: SDXL Base 1.0
- Fast still-image option: SD3.5 Large Turbo
- Reference still guidance: SD3.5 ControlNet Blur, Canny, and Depth
- Primary HF video backend: Wan2.2 TI2V 5B
- Short image-to-video fallback: SVD XT Img2Vid

## Hardware tiers

- Low-spec: `qwen3:4b` (Ollama) + SDXL Base 1.0
- Mid-range: Nemotron cloud or `qwen3:8b` + SDXL Base 1.0 + SD3.5 Large Turbo + SD3.5 Blur/Canny
- High-end: Nemotron cloud + SDXL Base 1.0 + SD3.5 Large Turbo + SD3.5 Blur/Canny/Depth + Wan2.2 TI2V 5B

## Integrations
- ComfyUI renders are queued locally.
- Planning/transcription run in-process by default through the selected provider; an external AI service on `7862` is optional.
- S3-backed and Hugging Face bucket model hosting can cache or source supported ComfyUI model files and internal Diffusers snapshot archives.
- EDMG Core is bundled into the Studio backend install/build target; Studio Setup can repair or reinstall it if needed.
- FFmpeg defaults to the Studio-bundled binary when available; `EDMG_FFMPEG_PATH` remains an override.
