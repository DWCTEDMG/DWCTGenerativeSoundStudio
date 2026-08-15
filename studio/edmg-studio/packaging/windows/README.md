# Windows Release Build (Installer-grade)

This folder contains the **WinUI-first** Windows packaging pipeline. It produces
a packaged x64 WinUI primary frontend over the authenticated localhost FastAPI
backend and retains Electron as an explicit compatibility frontend.

## Prereqs

- Windows 10/11 x64
- `uv` 0.11.28. The repository pins Python 3.12 and uv acquires the matching
  interpreter for the frozen release environment.
- Node.js 20.19+ or 22.12+ on PATH (Node 22 LTS recommended)
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

That command builds the Electron/CUDA compatibility tree, stages a
self-contained Windows App SDK WinUI MSIX, and builds the Inno wrapper. To
validate only the WinUI package without recompressing the large payload:

```powershell
pnpm run stage:winui:msix
```

An unsigned staged MSIX proves package structure only. It is not a releasable
installer and the installation manager rejects it.

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

- `studio/edmg-studio/dist-inno/EDMG-Studio-<version>-windows-x64-<profile>-Setup.exe`
- `studio/edmg-studio/dist-inno/payload/win-unpacked.7z`
- `studio/edmg-studio/dist-inno/payload/payload-integrity.json`
- `studio/edmg-studio/release/winui-msix/<identity>_<version>_x64.msix`
- `studio/edmg-studio/release/winui-msix/winui-msix.json`

The CUDA command uses the parallel `dist-inno-cuda/` directory and names its
installer `EDMG-Studio-<version>-windows-x64-cuda-Setup.exe`. The legacy
single-file CUDA NSIS attempt remains available as `dist:win:cuda:nsis` for
diagnostics, but the current locked CUDA payload is too large to succeed.

Ship the setup EXE and `payload/` directory together. The setup EXE is small
because it embeds only the WinUI MSIX and its registration helper; Inno copies
the large Electron/CUDA packaged app archive from the sibling payload folder at
install time instead of embedding it. Inno's native archive extractor
tracks every installed payload file for a clean uninstall, so customer machines
do not need 7-Zip. The setup EXE embeds the payload SHA-256 and rejects a missing
or modified archive. The integrity sidecar binds that archive hash to the exact
desktop version, accelerator profile, desktop executable, final backend
manifest, and backend binary. The archive is always rebuilt from the current
`dist/win-unpacked` tree; release packaging has no stale-payload reuse switch.
The build machine still needs 7-Zip to create the archive.

Outputs:

- `studio/edmg-studio/dist/` (final electron-builder output: profile-qualified installer + unpacked app)
- `studio/edmg-studio/release/staged-app/` (intermediate staged app passed to electron-builder)

Windows NSIS installers use
`EDMG-Studio-<version>-windows-x64-<profile>-Setup.exe`, where `<profile>` is
the immutable packaged backend profile: `cpu`, `directml`, or `cuda`. This
keeps installers for mutually exclusive runtimes from overwriting or being
mistaken for one another.

The packaged desktop version comes from `studio/edmg-studio/package.json#version`.
`build_all.ps1` runs `pnpm run check:tooling` before `dist:win` so lockfile and
version metadata drift is caught before packaging. The default Windows build
uses the mutually exclusive `directml` profile. Use `pnpm run dist:win:cpu`,
`pnpm run dist:win:directml`, or `pnpm run dist:win:cuda` when selecting an
explicit release profile. Release packaging uses isolated profile-specific uv
environments under `release/uv-environments/`, so a running development backend
cannot replace CUDA dependencies during a build.

## What gets bundled

- self-contained Windows App SDK WinUI MSIX as the primary Windows frontend
- WinUI package registration, dynamic AppsFolder launch, rollback, and uninstall helper
- Electron UI as the Linux and Windows compatibility frontend
- Python backend compiled into `edmg-studio-backend.exe` from `uv.lock`
- Checksum-verified, pinned media tools:
  - `studio/edmg-studio/electron-resources/bin/ffmpeg.exe`
  - `studio/edmg-studio/electron-resources/bin/ffprobe.exe`
- `studio/edmg-studio/electron-resources/backend/edmg-studio-backend.exe`

