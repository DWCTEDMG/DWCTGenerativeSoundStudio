# EDMG NVIDIA Kit App

This directory contains the starter Omniverse Kit version of EDMG Studio.

Do not treat this as an Electron replacement yet. The starter Kit app proves the
product boundary:

1. declares a Windows-launchable Kit app shape.
2. opens a starter OpenUSD stage.
3. loads audio timeline metadata.
4. calls the EDMG backend or NVIDIA service profile for planning.
5. writes normalized scene-plan metadata back to the project.
6. renders or previews a simple RTX scene.

Current starter layout:

```text
studio/nvidia-kit/
|- apps/edmg-nvidia-studio.kit
|- extensions/
|  |- edmg.timeline/
|  |- edmg.ai_director/
|  |- edmg.usd_schema/
|  `- edmg.render_queue/
|- sample_projects/
`- tools/
```

The app and extensions are source skeletons. A full Kit App Template checkout,
launcher scripts, and redistributable runtime packaging should be added only
after selecting and verifying a specific Omniverse Kit SDK/App Template version
on the target Windows build machine.

## Starter Sample

The first sample scene lives at:

- `sample_projects/audio_reactive_stage/stage.usda`
- `sample_projects/audio_reactive_stage/scene_plan.json`

Use it as the initial OpenUSD contract for the Kit proof-of-concept before
pulling in real user projects or large generated assets.

Validate the starter scene plan with:

```powershell
python studio/nvidia-kit/tools/validate_scene_plan.py studio/nvidia-kit/sample_projects/audio_reactive_stage/scene_plan.json
```

Validate the Kit app/extension skeleton with:

```powershell
python studio/nvidia-kit/tools/validate_kit_layout.py
```

Export the starter scene plan into a generated USDA file with:

```powershell
python studio/nvidia-kit/tools/export_scene_plan_usda.py `
  studio/nvidia-kit/sample_projects/audio_reactive_stage/scene_plan.json `
  studio/nvidia-kit/sample_projects/audio_reactive_stage/generated_scene_plan.usda
```

The `edmg.ai_director` extension also includes a dependency-free backend client
for the first API contracts:

- `GET /v1/nvidia/status`
- `POST /v1/usd/scene-plan`

Smoke those contracts from the Kit workspace with:

```powershell
python studio/nvidia-kit/tools/smoke_ai_director_backend.py `
  --backend-url http://127.0.0.1:8000 `
  --output-usda studio/nvidia-kit/sample_projects/audio_reactive_stage/generated_from_backend.usda
```
