# EDMG Studio Release Checklist

This is the Windows-first release checklist for the canonical Studio product in
`studio/edmg-studio/`.

## Supported build environment

- Python `>=3.10,<3.14`
- Node.js LTS
- Windows build host for `dist:win`

Packaged Studio ships its own Electron runtime. Python is only a build-time
requirement for source builds, backend bundling, and release packaging.

## Canonical repo hygiene

- `studio/edmg-studio/` is the primary product surface.
- `DWCTGenerativeSoundStudio-main/` is treated as duplicate local noise and is
  ignored. Do not import it into the canonical repo.
- Release branches should be clean before packaging:

```powershell
git status --short
```

## Release build

From the repo root:

```powershell
./packaging/windows/build_all.ps1
```

That script now:

- checks the supported Python version range
- rebuilds the packaged backend bundle
- stages bundled FFmpeg
- installs UI dependencies
- runs the Windows installer build

Primary artifact output:

- `studio/edmg-studio/dist/`

## Required proof before shipping

Run the full release validation from `studio/edmg-studio/`:

```powershell
npm run validate:release
```

That proof covers:

- source build + staged desktop validation
- packaged customer flow
- packaged upgrade and storage migration proof
- packaged zero-state setup proof with Studio-managed Ollama and 7-Zip

Optional support-plane helper:

```powershell
cd tools/edmgctl
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl doctor
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl release status
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl support export --out D:\Tools\edmg-support.zip
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
npm run validate:packaged-upgrade-proof
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
npm run validate:packaged-zero-state-setup
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

- the build uses Python `>=3.10,<3.14`
- `npm run validate:release` passes
- the packaged app reports healthy setup status
- the packaged customer flow and upgrade proof both pass

Treat missing core modules or Python-version-specific packaging regressions as
release blockers.

## Operator docs

Use the Studio runbook for install and recovery:

- [docs/STUDIO_RELEASE_RUNBOOK.md](docs/STUDIO_RELEASE_RUNBOOK.md)
- [docs/AI_PROVIDERS.md](docs/AI_PROVIDERS.md)
