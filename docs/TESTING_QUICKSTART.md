# EDMG Studio – quick test (no CLI typing)

1. Unzip this folder somewhere short (e.g. `C:\EDMG\`).
2. Double-click **RUN_ME.bat**
3. In the Launcher:
   - Click **Install/Update Backend (auto CUDA + TensorRT)**
   - Click **Install/Update Studio UI**
   - Click **Start Backend**
   - Click **Run Health Test**
   - Click **Start Studio (Electron dev)**

`LAUNCH_EDMG_STUDIO_GUI.bat` still exists as a compatibility alias, but the
canonical launcher now lives under `studio/edmg-studio/RUN_ME.bat` and the
repo-root `RUN_ME.bat` simply forwards to it.

## Prereqs (installed once)
- **Python 3.12** (the source launcher can acquire it through pinned uv)
- **uv 0.11.28** for source/dev workflows; packaged applications need neither
  Python nor uv
- **Node.js LTS** (for the Electron UI)
- Optional but recommended:
  - **Ollama** running at `http://127.0.0.1:11434`
  - **ComfyUI** running at `http://127.0.0.1:8188`
  - **FFmpeg** on PATH (for MP4 assembly)
  - **NVIDIA driver** with `nvidia-smi` for the locked CUDA 13.0/TensorRT profile

If Ollama/ComfyUI/FFmpeg aren’t installed yet, the app will still boot and show
clear “Fix:” instructions in Setup/logs. Source environments select exactly one
locked accelerator profile: `cpu`, `directml`, or `cuda`.

## Release proof

From `studio/edmg-studio/`:

```powershell
pnpm run check:tooling
pnpm run validate:release
```

That runs the staged desktop checks, packaged customer-flow proof, and packaged
upgrade/migration proof.

For the fresh-machine packaged setup path specifically:

```powershell
pnpm run validate:packaged-zero-state-setup
```

That proof ignores global Ollama/7-Zip, installs Studio-managed copies under
the selected `Studio Home`, and verifies the packaged app can bootstrap its own
external tools from scratch.

## Pytest scopes

From the repo root:

```powershell
uv lock --project studio/edmg-studio/python_backend --check
uv run --project studio/edmg-studio/python_backend --frozen --extra cpu --extra core --extra audio --group test python scripts/run_pytest_scopes.py
```

- The runner performs a frozen CPU-profile sync, runs the repo-level test scope
  first, then runs the backend-local pytest scope.

From `studio/edmg-studio/python_backend/`:

```powershell
uv lock --check
uv sync --frozen --extra cpu --extra core --extra audio --group test
uv run --frozen --extra cpu --extra core --extra audio --group test python -m pytest
```

That backend-local command follows `pyproject.toml` and covers both:

- `enhanced_deforum_music_generator/tests`
- `edmg_studio_backend/tests`
