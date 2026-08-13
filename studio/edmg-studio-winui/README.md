# EDMG Studio — native Windows client

This directory contains the packaged WinUI 3 migration of EDMG Studio. It is a parallel client over the existing FastAPI backend; the established Electron/React client remains available while native screens are migrated and verified one workflow at a time.

## Current milestone

The first usable native workflow is implemented:

- Windows 11-style `NavigationView`, Mica title bar, light/dark theme integration, keyboard navigation, and accessible headings.
- Dashboard with live backend, project, runtime, storage, and AI-provider status.
- Projects library with empty, loading, error, refresh, create, and open states.
- Workspace with a native Windows audio picker and the authoritative create → upload → analyze/transcribe → plan-variants flow.
- Setup Wizard with runtime readiness, storage locations, safe cache fallback reporting, backend connection details, and Credential Locker token storage.
- Source, packaged, external, and healthy-source-attachment backend modes.
- Managed-process containment with a Windows Job Object, owned-process-tree shutdown, strict `2xx + {"ok":true}` health checks, listener ownership checks, retry isolation, cancelable startup, and crash status propagation.
- Runtime configuration compatibility with `runtime-defaults.json`, source `launcher_env.json`, `%APPDATA%\EDMG Studio\bootstrap.json`, and process-environment precedence.
- Native EDMG Studio branding: the canonical logo, atmospheric Studio and Workspace artwork, teal theme resources, branded package tiles, splash screen, and executable icon.

## Brand assets

The WinUI client treats the Electron product artwork as the canonical source. Regenerate the checked-in native package and in-app assets after changing that artwork:

```powershell
.\scripts\Generate-BrandAssets.ps1
```

The generator validates every output path before writing, copies the canonical logo/backgrounds into `Assets\Brand`, creates the scale-qualified MSIX graphics, and installs the existing multi-resolution EDMG Windows icon. The XAML theme provides distinct dark, light, and high-contrast resources; decorative artwork is disabled automatically in high-contrast mode.
- Canonical cache/storage environment mapping and persisted AI-provider environment mapping.

Timeline, Render, Render Queue, Review, Outputs, EDMG Director, AI Planner Lab, Reactive Lab, Cloud, Models, and Settings are present in the native navigation but intentionally open clear migration-status pages. They are not represented as complete native functionality yet.

## Architecture

```text
EdmgStudio.WinUI (WinUI 3 / MSIX)
    ├── native pages and Windows integrations
    └── EdmgStudio.Core
          ├── backend configuration and lifecycle
          ├── typed Studio HTTP client
          └── project/workflow models
                    │
                    ▼
Existing edmg_studio_backend (FastAPI / Python 3.12)
```

The native client does not duplicate the AI, audio-analysis, render, model, or project-storage engines. Both desktop clients use the same backend and project format.

## Prerequisites

- Windows 10 version 1809 or newer; Windows 11 is the primary experience.
- Visual Studio with the WinUI application development workload.
- .NET SDK selected by [`global.json`](global.json).
- The WinUI C# templates (`Microsoft.WindowsAppSDK.WinUI.CSharp.Templates`) when creating or regenerating projects.
- For source-managed backend startup, the repository's pinned `uv` toolchain and Python 3.12 environment.

Microsoft's current WinUI quick start describes the required Visual Studio workload, developer mode, and packaged project setup: <https://learn.microsoft.com/windows/apps/winui/winui3/create-your-first-winui3-app>.

## Build and test

Run these commands from this directory in PowerShell:

```powershell
dotnet restore .\EdmgStudio.WinUI.csproj -r win-x64
dotnet build .\EdmgStudio.WinUI.csproj -p:Platform=x64 -p:Configuration=Debug
dotnet test .\tests\EdmgStudio.Core.Tests\EdmgStudio.Core.Tests.csproj
```

The whole solution can also be compiled with:

```powershell
dotnet build .\EdmgStudio.WinUI.slnx
```

The focused backend data-freshness tests live in the existing Python test suite and should be run with the repository's frozen backend environment.

## Run with package identity

The default development route retains package identity so Credential Locker, MSIX behavior, and Windows integrations are exercised:

```powershell
dotnet run --project .\EdmgStudio.WinUI.csproj `
  --launch-profile "EdmgStudio.WinUI (Package)" `
  -p:Platform=x64
```

For a deterministic source-development launch against an existing local backend on port 7863:

```powershell
$env:EDMG_STUDIO_BACKEND_MODE = "managed"
$env:EDMG_STUDIO_BACKEND_HOST = "127.0.0.1"
$env:EDMG_STUDIO_BACKEND_PORT = "7863"
$env:EDMG_STUDIO_SPAWN_BACKEND = "1"
dotnet run --project .\EdmgStudio.WinUI.csproj `
  --launch-profile "EdmgStudio.WinUI (Package)" `
  -p:Platform=x64
```

Managed source mode attaches to an already healthy Studio backend. It never terminates that attached process. A backend spawned by the native client is placed in its own kill-on-close Job Object and is stopped with the client.

## Storage and configuration compatibility

Configuration precedence is:

```text
runtime defaults
  < source launcher_env.json
  < %APPDATA%\EDMG Studio\bootstrap.json
  < process environment
  < non-secret diagnostic command-line overrides
```

The explicitly selected Studio home, project data, models, cache, logs, and external-tools paths are preserved. If only a legacy data directory is configured, Studio home is derived from its parent. If the selected cache is unavailable, only cache-derived paths move to `%LOCALAPPDATA%\EDMG Studio\cache-fallback`; project data and models are not silently relocated.

If the shared bootstrap contains `pendingMigration`, managed backend startup stops with a migration-required status. Use the existing Studio client to complete that established migration workflow before retrying the native client. This avoids presenting empty target directories while data still resides at the source location.

Packaged activation does not inherit temporary environment changes from its launcher. For a diagnostic package launch without editing shared settings, use `winapp run` with non-secret arguments such as `--backend-mode managed --backend-host 127.0.0.1 --backend-port 7863 --spawn-backend true`. Backend tokens are deliberately excluded from command-line parsing; use Credential Locker or the backend-token environment contract instead.

## Project freshness rules

The shared backend now treats active workflow state as a dependency chain:

```text
new audio → invalidate active analysis and plan
new analysis → invalidate active plan
new plan → becomes the active variant source
```

Authored Timeline data, Visual DNA, imported lab state, outputs, jobs, and render history are preserved. Before native Render becomes functional, the remaining downstream conductor/performer caches need explicit revision provenance rather than broad deletion.

## Packaging and release boundary

This is a packaged MSIX project, but it is not a Store-submission artifact yet.

- `Package.appxmanifest` currently uses a development identity and publisher placeholder. Replace both with the exact Partner Center identity and publisher values before Store packaging.
- The production backend is a complete validated PyInstaller `onedir` payload, not a standalone executable. It belongs under the installed app's `resources\backend` directory and must pass the repository's existing release-manifest/hash gate before packaging.
- Do not commit or copy the current multi-gigabyte generated backend bundle into this source directory.
- Store signing, final product icons, installer upgrade tests, clean-machine proof, and customer-flow release validation remain separate release gates.

The Electron client should not be removed until every native destination has feature parity and the packaged customer workflow has passed those release gates.
