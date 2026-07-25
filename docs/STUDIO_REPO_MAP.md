# EDMG Studio Repo Map

This repo contains one primary product and several compatibility surfaces.

## Canonical product

The authoritative desktop product is:

- `studio/edmg-studio/`

Its canonical runtime architecture is:

1. Electron shell and preload in `studio/edmg-studio/`
2. React/Vite frontend in `studio/edmg-studio/src/`
3. FastAPI backend in `studio/edmg-studio/python_backend/`
4. Shared launcher/runtime glue in `studio/edmg-studio/tools/launcher_gui.py`
5. Packaging and release validation under `studio/edmg-studio/scripts/`,
   `studio/edmg-studio/packaging/windows/`,
   `studio/edmg-studio/packaging/linux/`, and
   `docs/STUDIO_RELEASE_RUNBOOK.md`

Canonical launch path from the repo root:

- `RUN_ME.bat`
- `./run_me.sh`

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
- [studio/edmg-studio/README.md](../studio/edmg-studio/README.md)
- [RELEASE.md](../RELEASE.md)
- [docs/STUDIO_RELEASE_RUNBOOK.md](./STUDIO_RELEASE_RUNBOOK.md)

Key validation commands:

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

Canonical packaged desktop version source:

- `studio/edmg-studio/package.json#version`
