# Linux Packaging Notes

EDMG Studio already ships Linux-aware runtime branches in the Electron shell, Setup Wizard, desktop artifact helpers, and packaged smoke validation. The Linux packaged target is the Electron `AppImage`.

## UI availability

The Linux AppImage contains the full Studio GUI/UI, with the same React Studio
pages and Electron bridge used by the Windows desktop build. Run it on an x64
Linux workstation with a graphical desktop.

On a headless Lightning, Vast, or other cloud Linux host, run only the backend
there. Connect to it from a local EDMG Studio AppImage or other desktop build
after selecting the external backend in **Settings**. For source development,
the Vite browser UI can also connect to that backend; it is not the packaged
Linux desktop distribution.

## Build on a Linux host

```bash
cd studio/edmg-studio
corepack enable
pnpm install
pnpm run validate:release:linux
```

That flow:

- runs the frontend typecheck and UI tests
- stages the desktop app bundle
- validates the Electron bridge and packaged smoke path
- builds the Linux `AppImage`

If you only need the artifact build:

```bash
cd studio/edmg-studio
pnpm run dist:linux
```

For an NVIDIA build host where the AppImage should bundle the CUDA/TensorRT
backend extra instead of the generic backend bundle, use:

```bash
cd studio/edmg-studio
pnpm run dist:linux:cuda
```

The CUDA build path performs `uv lock --check` and a frozen `cuda` profile sync.
The fixed PyTorch CUDA index, TensorRT packages, and capability extras come from
`pyproject.toml` and `uv.lock`. The target machine still needs a matching NVIDIA
driver and locally installed model weights.

## Runtime expectations

- FFmpeg can come from the packaged bundle or `EDMG_FFMPEG_PATH`
- Ollama is expected to be installed system-wide or provided via `EDMG_OLLAMA_PATH`
- ComfyUI is optional and should run as a separate Linux service when used
- the Windows-only managed 7-Zip and ComfyUI Portable installers do not apply on Linux
- managed cloud notebooks such as Lightning may already provide a writable
  Python/conda environment and may not allow project-local virtualenv creation

## Core audio and visual direction

The packaged Linux backend applies the same core capability pipeline as the
Windows desktop build:

- Every audio analysis records multitrack metadata. A normal single audio file
  uses the `mixed` track fallback, so no optional separator is required.
- Every generated or imported plan receives Studio style direction. A recognized
  style preference is used when supplied; otherwise Studio uses the
  `cinematic` baseline.
- `EDMG_DEV_PROFILING=true` records lightweight analysis-stage timings in the
  project diagnostics. It is a development-only setting and is disabled by
  default in the environment template.

## First-run notes

1. Mark the AppImage executable if needed: `chmod +x EDMG-Studio*.AppImage`
2. Launch the app.
3. Open `Setup`.
4. Choose a `Studio Home` on the storage volume you want for models, cache, logs, and external tools.

`Studio Home` can be on any writable local or mounted volume. Advanced setups
can place each category independently by setting `EDMG_STUDIO_DATA_DIR`,
`EDMG_STUDIO_MODELS_DIR`, `EDMG_STUDIO_CACHE_DIR`, `EDMG_STUDIO_LOGS_DIR`, and
`EDMG_STUDIO_EXTERNAL_DIR`; the Linux backend and sidecar launchers honor those
paths instead of forcing them below one drive or mount.

## Validation scope

`validate:release:linux` intentionally skips the Windows-only packaged customer-flow, upgrade-proof, and zero-state managed-installer proofs. Those remain covered by the Windows release path.

## Lightning / Managed Linux Backend

When the Linux host already has an active Python environment, use the backend
launcher in active-env mode instead of creating a virtualenv:

```bash
cd studio/edmg-studio
EDMG_BACKEND_ENV_MODE=active \
EDMG_BACKEND_ACCELERATOR_PROFILE=cuda \
bash scripts/start_lightning_backend.sh
```

Notes:

- `EDMG_BACKEND_ENV_MODE=active` directs uv to synchronize the active
  virtualenv/conda environment from the committed lock.
- `EDMG_BACKEND_ACCELERATOR_PROFILE` accepts `cpu` or `cuda` on Linux and
  selects exactly one locked accelerator profile.
- PyTorch indexes, TensorRT, NumPy, and all backend capabilities are resolved
  by the committed `uv.lock`; arbitrary package/index overrides are unsupported.
- Keep the public Lightning/backend port at `7863`. The local desktop/dev UI
  should connect to the generated `https://7863-...cloudspaces.litng.ai` URL.

If the active environment was already synchronized from this lock, you can skip
the write step. The launcher still runs a frozen `uv sync --check` and refuses
an environment that differs from the selected profile:

