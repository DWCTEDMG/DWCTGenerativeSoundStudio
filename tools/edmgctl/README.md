# `edmgctl`

`edmgctl` is the first Go support-plane addition for EDMG Studio.

It does not replace any Python ML/audio logic or the Electron/React UI. It
wraps the existing Studio release and diagnostics surface with a small,
cross-platform CLI that can:

- inspect repo/tool/bootstrap state
- report supervisor state inside the doctor surface
- validate Studio-managed storage roots
- inspect packaged release artifacts
- export a single support bundle zip for release/debug handoff
- run the existing release build and release proof commands

## Why this is the first Go insertion point

This repo already has working Python and TypeScript product code. The
lowest-risk place for Go is around operations and tooling:

- no rewrite of the audio or ML path
- no rewrite of the UI
- no new runtime dependency inside the core Studio app
- immediate value for diagnostics, release checks, and support workflows

## Commands

From `tools/edmgctl/`:

```powershell
$env:GOCACHE='D:\Tools\GoCache'
$env:GOMODCACHE='D:\Tools\GoPkg'
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl doctor
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl bootstrap show
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl release status
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl artifact list --hashes
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl support export --out D:\Tools\edmg-support.zip
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl supervisor start --port 0 --wait --timeout 90s
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl supervisor status
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl supervisor stop
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl release verify-manifest --manifest D:\Tools\edmg-artifacts.json
```

Machine-readable output:

```powershell
$env:GOCACHE='D:\Tools\GoCache'
$env:GOMODCACHE='D:\Tools\GoPkg'
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl doctor --json
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl artifact manifest --out D:\Tools\edmg-artifacts.json
```

Release wrappers:

```powershell
$env:GOCACHE='D:\Tools\GoCache'
$env:GOMODCACHE='D:\Tools\GoPkg'
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl release build
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl release validate
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl release verify-manifest --manifest D:\Tools\edmg-artifacts.json
```

## Build

```powershell
cd D:\DWCTGenerativeSoundStudio\tools\edmgctl
$env:GOCACHE='D:\Tools\GoCache'
$env:GOMODCACHE='D:\Tools\GoPkg'
D:\Tools\Go\bin\go.exe build -o D:\Tools\edmgctl.exe ./cmd/edmgctl
```

Then run:

```powershell
D:\Tools\edmgctl.exe doctor
```

## Integration points

`edmgctl` intentionally integrates with the existing repo instead of replacing
it.

It reads:

- `studio/edmg-studio/package.json`
- `studio/edmg-studio/electron-resources/backend/backend-bundle-manifest.json`
- the user bootstrap config at `%APPDATA%\EDMG Studio\bootstrap.json` on Windows

It executes:

- `npm run dist:win`
- `npm run validate:release`

It also inventories:

- bundled backend executable
- bundled FFmpeg
- unpacked packaged app
- Windows installer artifact

It can also supervise one packaged backend process for support and proof work:

- start the packaged backend with the same Studio-managed storage roots
- ping `/health`
- stop the managed backend

It can also export one portable support bundle zip containing:

- `doctor.json`
- bootstrap report and raw bootstrap config when present
- supervisor status and raw supervisor state when present
- the current artifact manifest with hashes
- release-proof pointers and a small bundle README

So the current Python backend, Electron main process, React UI, and packaging
scripts remain the source of truth. Go is only the orchestration/diagnostic
surface.

## Cross-platform notes

- `doctor`, `bootstrap show`, and `release status` are cross-platform.
- `release build` is still Windows-first because the underlying product release
  flow is Windows-first.
- `release validate` delegates to the existing Studio scripts and behaves the
  same way those scripts behave on the current host.
