# EDMG Studio Monolith Repo

This repository is the single authoritative source tree for EDMG Studio.

Studio is not a sidecar anymore. The desktop shell, React frontend, FastAPI
backend, vendored EDMG engine packages, setup flow, release packaging, and
support tooling all converge on one product path:

- `studio/edmg-studio/`

The older standalone-engine installers, duplicate Electron shell, and extra
README entrypoints have been retired so the repo presents one product instead
of multiple competing workflows.

The legacy standalone web UI prototypes have also been retired. Their planning
and audio-reactive capabilities now live inside the Studio app workbenches:

- `studio/edmg-studio/src/workbenches/AiNlpWorkbench.tsx`
- `studio/edmg-studio/src/workbenches/AudioReactiveWorkbench.tsx`

## Canonical launch

Windows:

```bat
RUN_ME.bat
```

macOS/Linux:

```bash
./run_me.sh
```

Those launchers open the Studio dev launcher in `studio/edmg-studio/tools/launcher_gui.py`, which
keeps the UI, backend, and `Studio Home` storage aligned with the same settings
used by the packaged app.

## Canonical product layout

- `studio/edmg-studio/`
  Electron shell, preload, main-process runtime, React/Vite frontend, packaging
  scripts, and release validation.
- `studio/edmg-studio/python_backend/`
  FastAPI backend plus the vendored `enhanced_deforum_music_generator` and
  `deforum_music` engine packages that power planning, analysis, schedules, and
  EDMG Core support.
- `studio/edmg-studio/tools/launcher_gui.py`
  Shared dev launcher and Studio Home bootstrap flow.
- `studio/edmg-studio/packaging/windows/`
  Windows-first release orchestration for the packaged Studio app.

## Studio Home

Studio separates the app install directory from the heavy runtime storage root.
The `Studio Home` contains:

- `data`
- `models`
- `cache`
- `logs`
- `external`
- `electron`

That keeps large downloads, render caches, and external tools off the app
install path and allows migration to another drive such as `D:\`.

## Release and operator docs

- [studio/edmg-studio/README.md](D:\DWCTGenerativeSoundStudio\studio\edmg-studio\README.md)
- [RELEASE.md](D:\DWCTGenerativeSoundStudio\RELEASE.md)
- [docs/STUDIO_RELEASE_RUNBOOK.md](D:\DWCTGenerativeSoundStudio\docs\STUDIO_RELEASE_RUNBOOK.md)
- [docs/STUDIO_REPO_MAP.md](D:\DWCTGenerativeSoundStudio\docs\STUDIO_REPO_MAP.md)
- [docs/AI_PROVIDERS.md](D:\DWCTGenerativeSoundStudio\docs\AI_PROVIDERS.md)
- [docs/HF_VIDEO_MODELS.md](D:\DWCTGenerativeSoundStudio\docs\HF_VIDEO_MODELS.md)

## Recommended Local Stack

- Planner default: `qwen3:8b` via Ollama
- Low-resource planner: `qwen3:4b`
- OpenAI-compatible default model string: `qwen3-8b`
- Broad still-image default: SDXL Base 1.0
- Fast still-image option: SD3.5 Large Turbo
- Reference still guidance: SD3.5 ControlNet Blur, Canny, and Depth
- Primary HF video backend: Wan2.2 TI2V 5B
- Short image-to-video fallback: SVD XT Img2Vid

## Hardware Tiers

- Low-spec: `qwen3:4b` + SDXL Base 1.0
- Mid-range: `qwen3:8b` + SDXL Base 1.0 + SD3.5 Large Turbo + SD3.5 Blur/Canny
- High-end: `qwen3:8b` + SDXL Base 1.0 + SD3.5 Large Turbo + SD3.5 Blur/Canny/Depth + Wan2.2 TI2V 5B

## Compatibility note

The repo root now keeps only thin launch aliases and monolith-level docs. The
runtime code, packaging logic, backend engine packages, and operator tooling
live under `studio/edmg-studio/`.
