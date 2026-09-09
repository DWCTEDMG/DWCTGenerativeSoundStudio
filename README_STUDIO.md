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

The primary Windows customer artifact is `EDMG-Studio-<version>-windows-x64-Setup.exe`. It installs a
signed, self-contained WinUI MSIX so package identity remains available for activation, Credential
Locker, and Windows integrations. Electron installers are compatibility artifacts, not the default
Windows release.

## Quick start (dev)

1. Start Studio backend

```powershell
uv lock --project studio\edmg-studio\python_backend --check
uv sync --project studio\edmg-studio\python_backend --frozen --extra cpu --extra core --extra audio
uv run --project studio\edmg-studio\python_backend --frozen --extra cpu --extra core --extra audio `
  python -m edmg_studio_backend serve --host 127.0.0.1 --port 7863
```

Python 3.12 and uv 0.11.28 are pinned repository inputs. Select one accelerator extra (`cpu`,
`directml`, or `cuda`) when synchronizing a different backend profile.

2. Start Studio UI

Windows packaged app (from `studio/edmg-studio-winui`):

- open `EdmgStudio.WinUI.slnx` in Visual Studio, select `Release` and `x64`, set
  `EdmgStudio.WinUI` as the startup project, select the `EdmgStudio.WinUI (Package)` profile,
  and press F5 or Ctrl+F5
- from PowerShell, the equivalent source launch is `dotnet run --project .\EdmgStudio.WinUI.csproj
  --launch-profile "EdmgStudio.WinUI (Package)" -p:Platform=x64`
- never run the generated packaged executable directly
- retain `Package.appxmanifest`; package identity is part of the supported runtime contract

Linux/compatibility client:

- `cd studio/edmg-studio`
- `corepack enable`
- `pnpm install`
- `pnpm run dev`

The backend runs planning in-process, so a separate AI service is not required. The selected provider
may be NVIDIA-hosted, another OpenAI-compatible endpoint, local Ollama, or the built-in rule-based
planner.

## Managed model readiness

The backend implements managed adapters for Qwen3-VL 8B/30B GGUF, Whisper large-v3-turbo,
LTX-2.5 Distilled, and HunyuanVideo-1.5. Installing weights does not make a model ready: use the
Models page smoke-test action and require backend Level-5 real-inference qualification. Readiness is
invalidated when package files, dependencies, runner configuration, hardware, or the selected device
changes. See [`studio/edmg-studio/python_backend/README.md`](studio/edmg-studio/python_backend/README.md#managed-model-runtimes).

## Secondary surfaces

These remain in the repo for compatibility or engine-specific workflows, but
they are not equal alternatives to the Studio product path:

- `start.bat` / `start.sh` for the standalone engine UI
- `desktop/electron/` legacy shell
- archived prototype UI files in `examples/archive-ui/`
