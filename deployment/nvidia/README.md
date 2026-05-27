# NVIDIA Service Profile

This directory is the first deployment lane for the NVIDIA-first EDMG Studio
rework.

For the larger official NVIDIA product map and Windows packaging boundary, see
[`docs/NVIDIA_OFFICIAL_OPTIONS.md`](../../docs/NVIDIA_OFFICIAL_OPTIONS.md).
For the step-by-step local setup path, see
[`docs/NVIDIA_GETTING_STARTED.md`](../../docs/NVIDIA_GETTING_STARTED.md).

The immediate goal is to keep the existing backend usable while pointing its AI
routes at NVIDIA-hosted or locally hosted services. The longer-term goal is a
dedicated Omniverse Kit app plus a GPU service stack.

## Intended runtime split

```text
Windows package
|- Omniverse Kit app
|- USD editor and RTX viewport
|- project browser
`- service connection profiles

GPU service stack
|- EDMG backend/API gateway
|- NIM-compatible LLM endpoint
|- Riva-compatible ASR/TTS endpoint
|- NeMo training/customization jobs
|- optional Cosmos generation endpoint
`- optional ComfyUI/render workers
```

## Compose starter

Copy the example environment file and put local secrets in the ignored copy:

```powershell
Copy-Item deployment/nvidia/.env.example deployment/nvidia/.env.local
notepad deployment/nvidia/.env.local
```

Use this profile as an override with the existing Starlift Compose file:

```powershell
docker compose `
  --env-file deployment/nvidia/.env.local `
  -f docker-compose.starlift.yml `
  -f deployment/nvidia/docker-compose.nvidia.yml `
  up --build
```

By default this only reconfigures the existing backend for an OpenAI-compatible
NIM-style endpoint and NVIDIA mode metadata. Optional placeholder services live
behind Compose profiles because official NIM/Riva/NeMo images and model choices
depend on NVIDIA account access, EULAs, and target hardware.

## Required host assumptions

- NVIDIA GPU and current driver.
- Docker with NVIDIA Container Toolkit for Linux containers, or a remote Linux
  GPU host.
- Access to any required NGC images and model licenses.
- Enough disk for model caches and render artifacts.

## Windows preflight

Run the local preflight after Docker is installed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deployment/nvidia/check_nvidia_profile.ps1
```

The preflight checks Docker, visible NVIDIA GPUs, Docker NVIDIA runtime support,
env-file presence, masked NGC credential presence, and Compose syntax for both
the base override and optional `nvidia-local` profile. It never prints the key
value.

After the backend is running, smoke the NVIDIA API surface:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deployment/nvidia/smoke_nvidia_backend.ps1
```

## Environment knobs

```powershell
$env:EDMG_AI_PROVIDER="openai_compat"
$env:EDMG_AI_OPENAI_COMPAT_BASE_URL="http://host.docker.internal:8000/v1"
$env:EDMG_AI_OPENAI_COMPAT_MODEL="your-nim-model"
$env:EDMG_NVIDIA_MODE="1"
$env:EDMG_NVIDIA_PROFILE="omniverse"
```

For remote services, use the remote base URL instead of
`host.docker.internal`.

Credential split:

- `NGC_API_KEY` is for NVIDIA/NGC image and gated asset access.
- `EDMG_AI_OPENAI_COMPAT_API_KEY` is for the planner endpoint itself when that
  endpoint requires bearer authentication.
- Both values must stay in the shell, OS secret store, or an ignored
  `.env.local` file.

## First validation target

1. Start the existing backend with this override.
2. Confirm `/health` returns the configured OpenAI-compatible provider.
3. Send a small `/v1/plan` request through the current AI service contract.
4. Add a separate Riva/ASR adapter only after the planning path is stable.

## Official image policy

Do not commit private registry credentials, pulled model weights, or accepted
license artifacts. Keep image names configurable because official NVIDIA service
images vary by product, release channel, access level, and model family.
