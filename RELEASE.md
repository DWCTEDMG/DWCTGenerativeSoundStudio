# EDMG Studio Release Checklist

This is the Windows-first release checklist for the Studio product: the primary
WinUI frontend in `studio/edmg-studio-winui/`, the shared backend in
`studio/edmg-studio/`, and the established Electron compatibility/release lane.

This checklist defines procedures and acceptance gates; it is not a claim that
the current installers exist or have passed them. Release evidence is valid only
for the exact candidate produced by a successful current run.

Stable and preview promotion follows [docs/BRANCH_POLICY.md](docs/BRANCH_POLICY.md). A build from
`next` is a preview; only a protected `main` commit that passed the release gate is a stable release.

## Supported build environment

- Python `3.12` (repository `.python-version`)
- `uv` `0.11.28`
- Node.js LTS
- `pnpm@10.33.0` via `studio/edmg-studio/package.json#packageManager`
- Windows build host for `dist:win`

Packaged Studio ships a self-contained Windows App SDK WinUI package, the
Electron compatibility runtime, and the PyInstaller backend. Python and uv are
build-time requirements only; customers do not install either one.

### Frontend and packaging boundary

WinUI is the primary Windows product frontend and uses the same validated
PyInstaller backend payload over authenticated localhost HTTP. The existing
Electron frontend remains available for Linux and Windows compatibility. The
canonical Windows CUDA command stages a self-contained x64 WinUI MSIX and embeds
it in the external-payload Inno installer; the approximately 6.8 GB Electron and
CUDA/TensorRT backend tree remains the sibling payload archive. A public package
still requires production signing and publisher identity, clean-machine install,
upgrade, rollback, accessibility, customer-flow, and physical NVIDIA evidence.

Source gates for the native client, run from `studio/edmg-studio-winui/`:

```powershell
dotnet build .\EdmgStudio.WinUI.csproj -p:Platform=x64 -p:Configuration=Release
dotnet test .\tests\EdmgStudio.Core.Tests\EdmgStudio.Core.Tests.csproj -p:Platform=x64
```

Launch development builds through the packaged profile or `winapp`; never run
the generated executable directly.

Create a structurally validated local WinUI package from `studio/edmg-studio/`:

```powershell
pnpm run stage:winui:msix
```

This staging path enforces Release/x64, no MSIX bundle, no trimming, and a
self-contained Windows App SDK. Without configured signing credentials the
result is structural build evidence only and must not be distributed.

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

`dist:win:cuda` is the canonical WinUI-first CUDA distribution path. It retains
the Electron application as a clearly named compatibility shortcut while
registering WinUI as the primary Start menu and post-install application.

Every release profile is resolved exclusively from `pyproject.toml` and the
committed `uv.lock`. Environment variables that inject a package source,
requirements file, project environment, bundle extra, or Torch index are
release blockers.

## Required proof before shipping

Run the full release validation from `studio/edmg-studio/`:

```powershell
pnpm run validate:release
```

This command produces and exercises a local release candidate. Signing remains optional so that
contributors can validate the complete candidate pipeline without production credentials. For a
public Windows release, configure the signing identity described below and run the fail-closed
production gate instead:

```powershell
$env:EDMG_CODE_SIGN_CERT = "<thumbprint-or-pfx-path>"
$env:EDMG_CODE_SIGN_PASSWORD = "<optional-pfx-password>"
$env:EDMG_CODE_SIGN_TIMESTAMP_URL = "http://timestamp.digicert.com"
pnpm run validate:release:production
```

`validate:release:production` verifies the signing configuration before starting the expensive
candidate build, forces `EDMG_REQUIRE_CODE_SIGNING=1`, and then runs the same `validate:release`
pipeline. Missing or invalid credentials therefore fail before packaging begins. The default
Windows lane builds and validates the DirectML SKU. CPU and CUDA artifacts, when intended for
public distribution, require separate signed builds and their own packaged, clean-machine, and
hardware evidence; this command is not a three-profile matrix gate.

That proof covers:

- source build + staged desktop validation
- packaged customer flow
- packaged synthetic old-layout storage migration proof
- packaged zero-state setup proof with Studio-managed Ollama and 7-Zip
- backend manifest verification for Python version, uv version, lock SHA-256,
  accelerator profile, Torch packages/index, PyInstaller version, source
  fingerprint, and binary hash
- CycloneDX SBOM export from the committed `uv.lock` under
  `studio/edmg-studio/release/evidence/python-backend-<profile>.cyclonedx.json`
