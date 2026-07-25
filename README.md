# Enhanced Deforum Music Generator (EDMG) — Studio Canonical Repo

This repository now combines:
- EDMG Studio, the primary desktop product
- standalone EDMG engine flows
- legacy A1111 / engine integration paths
- installer and build tooling for compatibility and advanced workflows

EDMG Studio is the authoritative product surface. The other repo-root entrypoints
remain available for compatibility, migration, and engine-specific workflows,
but they are not equal alternatives to the Studio product.

## Canonical product

The primary desktop product lives under:

- `studio/edmg-studio/`

That tree contains the Electron shell, React/Vite frontend, FastAPI backend,
vendored EDMG engine packages, packaging scripts, and release validation flow.

The legacy standalone web UI prototypes have been retired from the active product
surface. Their planning and audio-reactive workflows now live inside Studio
workbenches such as:

- `studio/edmg-studio/src/workbenches/AiNlpWorkbench.tsx`
- `studio/edmg-studio/src/workbenches/AudioReactiveWorkbench.tsx`

## Canonical launch

Windows:

```bat
RUN_ME.bat
```

macOS/Linux:

```bash
./run_me.sh
```

Those launchers open the Studio dev launcher in
`studio/edmg-studio/tools/launcher_gui.py`, which keeps the UI, backend, and
Studio Home storage aligned with the same settings used by the packaged app.

The launcher flow:
- installs Studio backend/UI dev dependencies when needed
- starts EDMG Studio
- keeps runtime data and caches under your chosen Studio Home
- lets Studio’s in-app Setup page handle Ollama, local OpenAI-compatible
  providers, ComfyUI Portable, model packs, and EDMG Core repair/install

## Studio Setup

Inside Studio:
- set **Studio Home** to `D:\...` or another large volume if you want heavy
  runtime state off the system drive
- run **Full Setup** for Ollama + ComfyUI Portable
- optionally install or repair **EDMG Core** from the same Setup page

## Studio Home

Studio separates the app install directory from the heavy runtime storage root.
The `Studio Home` typically contains:

- `data`
- `models`
- `cache`
- `logs`
- `external`
- `electron`

That keeps large downloads, model caches, render outputs, and external tools
off the app install path and makes migration to another drive or mount easier.

## Secondary / compatibility paths

These still exist, but they are not the primary product entry:

- `start.bat`
- `start.sh`
- `install.ps1`
- `install.sh`
- `bootstrap_all.py`
- `installer_gui.py`
- `setup.py`
- `desktop/electron/`
- standalone engine / Gradio workflows
- archived UI prototypes in `examples/archive-ui/`

Treat them as compatibility or engine-specific workflows around the broader EDMG
codebase, not as equal alternatives to Studio.

### Engine install (secondary)

Linux/Mac:

```bash
bash install.sh full cpu
# or CUDA (example)
bash install.sh full cu121
```

Windows:

```powershell
.\install.ps1 -Mode full -Cuda
# or use the GUI installer to choose cu118/cu121/cu124

# Example: keep the venv and caches on D:
.\install.ps1 -Mode full -Backend cu121 -Venv D:\EDMG\venv -CacheRoot D:\EDMG\cache
```

### Run legacy standalone engine UI

Linux/Mac:

```bash
./start.sh
```

Windows:

```powershell
.\start.bat
```

## UI default mode: Deforum JSON Expert

The Gradio UI defaults to **Deforum JSON Expert** mode:
- a full Deforum settings template is shown as editable JSON
- EDMG generates audio-reactive schedules and prompts
- your edited template overrides generated output keys when merged

## Legacy desktop shell

An older Electron shell still exists here:

```text
desktop/electron
```

It is superseded by `studio/edmg-studio`, which is the canonical desktop product.

## A1111 / legacy integration

This repo still contains legacy engine and integration paths, but it does not
ship a bundled `a1111_extension/` folder anymore.

If you need Automatic1111 integration, treat it as an external or legacy
workflow alongside the standalone EDMG engine. The authoritative desktop product
path remains:

