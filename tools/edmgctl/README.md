# `edmgctl`

`edmgctl` is the first Go support-plane addition for EDMG Studio.

It does not replace any Python ML/audio logic or the Electron/React UI. It
wraps the existing Studio release and diagnostics surface with a small,
cross-platform CLI that can:

- inspect repo/tool/bootstrap state
- validate Studio-managed storage roots
- inspect packaged release artifacts
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
```

Machine-readable output:

```powershell
$env:GOCACHE='D:\Tools\GoCache'
$env:GOMODCACHE='D:\Tools\GoPkg'
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl doctor --json
```

Release wrappers:

```powershell
$env:GOCACHE='D:\Tools\GoCache'
$env:GOMODCACHE='D:\Tools\GoPkg'
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl release build
D:\Tools\Go\bin\go.exe run ./cmd/edmgctl release validate
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

So the current Python backend, Electron main process, React UI, and packaging
scripts remain the source of truth. Go is only the orchestration/diagnostic
surface.

## Cross-platform notes

- `doctor`, `bootstrap show`, and `release status` are cross-platform.
- `release build` is still Windows-first because the underlying product release
  flow is Windows-first.
- `release validate` delegates to the existing Studio scripts and behaves the
  same way those scripts behave on the current host.
