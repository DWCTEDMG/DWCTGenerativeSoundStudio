# EDMG Studio Repo Map

This repo contains one primary product and several compatibility surfaces.

## Canonical product

The authoritative desktop product is:

- `studio/edmg-studio/`

Its canonical launch path from the repo root is:

- `RUN_ME.bat`
- `./run_me.sh`

Its canonical runtime architecture is:

1. Electron shell and preload in `studio/edmg-studio/`
2. React/Vite frontend in `studio/edmg-studio/src/`
3. FastAPI backend in `studio/edmg-studio/python_backend/`
4. Shared launcher/runtime glue in `tools/launcher_gui.py`
5. Windows packaging and release validation under `studio/edmg-studio/scripts/`, `packaging/windows/`, and `docs/STUDIO_RELEASE_RUNBOOK.md`

## Secondary compatibility surfaces

These remain supported for engine-specific or legacy workflows, but they are not the primary desktop product:

- `start.bat`
- `start.sh`
- `install.ps1`
- `install.sh`
- `bootstrap_all.py`
- `installer_gui.py`
- `setup.py`

Treat them as standalone-engine and integration tooling around the broader EDMG codebase, not as equal alternatives to Studio.

## Legacy/reference surfaces

These are useful for reference, migration, or archived workflows:

- `desktop/electron/`
- `examples/archive-ui/`
- `juce_example/`

## Release and validation

Use these for the Studio product:

- `README_STUDIO.md`
- `RELEASE.md`
- `docs/STUDIO_RELEASE_RUNBOOK.md`

Key validation commands run from `studio/edmg-studio/`:

- `npm run validate:desktop`
- `npm run dist:win`
- `npm run validate:packaged-customer-flow`
- `npm run validate:packaged-upgrade-proof`
