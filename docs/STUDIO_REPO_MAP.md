# EDMG Studio Repo Map

This repo contains one primary Studio product, two desktop clients, and several
compatibility surfaces.

## Canonical product

The authoritative Studio runtime architecture is:

1. Primary Windows frontend in `studio/edmg-studio-winui/` (WinUI 3/MSIX)
2. Linux and compatibility frontend in `studio/edmg-studio/` (Electron/React)
3. Shared FastAPI backend in `studio/edmg-studio/python_backend/`
4. Shared project/storage contracts and bearer-authenticated localhost API
5. Electron launcher/runtime glue in `studio/edmg-studio/tools/launcher_gui.py`
6. Established packaging and release validation under `studio/edmg-studio/scripts/`,
   `studio/edmg-studio/packaging/windows/`,
   `studio/edmg-studio/packaging/linux/`, and
   `docs/STUDIO_RELEASE_RUNBOOK.md`

Python remains authoritative for analysis, AI/provider access, CUDA/TensorRT
inference, rendering, jobs, outputs, and model lifecycle. The native client is
not a second rendering engine.

Canonical launch path from the repo root:

- `RUN_ME.bat`
- `./run_me.sh`

`RUN_ME.bat` defaults to packaged WinUI. Pass `electron` or `compat` for the
Electron client. Linux continues to use the Electron launcher.

## Internal support surfaces

These are still part of the Studio product, but they are support tooling rather
than separate end-user products:

- `studio/edmg-studio/scripts/`
- `studio/edmg-studio/tools/edmgctl/`
- `studio/edmg-studio/packaging/windows/`
- `studio/edmg-studio/packaging/linux/`

## Secondary compatibility surfaces

These remain supported for engine-specific or legacy workflows, but they are not
the primary desktop product:

- `start.bat`
- `start.sh`
- `install.ps1`
- `install.sh`
- `bootstrap_all.py`
- `installer_gui.py`
- `setup.py`

Treat them as standalone-engine and integration tooling around the broader EDMG
codebase, not as equal alternatives to Studio.

## Legacy/reference surfaces

These are useful for reference, migration, or archived workflows:

- `desktop/electron/`
- `examples/archive-ui/`
- `juce_example/`

The old standalone web UI prototypes are no longer part of the active product
surface. Their planning and audio-reactive capabilities now live in Studio
workbenches such as:

- `studio/edmg-studio/src/workbenches/AiNlpWorkbench.tsx`
- `studio/edmg-studio/src/workbenches/AudioReactiveWorkbench.tsx`

## Release and validation

Use these for the Studio product:

- [README.md](../README.md)
- [README_STUDIO.md](../README_STUDIO.md)
- [studio/edmg-studio-winui/README.md](../studio/edmg-studio-winui/README.md)
- [studio/edmg-studio/README.md](../studio/edmg-studio/README.md)
- [RELEASE.md](../RELEASE.md)
- [docs/STUDIO_RELEASE_RUNBOOK.md](./STUDIO_RELEASE_RUNBOOK.md)

Key validation commands:

- `studio/edmg-studio-winui/`:
  `dotnet build .\EdmgStudio.WinUI.csproj -p:Platform=x64 -p:Configuration=Debug`
- `studio/edmg-studio-winui/`:
  `dotnet test .\tests\EdmgStudio.Core.Tests\EdmgStudio.Core.Tests.csproj -p:Platform=x64`
- Repo root:
  `uv run --project studio/edmg-studio/python_backend --frozen --extra cpu --extra core --extra audio --group test python scripts/run_pytest_scopes.py`
- `studio/edmg-studio/`:
  `pnpm run check:tooling`
- `studio/edmg-studio/`:
  `pnpm run validate:desktop`
- `studio/edmg-studio/`:
  `pnpm run dist:win`
- `studio/edmg-studio/`:
  `pnpm run dist:linux`
- `studio/edmg-studio/`:
  `pnpm run validate:packaged-customer-flow`
- `studio/edmg-studio/`:
  `pnpm run validate:packaged-upgrade-proof`
- `studio/edmg-studio/`:
  `pnpm run validate:release:linux`

Current Electron release-lane version source:

- `studio/edmg-studio/package.json#version`

The Electron installer lane remains the currently qualified release path. WinUI
is the primary Windows product client, but Store identity/signing, backend-bundle
integration, clean-machine MSIX, upgrade, and customer-flow evidence must be
completed before claiming a production WinUI package.