- SHA-256 checksum manifests for bundled and installer artifacts under
  `studio/edmg-studio/release/evidence/`

The installed-previous-version evidence lane is opt-in. Set
`EDMG_STUDIO_INSTALLED_APP_DIR` to make upgrade validation compare the separately built candidate
against an immutable installed baseline, require a strictly newer candidate version, confine every
mutable proof path outside that baseline, and recheck its hashes after cleanup. Without that
setting, the release pipeline proves the synthetic migration contract only. Even the signed
production command does not replace clean-VM, actual installed-version upgrade, named-hardware,
rollback, accessibility, or protected-branch evidence.

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

That script also runs the env-gated Authenticode signing/verification lane and the clean-machine
smoke checklist (`packaging/windows/smoke_clean_machine.ps1`).

### Code signing (credentials required)

Developer signing is optional, but production signing is fail-closed. Configure
one of a local PFX/P12 file or a SHA1 certificate-store thumbprint on the
Windows signing host:

```powershell
$env:EDMG_CODE_SIGN_CERT = "<thumbprint-or-pfx-path>"
$env:EDMG_CODE_SIGN_PASSWORD = "<optional-pfx-password>"
$env:EDMG_CODE_SIGN_TIMESTAMP_URL = "http://timestamp.digicert.com"
pnpm run validate:release:production
```

The lower-level `build_all.ps1` lane also honors `EDMG_REQUIRE_CODE_SIGNING=1`, but the production
validation command is the canonical public-release entry point because it performs credential
preflight before the candidate pipeline starts.

The packaging lane maps the custom credential variables into electron-builder
native signing, enables `forceCodeSigning`, signs EDMG-owned backend/helper
executables while copying them into the packaged app, then verifies the final
copied bytes and refreshes the embedded manifest before installer archival.
Final executables/installers are checked through both
`Get-AuthenticodeSignature` and `signtool verify`. The password is never
logged. SDK SignTool discovery is automatic; `EDMG_SIGNTOOL_PATH` is available
for nonstandard SDK installations.

Each signing/verification pass appends
`release/evidence/windows-signatures.json`. Installer checksum evidence is
generated only after final signatures, so the recorded SHA-256 values describe
the bytes that are shipped.

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
2. Choose a non-system-drive `Studio Home` on a writable volume whose free space
   has been checked for the intended models, caches, and outputs. Do not use a
   full drive.
3. Run `Full Setup`.
4. Create a project.
5. Upload audio.
6. Analyze — confirm **Workspace → Understand / Music Graph v1** shows sections, tags, and optional ASR lines.
7. Plan — generate variants and apply one to the timeline.
8. Render — select a supported diffusion, hosted, or TensorRT path, pass
   preflight, enqueue a production render, and verify progress/cancel/recovery in
   the queue. Do not use the retired proxy-render workflow.
9. **Review** — compare artifacts and record an approval decision.
10. **Workspace → Handoff** — export a template package (optional import smoke).
11. Export and verify output files.
12. **Settings → System readiness** — confirm baseline metrics budgets load (`GET /v1/metrics/baseline`)
    and Build identity reports the expected desktop/backend versions, accelerator profile, and
    packaged provenance.
13. **Models → Imports** — on a disposable copy under a non-default Studio Home, verify legacy
    TensorRT partial/unsafe and insufficient-space rejection, safe cancellation cleanup, unchanged
    source hashes, atomic canonical publication, and the engine-only bundle's explicit not-ready
    state.
14. On named CUDA hardware with a completed canonical bundle, prove dedicated TensorRT video and
    SVD/AnimateDiff TensorRT anchors receive the exact server-resolved bundle path, keep it distinct
    from base/temporal model paths, reject a filesystem path supplied as `model_id`, and complete
    render/cancel/recovery checks. Verify an older `/render/tensorrt-deforum` client request and a
    persisted `tensorrt_deforum` job both execute the same canonical video path, report
    `legacy_deforum_schedule_applied=false`, and never restore the removed simulation service.

## Documentation relaunch (partial — P5-06)

Triton model serving is not required by the 1.2.0 desktop release candidate. The locked CUDA release
profile is configured to include the in-process TensorRT runtime. A fresh signed 1.2.0 CUDA artifact,
packaged-runtime inspection, and supported-GPU model-load/render proof remain required. The separate
Triton provider remains research-only until it passes the promotion contract in
[`docs/TRITON_PROVIDER_READINESS.md`](docs/TRITON_PROVIDER_READINESS.md).

