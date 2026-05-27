# NVIDIA Getting Started

This is the local setup path for the NVIDIA-first branch.

## 1. Stay on the NVIDIA branch

```powershell
git switch codex/nvidia-omniverse-studio
```

## 2. Verify host prerequisites

Run the preflight from the repo root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deployment/nvidia/check_nvidia_profile.ps1 -EnvFile deployment/nvidia/.env.example
```

Expected baseline on a ready Windows workstation:

- Docker is found.
- `nvidia-smi` reports the local GPU.
- Docker reports an `nvidia` runtime.
- Compose config renders for the base and `nvidia-local` profiles.

This does not pull official NVIDIA images and does not print secrets.

## 3. Create the ignored local env file

```powershell
Copy-Item deployment/nvidia/.env.example deployment/nvidia/.env.local
notepad deployment/nvidia/.env.local
```

Put secrets only in `deployment/nvidia/.env.local`, the shell environment, or an
OS secret store. Do not paste keys into tracked docs, tests, or Compose files.

Important variables:

```dotenv
EDMG_NVIDIA_MODE=1
EDMG_NVIDIA_PROFILE=omniverse
EDMG_AI_PROVIDER=openai_compat
EDMG_AI_OPENAI_COMPAT_BASE_URL=http://host.docker.internal:8000/v1
EDMG_AI_OPENAI_COMPAT_MODEL=nvidia-nim-model
NGC_API_KEY=
EDMG_AI_OPENAI_COMPAT_API_KEY=
```

`NGC_API_KEY` is for NVIDIA/NGC image and gated asset access. The planner API key
is separate and belongs in `EDMG_AI_OPENAI_COMPAT_API_KEY` only when the target
endpoint requires bearer authentication.

## 4. Start the NVIDIA-aware stack

Base backend override:

```powershell
docker compose `
  --env-file deployment/nvidia/.env.local `
  -f docker-compose.starlift.yml `
  -f deployment/nvidia/docker-compose.nvidia.yml `
  up --build backend
```

Optional local NVIDIA services:

```powershell
docker compose `
  --profile nvidia-local `
  --env-file deployment/nvidia/.env.local `
  -f docker-compose.starlift.yml `
  -f deployment/nvidia/docker-compose.nvidia.yml `
  up
```

The optional profile needs real official NVIDIA image names in `.env.local`.
Placeholders are intentionally invalid so the repo does not pretend to know
which gated image, model family, or license channel your account can use.

## 5. Confirm the app sees the profile

From the backend:

```powershell
curl http://127.0.0.1:8000/v1/nvidia/status
curl http://127.0.0.1:8000/v1/config
```

From the desktop app:

- Setup page: active AI path includes NVIDIA enabled/disabled when profile data
  is available.
- Settings page: Live AI / NVIDIA Status shows NGC, NIM, Riva, and Omniverse
  configuration state without printing key values.

## 6. Validate the starter USD project

```powershell
python studio/nvidia-kit/tools/validate_scene_plan.py studio/nvidia-kit/sample_projects/audio_reactive_stage/scene_plan.json
python studio/nvidia-kit/tools/validate_kit_layout.py
python studio/nvidia-kit/tools/export_scene_plan_usda.py `
  studio/nvidia-kit/sample_projects/audio_reactive_stage/scene_plan.json `
  studio/nvidia-kit/sample_projects/audio_reactive_stage/generated_scene_plan.usda
```

The sample stage lives at:

```text
studio/nvidia-kit/sample_projects/audio_reactive_stage/stage.usda
```

The backend also exposes the same first contract as an API:

```powershell
curl -X POST http://127.0.0.1:8000/v1/usd/scene-plan `
  -H "Content-Type: application/json" `
  --data-binary "@studio/nvidia-kit/sample_projects/audio_reactive_stage/scene_plan.json"
```

The API response includes `usd_stage.text`, a generated USDA text preview that
matches the CLI exporter.

Or run the PowerShell smoke script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deployment/nvidia/smoke_nvidia_backend.ps1
```

The Kit workspace has an equivalent AI Director smoke:

```powershell
python studio/nvidia-kit/tools/smoke_ai_director_backend.py --backend-url http://127.0.0.1:8000
```

## Next implementation target

The next code target is `nvidia-nim-planner`: prove a real NIM/OpenAI-compatible
planner endpoint can complete the existing `/v1/plan` contract, then persist the
normalized result into USD project metadata.
