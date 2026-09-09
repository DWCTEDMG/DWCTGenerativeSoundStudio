# EDMG Studio Backend (v1.2.0)

## Run
```bash
uv lock --check
uv sync --frozen --extra cpu --extra core --extra audio --extra asr --extra internal-video
uv run --frozen --extra cpu --extra core --extra audio --extra asr --extra internal-video \
  python -m edmg_studio_backend serve --host 127.0.0.1 --port 7863
```

Python is pinned to 3.12 and uv to 0.11.28. Choose exactly one accelerator
profile (`cpu`, `directml`, or `cuda`) and compose it with the capabilities the
deployment needs. PyTorch sources are explicit lock inputs, not runtime index
overrides.

## Docker (backend only)

This Docker path runs the FastAPI backend only. The WinUI Windows client or Electron/React
compatibility client still runs natively on the host.

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
Synchronize the frozen CPU test environment and run pytest through uv:

```bash
uv lock --check
uv sync --frozen --extra cpu --extra core --extra audio --group test
uv run --frozen --extra cpu --extra core --extra audio --group test python -m pytest
```

Run that command from `studio/edmg-studio/python_backend/`. The backend-local
pytest scope covers both:

- `enhanced_deforum_music_generator/tests`
- `edmg_studio_backend/tests`

From the repo root:

- `uv run --project studio/edmg-studio/python_backend --frozen --extra cpu --group test python -m pytest` runs repo-level tests only
- `uv run --project studio/edmg-studio/python_backend --frozen --extra cpu --extra core --extra audio --group test python scripts/run_pytest_scopes.py` runs repo-level tests, then backend-local tests

## Managed model runtimes

Managed model installation and runtime readiness are separate. Models become ready only after
the Models page runtime smoke test completes a real inference and writes a receipt matching the
current package, dependencies, runner configuration, and selected GPU.

Runtime status is available through `GET /v1/runtimes` and
`GET /v1/runtimes/{model_id}/readiness`; supported real-inference qualification runs through
`POST /v1/runtimes/{model_id}/smoke-test`. The four states are `not_installed`,
`installed_runtime_unavailable`, `runtime_degraded`, and `runtime_ready`.

| Package ID | Runtime adapter |
| --- | --- |
| `hf_qwen3_vl_8b_gguf_director` | Qwen3-VL 8B GGUF through managed llama.cpp server |
| `hf_qwen3_vl_30b_gguf_director` | Qwen3-VL 30B GGUF through managed llama.cpp server |
| `hf_whisper_large_v3_turbo_internal` | Transformers Whisper large-v3-turbo |
| `hf_ltx_25_distilled_internal` | LTX-2.5 Distilled through isolated `ltx-pipelines==1.3.0` |
| `hf_hunyuan_video15_internal` | Official HunyuanVideo-1.5 through WSL2/external Linux |

Qwen requires an exact GGUF/projector pair and a compatible `llama-server.exe`. Whisper supports
CPU or an explicitly selected `cuda:N`; Qwen supports CPU or explicit CUDA isolation. The video
runtimes have the additional requirements below.

### LTX-2.5

LTX-2.5 runs in an isolated Python environment containing exactly `ltx-pipelines==1.3.0`.
Point Studio at that interpreter with `EDMG_LTX25_PYTHON`. The managed model package supplies
the transformer, Gemma text encoder, video/audio VAEs, duration head, and spatial upsampler.
CUDA is required; `cuda:N` is isolated through `CUDA_VISIBLE_DEVICES`, while the pipeline's CPU
offload option can reduce VRAM use. Optional overrides are `EDMG_LTX25_TIMEOUT_SECONDS` and
`EDMG_LTX25_SMOKE_TIMEOUT_SECONDS`.

### HunyuanVideo-1.5

The official Hunyuan runtime is Linux-only. On Windows, configure WSL2 or an externally managed
Linux Python environment; Studio does not silently substitute a different implementation:

```text
EDMG_HUNYUAN15_RUNNER=wsl                 # or external
EDMG_HUNYUAN15_WSL_DISTRO=<distro>        # optional for wsl
EDMG_HUNYUAN15_PYTHON=<linux-python>
EDMG_HUNYUAN15_REPO=<official-checkout>
EDMG_HUNYUAN15_LLM_PATH=<Qwen2.5-VL assets>
EDMG_HUNYUAN15_BYT5_PATH=<ByT5 assets>
EDMG_HUNYUAN15_GLYPH_PATH=<Glyph-SDXL-v2 assets>
EDMG_HUNYUAN15_VISION_PATH=<FLUX Redux/SigLIP assets>
EDMG_HUNYUAN15_TIMEOUT_SECONDS=3600
```

The Tencent package does not include those separately licensed companion assets. Studio validates
their configured paths and the official `HunyuanVideo_1_5_Pipeline.create_pipeline` environment,
isolates the requested `cuda:N`, and remains unavailable until real inference succeeds.

### Opt-in real-model qualification tests

Normal CI uses synthetic packages and mocked subprocesses. To run real Level-5 inference against
one or more existing managed installations, explicitly provide the package IDs, installation roots,
and target device. The test fails rather than skips when an opted-in package or runtime is incomplete:

```powershell
$env:REAL_MODEL_TESTS = "1"
$env:EDMG_REAL_MODEL_IDS = "hf_ltx_25_distilled_internal"
$env:EDMG_REAL_MODEL_ROOTS = '{"hf_ltx_25_distilled_internal":"D:\EDMG\models\internal\video\hf_ltx_25_distilled_internal"}'
$env:EDMG_REAL_MODEL_DEVICE = "cuda:0"
uv run --project studio\edmg-studio\python_backend --frozen --extra cpu --extra core --extra audio --group test `
  python -m pytest studio\edmg-studio\python_backend\edmg_studio_backend\tests\test_model_runtime_registry.py `
  -k opt_in_real_model_runtime_smoke_tests -v
```

The configured package must already have a valid `model.json` installation receipt. LTX, Hunyuan,
and Qwen also require their documented external runtime configuration. A successful run writes the
same hardware- and runtime-fingerprinted `runtime-validation.json` receipt used by the Models UI.

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