Creator-facing feature docs for the source candidate live in:

- [studio/edmg-studio/README.md](./studio/edmg-studio/README.md) — Understand, Review, Render Plan, live cues, template handoff, contract freeze
- [docs/STUDIO_RELEASE_RUNBOOK.md](docs/STUDIO_RELEASE_RUNBOOK.md) — install and recovery
- [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) — candidate blockers, limitations, and operator rules
- [docs/VISUAL_DNA_AND_RENDER_CONDUCTOR_SPEC.md](docs/VISUAL_DNA_AND_RENDER_CONDUCTOR_SPEC.md) — intelligence layer
- [docs/PYTHON_TOOLCHAIN.md](docs/PYTHON_TOOLCHAIN.md) — uv lock policy

Still open for full P5-06: dedicated architecture diagram refresh and project-format migration guide.

## API contract freeze (2026-07-21)

Beta integrators should treat `studio/edmg-studio/src/shared/api/contracts.ts` as the TypeScript source of truth for newly extracted routes (Music Graph, Render Plan GET, variant review, live assets/cues, template packages, performer plan, baseline metrics). Python response shapes in `edmg_studio_backend/api/routers.py` must stay compatible until schema versions increment.

## Release evidence summary

| Artifact | Location | Status |
|----------|----------|--------|
| CycloneDX SBOM | `release/evidence/python-backend-*.cyclonedx.json` | Generated by the evidence command; verify it belongs to the current candidate |
| SHA-256 checksums | `release/evidence/bundle-artifacts.sha256.json` and `release/evidence/release-artifacts.sha256.json` | Generated by the matching bundle/dist evidence phase; verify current artifact hashes |
| In-app build identity | Settings → System readiness | Desktop/backend versions, profile, runtime, source/binary/lock fingerprints; Git commit/dirty field still pending |
| Authenticode signatures | `release/evidence/windows-signatures.json` | Generated by the signing lane; production requires valid current entries plus `EDMG_REQUIRE_CODE_SIGNING=1` and `EDMG_CODE_SIGN_CERT` |
| Clean-machine smoke | `packaging/windows/smoke_clean_machine.ps1` | Local checklist; full VM proof still manual |
| Baseline metrics | `GET /v1/metrics/baseline` | Stub budgets; W7-04 named-hardware runs pending |

## Upgrade proof

Release is not complete unless an old layout upgrades cleanly.

Automated proof:

```powershell
cd studio/edmg-studio
pnpm run validate:packaged-upgrade-proof
```

To attach read-only evidence from an existing installed release, keep the installed baseline
separate from the newly built candidate:

```powershell
$env:EDMG_STUDIO_INSTALLED_APP_DIR='C:\Users\you\AppData\Local\Programs\EDMG Studio'
$env:EDMG_STUDIO_PACKAGED_APP='E:\path\to\candidate\win-unpacked\EDMG Studio.exe'
pnpm run validate:packaged-upgrade-proof
```

`EDMG_STUDIO_INSTALLED_APP_DIR` (or `--installed-app-dir <absolute-directory>`) identifies an
immutable previous installation for version, manifest, and SHA-256 evidence. It is never selected
as the candidate executable. The proof rejects candidate and temporary proof paths that resolve
inside the installed baseline. Do not point `EDMG_STUDIO_PACKAGED_APP` at the baseline when claiming
upgrade evidence; that would test migration with the old build rather than prove an upgrade.

Expected result:

- old `C:\`-style data migrates into the selected Studio-managed roots
- `pendingMigration` clears
- `lastMigration.ok` reports success
- migrated files exist under the new target roots
- evidence records the installed baseline version and hashes separately from the candidate
- candidate `FileVersion` is numerically greater than the installed baseline
- candidate and every mutable proof path resolve outside the installed application directory
- baseline desktop, backend, manifest, launcher-defaults, runtime-defaults, app archive, and
  installed-uninstaller hashes remain unchanged after candidate shutdown and proof cleanup

## Zero-state setup proof

Release is not complete unless a packaged app can bootstrap its own external
tooling without relying on already-installed global copies.

Automated proof:

```powershell
cd studio/edmg-studio
pnpm run validate:packaged-zero-state-setup
```

Expected result:

- packaged Studio starts with a fresh hermetic temporary Studio Home outside the installed application directory
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