```bash
cd studio/edmg-studio
EDMG_SKIP_BOOTSTRAP=1 EDMG_BACKEND_ENV_MODE=active bash scripts/start_lightning_backend.sh
```

## Linux ComfyUI Motion Sidecar

EDMG can use ComfyUI for motion only when a live ComfyUI server exposes the
required node classes:

- `ADE_AnimateDiffLoaderGen1`
- `ADE_StandardStaticContextOptions`
- `SVDSimpleImg2Vid`

Install/start a Linux ComfyUI sidecar beside the backend:

```bash
cd studio/edmg-studio
COMFY_INSTALL_MODELS=1 \
bash scripts/setup_linux_comfyui.sh
```

The helper defaults to:

- ComfyUI root: `$EDMG_STUDIO_HOME/external/ComfyUI`
- ComfyUI URL: `http://127.0.0.1:8188`
- log file: `$EDMG_STUDIO_HOME/logs/comfyui.log`

`COMFY_INSTALL_MODELS=1` downloads the default SDXL checkpoint, SVD XT 1.1, and
the AnimateDiff v1.5 motion module. Some Stability AI downloads may require
accepting the Hugging Face license and setting `HF_TOKEN`.

Restart the backend with ComfyUI enabled:

```bash
export EDMG_COMFYUI_URL=http://127.0.0.1:8188
export EDMG_COMFYUI_CHECKPOINT=sd_xl_base_1.0.safetensors
EDMG_BACKEND_ENV_MODE=active EDMG_SKIP_BOOTSTRAP=1 bash scripts/start_lightning_backend.sh
```

Validate from the backend host:

```bash
curl http://127.0.0.1:8188/object_info >/tmp/comfy-object-info.json
curl http://127.0.0.1:7863/v1/comfyui/capabilities
```

You only need to expose Lightning port `8188` when you want to inspect the
ComfyUI canvas in a browser. The EDMG backend should keep using the private
localhost URL.

## Linux Ollama Sidecar

Install/start Ollama beside the backend and pull the default NVIDIA Nemotron 3
Ultra cloud planner. In Ollama, the tag is `nemotron-3-ultra:cloud`; it is
NVIDIA's 550B / 55B-active Nemotron 3 Ultra model served through Ollama Cloud.

```bash
cd studio/edmg-studio
OLLAMA_SIGNIN=1 bash scripts/setup_linux_ollama.sh
```

Open the printed sign-in URL in your browser, complete Ollama sign-in, then run:

```bash
EDMG_AI_OLLAMA_MODEL=nemotron-3-ultra:cloud bash scripts/setup_linux_ollama.sh
```

The helper defaults to:

- Ollama URL: `http://127.0.0.1:11434`
- model: `nemotron-3-ultra:cloud`
- model store: `$EDMG_STUDIO_HOME/models/ollama`
- env file: `$EDMG_STUDIO_HOME/ollama.env`

Restart the backend with Ollama enabled:

```bash
source "$EDMG_STUDIO_HOME/ollama.env"
EDMG_BACKEND_ENV_MODE=active EDMG_SKIP_BOOTSTRAP=1 bash scripts/start_lightning_backend.sh
```

Cloud models are authenticated by the local Ollama installation after
`ollama signin`. Keep port `11434` private unless you have a narrow firewall and
an explicit reason to expose it.

If you want NVIDIA's own NIM endpoint instead of Ollama Cloud, skip the Ollama
sidecar and configure the backend's OpenAI-compatible provider:

```bash
export EDMG_AI_MODE=local
export EDMG_AI_PROVIDER=openai_compat
export EDMG_AI_OPENAI_COMPAT_BASE_URL=https://integrate.api.nvidia.com/v1
export EDMG_AI_OPENAI_COMPAT_MODEL=nvidia/llama-3.1-nemotron-ultra-253b-v1
export EDMG_AI_OPENAI_COMPAT_API_KEY="$NVIDIA_API_KEY"
```

Fresh backends with no env vars also default to `nemotron_cloud` through the
OpenAI-compatible NVIDIA NIM endpoint. Use the Ollama sidecar above only when
you want Ollama Cloud instead of direct NIM.

## Linux S3 Model Hosting

The backend supports S3-backed model hosting through the built-in model cache.
Use it when cloud GPU hosts should share large model assets instead of
redownloading them into every Studio Home.

Storage modes:

- `local_cache`: keep the local model file and mirror supported installs into
  S3. This is the safest default.
- `cloud_only`: upload/store supported assets in S3 and keep only the cloud
  record locally. Runtime restores materialize files when needed.

Configure and validate the model cache:

