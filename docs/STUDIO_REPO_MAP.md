# EDMG Studio Repo Map

This repository now presents one product surface: EDMG Studio.

## Canonical product tree

- `studio/edmg-studio/`
  Canonical Electron desktop app.
- `studio/edmg-studio/src/`
  React/Vite frontend.
- `studio/edmg-studio/main.mjs`, `preload.cjs`, `main-process/`
  Desktop shell and runtime glue.
- `studio/edmg-studio/python_backend/`
  FastAPI backend plus the vendored EDMG engine packages.
- `tools/launcher_gui.py`
  Shared dev launcher and Studio Home bootstrap flow.
- `packaging/windows/`
  Windows-first packaged release automation.

## Canonical entrypoints

- `RUN_ME.bat`
- `./run_me.sh`

## Internal support surfaces

These are still part of the monolith, but they are support tooling rather than
separate user-facing products:

- `studio/edmg-studio/scripts/`
- `tools/edmgctl/`
- `scripts/`

Important: these support paths exist to serve the Studio product. They are not
alternative install flows.

## Legacy surfaces retired from the public repo entry

The old standalone installers, duplicate desktop shell, and extra top-level
README entrypoints have been removed. Archived or reference-only material that
still remains should be treated as implementation detail, not as competing
product surfaces.

## Release and validation

Primary Studio docs:

- [README.md](D:\DWCTGenerativeSoundStudio\README.md)
- [studio/edmg-studio/README.md](D:\DWCTGenerativeSoundStudio\studio\edmg-studio\README.md)
- [RELEASE.md](D:\DWCTGenerativeSoundStudio\RELEASE.md)
- [docs/STUDIO_RELEASE_RUNBOOK.md](D:\DWCTGenerativeSoundStudio\docs\STUDIO_RELEASE_RUNBOOK.md)

Key validation commands run from `studio/edmg-studio/`:

- `npm run validate:desktop`
- `npm run dist:win`
- `npm run validate:packaged-customer-flow`
- `npm run validate:packaged-upgrade-proof`
