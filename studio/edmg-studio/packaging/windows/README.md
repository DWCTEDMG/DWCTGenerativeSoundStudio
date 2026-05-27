# Windows Release Build (Installer-grade)

This folder contains a **Windows-first** packaging pipeline that produces a DAW/game-like installer.

## Prereqs

- Windows 10/11 x64
- Python `>=3.10,<3.14` installed. If `python` points at an unsupported newer
  runtime, `build_all.ps1` will try the Windows `py` launcher selectors
  (`py -3.13`, `py -3.12`, `py -3.11`, `py -3.10`) before failing.
- Node.js 18+ on PATH
- `pnpm@10.33.0` available via `corepack enable` or a direct pnpm install
- Git (optional, for fetching ComfyUI)

Recommended (for AI):

- **Ollama** installed and running.

## One-command build

Open PowerShell in repo root and run:

```powershell
./studio/edmg-studio/packaging/windows/build_all.ps1
```

Outputs:

- `studio/edmg-studio/dist/` (final electron-builder output: installer + unpacked app)
- `studio/edmg-studio/release/staged-app/` (intermediate staged app passed to electron-builder)

The packaged desktop version comes from `studio/edmg-studio/package.json#version`.
`build_all.ps1` runs `pnpm run check:tooling` before `dist:win` so lockfile and
version metadata drift is caught before packaging.

## What gets bundled

- Electron UI
- Python backend compiled into `edmg-studio-backend.exe`
- A place to drop runtime deps:
  - `studio/edmg-studio/electron-resources/bin/ffmpeg.exe`
  - `studio/edmg-studio/electron-resources/backend/edmg-studio-backend.exe`

## Runtime defaults

- AI defaults to **local Ollama** (no separate AI server required)
  - `EDMG_AI_MODE=local`
  - `EDMG_AI_PROVIDER=ollama`

If you prefer a remote AI service:

```powershell
$env:EDMG_AI_MODE = "http"
$env:EDMG_AI_BASE_URL = "http://127.0.0.1:7862"
```


The build script auto-detects both backend layouts used in this repo:

- `studio/edmg-studio/python_backend/edmg_studio_backend`
- `studio/edmg-studio/python_backend/src/edmg_studio_backend`
