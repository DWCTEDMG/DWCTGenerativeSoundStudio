# EDMG Studio Monolith Repo

This repository is the single authoritative source tree for EDMG Studio.

Studio is not a sidecar anymore. The desktop shell, React frontend, FastAPI
backend, vendored EDMG engine packages, setup flow, release packaging, and
support tooling all converge on one product path:

- `studio/edmg-studio/`

The older standalone-engine installers, duplicate Electron shell, and extra
README entrypoints have been retired so the repo presents one product instead
of multiple competing workflows.

## Canonical launch

Windows:

```bat
RUN_ME.bat
```

macOS/Linux:

```bash
./run_me.sh
```

Those launchers open the Studio dev launcher in `studio/edmg-studio/tools/launcher_gui.py`, which
keeps the UI, backend, and `Studio Home` storage aligned with the same settings
used by the packaged app.

## Canonical product layout

- `studio/edmg-studio/`
  Electron shell, preload, main-process runtime, React/Vite frontend, packaging
  scripts, and release validation.
- `studio/edmg-studio/python_backend/`
  FastAPI backend plus the vendored `enhanced_deforum_music_generator` and
  `deforum_music` engine packages that power planning, analysis, schedules, and
  EDMG Core support.
- `studio/edmg-studio/tools/launcher_gui.py`
  Shared dev launcher and Studio Home bootstrap flow.
- `studio/edmg-studio/packaging/windows/`
  Windows-first release orchestration for the packaged Studio app.

## Studio Home

Studio separates the app install directory from the heavy runtime storage root.
The `Studio Home` contains:

- `data`
- `models`
- `cache`
- `logs`
- `external`
- `electron`

That keeps large downloads, render caches, and external tools off the app
install path and allows migration to another drive such as `D:\`.

## Release and operator docs

- [studio/edmg-studio/README.md](D:\DWCTGenerativeSoundStudio\studio\edmg-studio\README.md)
- [RELEASE.md](D:\DWCTGenerativeSoundStudio\RELEASE.md)
- [docs/STUDIO_RELEASE_RUNBOOK.md](D:\DWCTGenerativeSoundStudio\docs\STUDIO_RELEASE_RUNBOOK.md)
- [docs/STUDIO_REPO_MAP.md](D:\DWCTGenerativeSoundStudio\docs\STUDIO_REPO_MAP.md)

## Compatibility note

The repo root now keeps only thin launch aliases and monolith-level docs. The
runtime code, packaging logic, backend engine packages, and operator tooling
live under `studio/edmg-studio/`.
