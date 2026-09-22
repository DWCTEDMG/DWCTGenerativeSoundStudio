# EDMG Studio (Compatibility Electron Shell)

This older shell is retained for compatibility. The canonical Studio surfaces are:

- `studio/edmg-studio-winui/` for the primary packaged Windows client
- `studio/edmg-studio/` for the shared backend and maintained Linux/compatibility client

Use the root launcher (`RUN_ME.bat` / `./run_me.sh`) or see [`README_STUDIO.md`](../../README_STUDIO.md) for the current product entrypoint.
The [WinUI 3 consolidated blueprint](../../blueprint/WINUI3_CONSOLIDATED_BLUEPRINT.md) is the
current Windows status and release-gate reference. This shell must not be used as a Windows release
candidate.

This is a **JSON-first** Electron GUI for the Enhanced Deforum Music Generator.
It starts its legacy FastAPI path automatically and gives you a full Deforum settings JSON editor.
This shell predates the current Studio GPU-first accelerator policy; do not use its startup behavior
to provision or qualify the active WinUI/shared-backend environment. It includes:

- Audio analysis upload (tempo / beats / energy)
- Optional Whisper-based lyrics transcription (if installed)
- Sync calibration (estimates a small audio->video offset)
- Bundled Hugging Face video model catalog + downloader
- One-click generation of a complete Deforum settings JSON
- Quick utilities to open common folders (outputs, models_store, repo root)
- Restart button for the backend API

## Run manually only if you specifically need this compatibility shell

From the repo root:

```bash
cd desktop/electron
corepack pnpm install
corepack pnpm run start
```

### Python selection

By default the app runs `python -m scripts.run_api` from the repo root.
If you want it to use a specific venv, set:

```bash
set EDMG_PYTHON=C:\path\to\venv\Scripts\python.exe
```

### Backend port (legacy shell)

```bash
set EDMG_API_PORT=7862
```

## Notes

- The UI loads JSONEditor from `node_modules`, so it works offline.
- The backend defaults to 720p @ 30fps in the template.
- This is not a release-authoritative Studio path. Prefer `studio/edmg-studio-winui` on Windows or
  the maintained client under `studio/edmg-studio` on Linux.

## Optional Studio-wide TensorRT capability

EDMG Studio supports optional TensorRT acceleration through the shared backend runtime manager. Studio settings provide the global switch; native Render controls can override the preference, precision, and fallback for an individual internal render. Turning TensorRT off preserves the original runtime and does not require TensorRT to be installed.

This area retains its existing runtime and workflow; the shared Studio policy applies only to eligible internal inference components. The SD1.5 VAE decoder has an adapter; other model components remain on their existing runtimes until separately converted and validated. Hosted providers, audio processing, compositing, and exports do not acquire a TensorRT dependency. See the [Studio-wide TensorRT blueprint](../../EDMG_TensorRT_Full_Studio_Wide_Blueprint.md) for component admission and validation requirements.
