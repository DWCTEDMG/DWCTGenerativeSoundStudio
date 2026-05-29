# NVIDIA Omniverse Studio Rework

This branch starts a separate NVIDIA-first direction for EDMG Studio. The goal
is not to bolt NVIDIA services onto the current Electron app. The goal is to
define a new product lane where Omniverse, OpenUSD, RTX rendering, and NVIDIA AI
services are the default runtime assumptions.

For the broader product/service map, see
[`docs/NVIDIA_OFFICIAL_OPTIONS.md`](NVIDIA_OFFICIAL_OPTIONS.md).
For local setup, see [`docs/NVIDIA_GETTING_STARTED.md`](NVIDIA_GETTING_STARTED.md).

## Product thesis

EDMG NVIDIA Studio is a packaged Windows workstation app backed by GPU services:

- Omniverse Kit owns the desktop shell, USD stage editing, RTX viewport, and
  extension system.
- OpenUSD owns project, scene, timeline, camera, material, and render-variant
  data.
- NVIDIA NIM, NeMo, Riva, Audio2Face/ACE, Cosmos, Triton, TensorRT, and
  TensorRT-LLM own the heavy AI and inference lanes.
- The Windows package is a client/workstation app. Heavy services run locally
  through a GPU service stack, WSL2/Linux containers, a remote Linux GPU host, or
  a later cloud deployment.

The existing `studio/edmg-studio/` product remains the canonical desktop app for
this repository. This rework should evolve as a separate product surface until
the NVIDIA assumptions are proven.

## Target architecture

```text
EDMG NVIDIA Studio
|- Windows packaged Omniverse Kit app
|  |- OpenUSD stage editor
|  |- RTX viewport and render preview
|  |- audio timeline and beat/section map panels
|  |- AI Director panel
|  |- character and Audio2Face/ACE panel
|  |- render queue
|  `- model and service dashboard
|
|- EDMG API gateway
|  |- project and artifact metadata
|  |- job submission and status
|  |- service health aggregation
|  `- compatibility routes for existing Studio workflows
|
|- NVIDIA service layer
|  |- NIM LLM or multimodal endpoints
|  |- Riva ASR/TTS endpoints
|  |- NeMo training or customization jobs
|  |- Audio2Face/ACE character services
|  |- Cosmos world/video generation services
|  `- Triton/TensorRT/TensorRT-LLM serving backends
|
`- storage
   |- projects and USD stages
   |- audio sources and analysis caches
   |- model registry and downloaded weights
   |- render outputs
   `- job logs
```

## Windows package boundary

The Windows installer should include:

- Omniverse Kit runtime package or thin launcher setup.
- EDMG Kit app configuration.
- EDMG Kit extensions.
- connection profiles for local and remote GPU services.
- local project workspace templates.
- small smoke-test sample assets.

The Windows installer should not include:

- full NeMo training containers.
- full NIM service fleet.
- Cosmos checkpoints.
- large model weights.
- render-farm workers.

Those belong in a GPU service profile managed through Compose, Kubernetes, a
remote workstation, or a hosted deployment.

## OpenUSD project model

Use USD as the durable project contract instead of storing the creative state
only in React state or ad hoc JSON.

Proposed first-layer mapping:

- Song/project: root USD stage.
- Audio source: asset reference plus timeline metadata.
- Beat grid: time-sampled metadata or a companion JSON artifact referenced by
  the stage.
- Sections: USD timeline markers.
- AI scene plan: USD variants and custom metadata.
- Camera moves: animated camera prims.
- Prompt schedule: structured metadata attached to shots or section prims.
- Render variants: USD variant sets for style, camera, lighting, and model
  choices.

Keep raw AI responses as artifacts. Store normalized, user-editable decisions in
USD and project metadata.

## Service contracts

The first service contracts should stay HTTP and simple:

- `GET /health`
- `GET /v1/nvidia/status`
- `POST /v1/jobs`
- `GET /v1/jobs/{id}`
- `POST /v1/transcribe`
- `POST /v1/plan`
- `POST /v1/usd/scene-plan`
- `POST /v1/render`

The existing EDMG AI service already has `/v1/plan`, `/v1/transcribe`, and
`/v1/audio_features`; keep those as compatibility routes while adding
NVIDIA-specific orchestration around them.

Starter branch status:

- `/v1/nvidia/status` reports the masked NVIDIA service profile.
- `/v1/nvidia/diagnostics` reports host GPU, Docker NVIDIA runtime, and NIM
  endpoint reachability without exposing credentials. It also returns a
  normalized readiness block with required checks and next actions for the
  official local NVIDIA service stack.
- `/v1/nvidia/scene-plan` asks the configured NVIDIA/NIM-compatible planner for
  a plan, converts the selected variant into the normalized NVIDIA scene-plan
  contract, and returns a generated USDA preview.
- `/v1/usd/scene-plan` validates a scene plan and returns normalized USD-style
  metadata keys plus a generated USDA text preview.
- `studio/nvidia-kit/apps/edmg.nvidia.studio.kit` declares the first Kit app
  shell and four EDMG extension skeletons.
- `edmg.ai_director.backend_client` can call the NVIDIA status and USD scene
  plan contracts from a Kit extension without third-party Python packages.
- `studio/nvidia-kit/tools/export_scene_plan_usda.py` writes a scene-plan JSON
  artifact to a starter `.usda` file without requiring Omniverse locally.
- `studio/nvidia-kit/tools/smoke_ai_director_backend.py` validates the same
  backend contract from the Kit workspace.

## First milestone

Build a minimum useful NVIDIA path:

1. Package or run a minimal Omniverse Kit app called EDMG NVIDIA Studio.
2. Open a starter USD stage with camera, lights, and audio timeline metadata.
3. Connect to a configured NIM-compatible LLM endpoint for AI scene planning.
4. Connect to a configured Riva-compatible ASR endpoint for transcription, or
   fall back to the current faster-whisper path.
5. Write the normalized scene plan back into project metadata.
6. Render a short RTX preview or export a render job request.

## Repository layout proposal

```text
deployment/nvidia/
|- README.md
`- docker-compose.nvidia.yml

studio/nvidia-kit/
|- README.md
|- apps/edmg.nvidia.studio.kit
|- extensions/
|  |- edmg.timeline/
|  |- edmg.ai_director/
|  |- edmg.usd_schema/
|  `- edmg.render_queue/
`- sample_projects/
```

This branch adds the deployment, architecture starter, and Kit source skeleton.
Runtime packaging still depends on choosing the exact Kit SDK/template version
and verifying Windows packaging locally.

## Risks to settle early

- Omniverse Kit runtime redistribution and packaging constraints.
- Which NVIDIA services are required, optional, or enterprise-only.
- Whether local Windows users run services through WSL2 Docker or only connect
  to remote Linux GPU machines.
- USD schema design before generated projects accumulate.
- Model storage and license acceptance flow.
- How much of the existing Electron UI should be preserved versus rebuilt as
  Kit extensions.
