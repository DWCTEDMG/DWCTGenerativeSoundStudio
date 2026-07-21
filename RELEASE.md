# EDMG Studio Release Checklist

This is the Windows-first release checklist for the canonical Studio product in
`studio/edmg-studio/`.

## Supported build environment

- Python `3.12` (repository `.python-version`)
- `uv` `0.11.28`
- Node.js LTS
- `pnpm@10.33.0` via `studio/edmg-studio/package.json#packageManager`
- Windows build host for `dist:win`

Packaged Studio ships its own Electron runtime and PyInstaller backend. Python
and uv are build-time requirements only; customers do not install either one.

## Canonical repo hygiene

- `studio/edmg-studio/` is the primary product surface.
- `studio/edmg-studio/` is also the canonical JS/pnpm root. Do not add a competing root `package.json` or alternate JS lockfile elsewhere in the repo.
- `DWCTGenerativeSoundStudio-main/` is treated as duplicate local noise and is
  ignored. Do not import it into the canonical repo.
- Release branches should be clean before packaging:

```powershell
git status --short
```

## Release build

Canonical desktop version source:

- `studio/edmg-studio/package.json#version`

The staging/release flow copies that version into `release/staged-app/package.json`
and electron-builder uses it for installer naming.

From the repo root:

```powershell
./studio/edmg-studio/packaging/windows/build_all.ps1
```

That script now:

- checks the pinned uv release and Python 3.12 project metadata
- checks `uv.lock`, performs a frozen DirectML-profile sync, and rebuilds the
  packaged backend bundle through uv
- stages bundled FFmpeg
- installs UI dependencies
- validates pnpm/lockfile/release metadata expectations
- runs the Windows installer build

Primary artifact output:

- `studio/edmg-studio/dist/`

The Windows default is DirectML. Explicit profile builds are also available
from `studio/edmg-studio/`:

```powershell
pnpm run dist:win:cpu
pnpm run dist:win:directml
pnpm run dist:win:cuda
```

Every release profile is resolved exclusively from `pyproject.toml` and the
committed `uv.lock`. Environment variables that inject a package source,
requirements file, project environment, bundle extra, or Torch index are
release blockers.

## Required proof before shipping

Run the full release validation from `studio/edmg-studio/`:

```powershell
pnpm run validate:release
```

That proof covers:

- source build + staged desktop validation
- packaged customer flow
- packaged upgrade and storage migration proof
- packaged zero-state setup proof with Studio-managed Ollama and 7-Zip
- backend manifest verification for Python version, uv version, lock SHA-256,
  accelerator profile, Torch packages/index, PyInstaller version, source
  fingerprint, and binary hash
- CycloneDX SBOM export from the committed `uv.lock` under
  `studio/edmg-studio/release/evidence/python-backend-<profile>.cyclonedx.json`
- SHA-256 checksum manifests for bundled and installer artifacts under
  `studio/edmg-studio/release/evidence/`

Generate or refresh release evidence manually:

```powershell
cd studio/edmg-studio
pnpm run generate:release-evidence
pnpm run generate:release-evidence:dist
```

After a full Windows build:

```powershell
./studio/edmg-studio/packaging/windows/build_all.ps1
```

That script now also runs the env-gated signing hook stub and the clean-machine
smoke checklist (`packaging/windows/smoke_clean_machine.ps1`).

### Code signing (credentials required)

Signing is optional and env-gated. Configure on a signing host:

```powershell
$env:EDMG_CODE_SIGN_CERT = "<thumbprint-or-pfx-path>"
$env:EDMG_CODE_SIGN_PASSWORD = "<optional-pfx-password>"
./studio/edmg-studio/packaging/windows/sign_release.ps1
```

The repository ships a stub hook only. Replace `sign_release.ps1` with real
`signtool.exe` invocations once signing credentials are available.

### Clean-machine smoke

Automated local checklist (staged launch probe + evidence files):

```powershell
./studio/edmg-studio/packaging/windows/smoke_clean_machine.ps1
```

Use `-SkipLaunchProbe` to validate artifact/checksum presence without launching
Electron. Full clean-VM acceptance still requires installing the packaged
installer on a machine without dev tooling.

Optional support-plane helper:

```powershell
cd studio/edmg-studio/tools/edmgctl
go run ./cmd/edmgctl doctor
go run ./cmd/edmgctl release status
go run ./cmd/edmgctl support export --out .\edmg-support.zip
```

That Go CLI is intentionally read-only for diagnostics unless you explicitly run
its `release build` or `release validate` wrappers.

Minimum manual acceptance pass after automation:

1. Install the packaged app with the assisted installer.
2. Choose a non-`C:\` `Studio Home` such as `D:\EDMG-Studio`.
3. Run `Full Setup`.
4. Create a project.
5. Upload audio.
6. Analyze.
7. Plan.
8. Render.
9. Export and verify output files.

## Upgrade proof

Release is not complete unless an old layout upgrades cleanly.

Automated proof:

```powershell
cd studio/edmg-studio
pnpm run validate:packaged-upgrade-proof
```

Expected result:

- old `C:\`-style data migrates into the selected Studio-managed roots
- `pendingMigration` clears
- `lastMigration.ok` reports success
- migrated files exist under the new target roots

## Zero-state setup proof

Release is not complete unless a packaged app can bootstrap its own external
tooling without relying on already-installed global copies.

Automated proof:

```powershell
cd studio/edmg-studio
pnpm run validate:packaged-zero-state-setup
```

Expected result:

- packaged Studio starts with a fresh `D:\...` Studio Home
- managed 7-Zip is downloaded under `external\bin`
- managed Ollama is installed under `external\ollama`
- managed Ollama runs on the proof port and pulls the requested model
- ComfyUI Portable installs under the Studio-managed external root

## Packaging warnings policy

PyInstaller may still report optional-import noise from libraries such as:

- diffusers / transformers / torch integrations
- websocket/cloud SDK adapters
- optional spaCy ecosystem extras

Those warnings are acceptable only when all of the following are true:

- the build uses Python 3.12, uv 0.11.28, and `uv sync --frozen`
- `pnpm run validate:release` passes
- the packaged app reports healthy setup status
- the packaged customer flow and upgrade proof both pass

Treat missing core modules or Python-version-specific packaging regressions as
release blockers.

## Operator docs

Use the Studio runbook for install and recovery:

- [docs/STUDIO_RELEASE_RUNBOOK.md](docs/STUDIO_RELEASE_RUNBOOK.md)
- [docs/AI_PROVIDERS.md](docs/AI_PROVIDERS.md)
- [docs/PYTHON_TOOLCHAIN.md](docs/PYTHON_TOOLCHAIN.md)