```bash
cd studio/edmg-studio

export AWS_REGION=us-east-1
export EDMG_AWS_MODEL_CACHE_BUCKET=your-edmg-model-bucket
export EDMG_AWS_MODEL_CACHE_PREFIX=models
export EDMG_MODEL_STORAGE_MODE=local_cache

bash scripts/setup_linux_s3_model_cache.sh
```

For S3-compatible providers, also set:

```bash
export EDMG_S3_ENDPOINT_URL=https://your-s3-compatible-endpoint
```

The helper writes:

```bash
$EDMG_STUDIO_HOME/s3-model-cache.env
```

Restart the backend with the S3 cache enabled:

```bash
source "$EDMG_STUDIO_HOME/s3-model-cache.env"
EDMG_BACKEND_ENV_MODE=active EDMG_SKIP_BOOTSTRAP=1 bash scripts/start_lightning_backend.sh
```

Then install models normally from Studio. Supported single-file ComfyUI assets
and internal Diffusers snapshots will be uploaded to S3 after install. Internal
Diffusers models are stored as `.zip` snapshot archives; S3 source entries for
internal models must also point at `.zip`, `.tar`, `.tar.gz`, or `.tgz` archives
containing `model_index.json`.

Required permissions for the configured bucket/prefix:

- `s3:HeadBucket`
- `s3:GetObject`
- `s3:PutObject`
- `s3:DeleteObject` for the setup probe, or run with `S3_VALIDATE_WRITE=0`
- `sts:GetCallerIdentity` for validation

To create the bucket from the helper, set `S3_CREATE_BUCKET=1`; by default it
only validates an existing bucket.

## Linux Hugging Face Bucket Model Cache

The backend also supports Hugging Face bucket-backed model hosting through the
built-in model cache. Project defaults ship in `launcher_env.defaults.json`
with the HF bucket enabled and `EDMG_MODEL_STORAGE_MODE=local_cache` so a fresh
install keeps usable local model copies while mirroring supported assets into
the bucket.

Authenticate once on the Linux host:

```bash
hf auth login
```

Configure and write a sourceable env file:

```bash
cd studio/edmg-studio

export EDMG_HF_BUCKET_ID=gulle1155/DWCTedmgAIStudioModels
export EDMG_HF_BUCKET_PREFIX=
export EDMG_MODEL_STORAGE_MODE=cloud_only

bash scripts/setup_linux_hf_bucket.sh
```

Restart the backend with the generated env file:

```bash
source "$EDMG_STUDIO_HOME/hf-bucket.env"
EDMG_BACKEND_ENV_MODE=active EDMG_SKIP_BOOTSTRAP=1 bash scripts/start_lightning_backend.sh
```

`cloud_only` is for explicitly remote-only installs. Leave the default
`local_cache` mode in place when you want local files mirrored into the bucket.

## Point Studio at a remote backend (Lightning / Vast / GCP)

Use the cross-platform backend switcher from the Studio root:

```bash
cd studio/edmg-studio
bash scripts/set_studio_remote_backend.sh external https://7863-example.cloudspaces.litng.ai
```

`start_lightning_backend.sh` now requires bearer authentication for its default `0.0.0.0` bind.
When `EDMG_BACKEND_AUTH_TOKEN` is not already present, it creates a mode-0600 token file at
`$EDMG_STUDIO_HOME/config/backend-auth-token` and reports that path without printing the token.
Transfer the token over your authenticated SSH/Lightning session, then paste it into **Studio
Settings → Desktop Backend → Backend Access Security**. The browser keeps it only for that tab;
Electron can persist it with OS-backed encryption. Keep the public endpoint behind HTTPS.

For a managed local backend on the same machine:

```bash
bash scripts/set_studio_remote_backend.sh managed 7863
```

This updates `.env`, `launcher_env.json`, `electron-resources/runtime-defaults.json`,
and `~/.config/EDMG Studio/bootstrap.json` on Linux.

## Browser-only dev on Linux

When running Vite without Electron:

```bash
cd studio/edmg-studio
pnpm exec vite --host 127.0.0.1 --port 5173 --strictPort
```

Open the UI with the backend URL as a query param:

```text
http://127.0.0.1:5173/?backendUrl=http://127.0.0.1:7863
```

## Render features on Linux

- **Proxy draft renders**: enabled by default. Disable in Settings → GPU / Render Runtime.
- **Motion sequencer**: available on the Render page for Parseq-style motion schedules on internal renders.
- **TensorRT path**: set `EDMG_BACKEND_ACCELERATOR_PROFILE=cuda` for source
  startup or build `pnpm run dist:linux:cuda`.

CUDA release validation:

```bash
cd studio/edmg-studio
pnpm run validate:release:linux:cuda
```