`prepare-electron-build.mjs` obtains FFmpeg and FFprobe from the immutable archive
recorded in `packaging/media-tools-assets.json`; it never copies an arbitrary
PATH installation or downloads a moving `latest` build. The verified archive is
reused from `.cache/media-tools/` by default. Set
`EDMG_STUDIO_BUILD_CACHE_ROOT` to put that cache on another build volume.

The same archive's GPLv3 `LICENSE.txt` is copied byte-for-byte into the package
as `electron-resources/bin/FFmpeg-LICENSE.txt`. A deterministic
`FFmpeg-SOURCE.txt` beside it records the exact FFmpeg source commit, BtbN build
source commit, release tag, archive name, size, and SHA-256. Packaging fails
closed if the archive license is missing, ambiguous, or not the expected GPLv3
text; the packaged-desktop smoke inventory requires both evidence files.

The staged backend manifest records Python/uv/PyInstaller versions, the lock
SHA-256, accelerator profile, resolved Torch packages/index, source fingerprint,
and binary hash. On Windows, Electron Builder signs the backend and helper while
copying them into the packaged application. Its `afterPack` gate then verifies
the configured signer, regenerates the packaged manifest from those exact final
PE bytes, and fully revalidates it before NSIS or Inno can archive them. Unsigned local QA
builds retain an explicit `unsigned-local` manifest state and cannot be promoted
through the fail-closed production gate. Release evidence (SBOM + checksum manifests) is written to
`studio/edmg-studio/release/evidence/` during `prepare-release-bundle` and after
installer builds. Installed WinUI applications launch through their registered package identity;
the compatibility frontend and backend use their installed executables.
Customer machines do not require Python, uv, or a separate Windows App Runtime
framework package.

## Release evidence and smoke

- SBOM: `release/evidence/python-backend-<profile>.cyclonedx.json`
- Bundle checksums: `release/evidence/bundle-artifacts.sha256.json`
- Installer checksums: `release/evidence/release-artifacts.sha256.json`
- Authenticode evidence: `release/evidence/windows-signatures.json`
- Signing/verification lane: `packaging/windows/sign_release.ps1`
- Clean-machine smoke: `packaging/windows/smoke_clean_machine.ps1`

## Authenticode signing

Release signing supports either a local PFX/P12 file or the SHA1 thumbprint of
a valid Code Signing certificate with a private key in the Windows
`CurrentUser\My` or `LocalMachine\My` store:

```powershell
$env:EDMG_CODE_SIGN_CERT = "C:\secure\edmg-release.pfx" # or 40-character SHA1 thumbprint
$env:EDMG_CODE_SIGN_PASSWORD = "<pfx-password>"         # PFX only; never committed
$env:EDMG_CODE_SIGN_TIMESTAMP_URL = "http://timestamp.digicert.com"
$env:EDMG_REQUIRE_CODE_SIGNING = "1"
./studio/edmg-studio/packaging/windows/build_all.ps1
```

`EDMG_REQUIRE_CODE_SIGNING=1` is the production fail-closed switch. It makes
packaging fail before unsigned EDMG-owned executables can be archived and also
sets electron-builder `forceCodeSigning`. The custom certificate variables are
mapped into electron-builder's native Windows signing configuration, while the
PowerShell lane verifies the copied backend/helper, application, and installer
with both `Get-AuthenticodeSignature` and `signtool verify`; application MSIX
packages are verified with the `/pa` policy. A
valid signature from a different certificate is rejected; the signer thumbprint
must match the configured release certificate.

The oversized Inno lane supplies this same fail-closed signer to the Inno
compiler. In production, Inno signs both Setup and its generated uninstaller;
the outer Setup is verified again after compilation. Signing only the finished
Setup after compilation is not sufficient because it would leave the installed
`unins000.exe` unsigned.

`signtool.exe` is discovered from `PATH` or installed Windows SDK directories.
Set `EDMG_SIGNTOOL_PATH` only when using a nonstandard SDK layout. Signature
evidence is appended to `release/evidence/windows-signatures.json`; installer
checksum evidence is generated afterward so it describes the signed bytes.

Without `EDMG_REQUIRE_CODE_SIGNING`, developer builds may remain unsigned, but
the signing evidence records those artifacts as skipped. Never distribute that
state as a production release.

The remaining release gates are intentionally external: qualify the production
publisher/signing identity, test install/upgrade/rollback/uninstall on a clean
supported Windows machine, and run CUDA/TensorRT acceptance on physical NVIDIA
hardware. Source-only or unsigned structural validation does not satisfy them.

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
