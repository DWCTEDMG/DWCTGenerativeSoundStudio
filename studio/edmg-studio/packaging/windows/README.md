# Windows Release Build (Installer-grade)

This folder contains a **Windows-first** packaging pipeline that produces a DAW/game-like installer.

## Prereqs

- Windows 10/11 x64
- `uv` 0.11.28. The repository pins Python 3.12 and uv acquires the matching
  interpreter for the frozen release environment.
- Node.js 18+ on PATH
- `pnpm@10.33.0` available via `corepack enable` or a direct pnpm install
- Git (optional, for fetching ComfyUI)
- Inno Setup 7 or newer for the CUDA external-payload installer. Inno 7's
  extended-length path support is required by the packaged Director dependency
  tree. The build prefers standard per-user and Program Files Inno 7 locations.

Install Inno Setup 7 per-user with:

```powershell
winget install --id JRSoftware.InnoSetup.7 -e --source winget --scope user
```

Use an Inno Setup license appropriate for your distribution; the free install
identifies builds made without a commercial license as non-commercial use only.

Recommended (for AI):

- **Ollama** installed and running.

## One-command build

Open PowerShell in repo root and run:

```powershell
./studio/edmg-studio/packaging/windows/build_all.ps1
```

The CUDA backend exceeds NSIS's 4 GiB archive limit, so `dist:win:cuda` uses
the Inno Setup external-payload installer automatically:

```powershell
cd studio/edmg-studio
pnpm run dist:win:cuda
```

For other oversized profiles, build the Inno Setup external-payload installer
directly:

```powershell
./studio/edmg-studio/packaging/windows/build_inno_external.ps1
```

From the repo-root launcher, the same path is available as:

```bat
RUN_ME.bat build-inno
```

Or open `RUN_ME.bat` normally and use **Build Inno Installer (large payload)**
in the Packaging row.

This produces:

- `studio/edmg-studio/dist-inno/EDMG-Studio-Setup-<version>.exe`
- `studio/edmg-studio/dist-inno/payload/win-unpacked.7z`

The CUDA command uses the parallel `dist-inno-cuda/` directory. The legacy
single-file CUDA NSIS attempt remains available as `dist:win:cuda:nsis` for
diagnostics, but the current locked CUDA payload is too large to succeed.

Ship the setup EXE and `payload/` directory together. The setup EXE is small
because Inno copies the large packaged app archive from the sibling payload
folder at install time instead of embedding it. Inno's native archive extractor
tracks every installed payload file for a clean uninstall, so customer machines
do not need 7-Zip. The setup EXE embeds the payload SHA-256 and rejects a missing
or modified archive. The build machine still needs 7-Zip to create the archive.

Outputs:

- `studio/edmg-studio/dist/` (final electron-builder output: installer + unpacked app)
- `studio/edmg-studio/release/staged-app/` (intermediate staged app passed to electron-builder)

The packaged desktop version comes from `studio/edmg-studio/package.json#version`.
`build_all.ps1` runs `pnpm run check:tooling` before `dist:win` so lockfile and
version metadata drift is caught before packaging. The default Windows build
uses the mutually exclusive `directml` profile. Use `pnpm run dist:win:cpu`,
`pnpm run dist:win:directml`, or `pnpm run dist:win:cuda` when selecting an
explicit release profile. Release packaging uses isolated profile-specific uv
environments under `release/uv-environments/`, so a running development backend
cannot replace CUDA dependencies during a build.

## What gets bundled

- Electron UI
- Python backend compiled into `edmg-studio-backend.exe` from `uv.lock`
- A place to drop runtime deps:
  - `studio/edmg-studio/electron-resources/bin/ffmpeg.exe`
  - `studio/edmg-studio/electron-resources/backend/edmg-studio-backend.exe`

The staged backend manifest records Python/uv/PyInstaller versions, the lock
SHA-256, accelerator profile, resolved Torch packages/index, source fingerprint,
and binary hash. Release evidence (SBOM + checksum manifests) is written to
`studio/edmg-studio/release/evidence/` during `prepare-release-bundle` and after
installer builds. Installed applications run the executable directly and do not
require Python or uv on the customer machine.

## Release evidence and smoke

- SBOM: `release/evidence/python-backend-<profile>.cyclonedx.json`
- Bundle checksums: `release/evidence/bundle-artifacts.sha256.json`
- Installer checksums: `release/evidence/release-artifacts.sha256.json`
- Signing hook stub: `packaging/windows/sign_release.ps1` (`EDMG_CODE_SIGN_CERT`)
- Clean-machine smoke: `packaging/windows/smoke_clean_machine.ps1`

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
