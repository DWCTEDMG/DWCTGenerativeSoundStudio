# EDMG Studio

This repo includes the Studio desktop product under:

- `studio/edmg-studio-winui/` — primary packaged Windows frontend
- `studio/edmg-studio/` — Electron/React frontend for Linux and compatibility

Both frontends use the same local FastAPI backend and project format for the "DAW-like" Studio
experience (projects → audio ingest → AI plan → timeline → render queue → review → outputs).
CUDA, TensorRT, analysis, rendering, and model lifecycle remain authoritative in Python.

The original DWCTEDMG codebase remains the engine + integrations, but Studio is the
canonical product surface and can install the EDMG Core engine into the same workflow.
For release/install operations, use [docs/STUDIO_RELEASE_RUNBOOK.md](docs/STUDIO_RELEASE_RUNBOOK.md) and [RELEASE.md](RELEASE.md).
For the top-level repo surface and compatibility map, see [docs/STUDIO_REPO_MAP.md](docs/STUDIO_REPO_MAP.md).

## Authoritative product path

From the repo root:

- `RUN_ME.bat`
- `./run_me.sh`

Compatibility aliases may still exist. On Windows, launch the packaged WinUI app; on Linux use the
Electron/React Studio launcher.

That launcher keeps the Studio product aligned with the same `Studio Home`, backend port,
and runtime data that the in-app Setup page uses.
The Studio backend install/build path now targets EDMG Core as part of the same backend bundle, the packaged Studio app bundles FFmpeg for the internal renderer, and Ollama plus ComfyUI remain external tools.
The packaged Windows installer is now configured as an assisted installer so the app install location can be chosen explicitly, while `Studio Home` remains the separate root for heavy runtime data on `D:\` or another drive.

## Quick start (dev)

1. Start Studio backend
- `cd studio/edmg-studio/python_backend`
- create venv with Python `>=3.10,<3.14`, `pip install -e ".[studio_bundle]"`
- run `edmg-studio-backend serve --host 127.0.0.1 --port 7863`

2. Start Studio UI

Windows packaged app (from `studio/edmg-studio-winui`):

- use the WinUI `BuildAndRun.ps1` workflow with `EdmgStudio.WinUI.csproj`; it builds x64,
  registers the package, and launches it through `winapp run --debug-output`
- never run the generated packaged executable directly
- if Developer Mode, .NET, or `winapp` is missing, install the prerequisite through
  the supported WinUI setup workflow before retrying; do not switch to an unpackaged build

Linux/compatibility client:

- `cd studio/edmg-studio`
- `npm install`
- `npm run dev`

The backend talks to local Ollama directly by default, so a separate AI service is not required for the normal Studio flow.

## Secondary surfaces

These remain in the repo for compatibility or engine-specific workflows, but
they are not equal alternatives to the Studio product path:

- `start.bat` / `start.sh` for the standalone engine UI
- `desktop/electron/` legacy shell
- archived prototype UI files in `examples/archive-ui/`