- `studio/edmg-studio/`

## JS tooling

- Run all JS/Electron commands from `studio/edmg-studio/`.
- Use Node.js `20.19+` or `22.12+`; Node 22 LTS is pinned in
  `studio/edmg-studio/.node-version`.
- The canonical package manager is `pnpm@10.33.0`, pinned in
  `studio/edmg-studio/package.json`.
- The shipped desktop app version also comes from
  `studio/edmg-studio/package.json#version`.

## Python tooling

- Python is pinned to 3.12 in `.python-version`.
- `uv` 0.11.28 manages Python acquisition, the backend environment, locking,
  tests, linting, and PyInstaller builds for the Studio/backend path.
- `studio/edmg-studio/python_backend/uv.lock` is committed release input.
- Select exactly one accelerator extra: `cpu`, `directml`, or `cuda`; compose it
  with capability extras such as `audio`, `asr`, and `internal-video`.
- Packaged Electron applications include the PyInstaller backend and do not
  require end users to install Python or uv.

See [docs/PYTHON_TOOLCHAIN.md](./docs/PYTHON_TOOLCHAIN.md) for commands and the
lock-update policy.

## Release / validation

For Studio release operations, use:

- [README_STUDIO.md](./README_STUDIO.md)
- [studio/edmg-studio/README.md](./studio/edmg-studio/README.md)
- [RELEASE.md](./RELEASE.md)
- [docs/STUDIO_RELEASE_RUNBOOK.md](./docs/STUDIO_RELEASE_RUNBOOK.md)

Additional strategy and operator docs:

- [docs/STUDIO_REPO_MAP.md](./docs/STUDIO_REPO_MAP.md)
- [docs/TESTING_QUICKSTART.md](./docs/TESTING_QUICKSTART.md)
- [docs/UV_MIGRATION_INVENTORY.md](./docs/UV_MIGRATION_INVENTORY.md)
- [docs/MODEL_MANAGER.md](./docs/MODEL_MANAGER.md)
- [studio/edmg-studio/docs/STUDIO_MODULARITY.md](./studio/edmg-studio/docs/STUDIO_MODULARITY.md)
- [docs/STUDIO_FORGE.md](./docs/STUDIO_FORGE.md)
- [docs/UNIFIED_INTERNAL_RENDERER_PLAN.md](./docs/UNIFIED_INTERNAL_RENDERER_PLAN.md)
- [docs/VISUAL_DNA_AND_RENDER_CONDUCTOR_SPEC.md](./docs/VISUAL_DNA_AND_RENDER_CONDUCTOR_SPEC.md)
- [docs/STARLIFT_VM_DEPLOY.md](./docs/STARLIFT_VM_DEPLOY.md)
- [docs/GCP_GPU_VM_DEPLOY.md](./docs/GCP_GPU_VM_DEPLOY.md)
- [docs/AI_PROVIDERS.md](./docs/AI_PROVIDERS.md)
- [docs/HF_VIDEO_MODELS.md](./docs/HF_VIDEO_MODELS.md)
- [docs/AI_INTEGRATION.md](./docs/AI_INTEGRATION.md)

## Test strategy

- Repo-level tests live under `tests/`; backend tests live under
  `studio/edmg-studio/python_backend/`.
- Run both scopes from the repo root with:

```bash
uv run --project studio/edmg-studio/python_backend --frozen --extra cpu --extra core --extra audio --group test python scripts/run_pytest_scopes.py
```

- The runner checks the committed lock and performs a frozen CPU-profile sync
  before executing either scope.

## Notes

- This project installs Python dependencies but does not install GPU drivers.
- First run of the legacy A1111 path can take time because Stable Diffusion WebUI
  creates and populates its own environment.

## Compatibility shims

- Repo-root `sitecustomize.py` and the repo-root `librosa/` package are
  source-tree compatibility shims for development and tests.
- Packaged/backend install flows rely on the declared Python dependencies and do
  not package those repo-root shims.
