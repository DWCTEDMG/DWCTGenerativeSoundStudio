# EDMG Studio – quick test (no CLI typing)

1. Unzip this folder somewhere short (e.g. `C:\EDMG\`).
2. Double-click **RUN_ME.bat**
3. In the Launcher:
   - Click **Install/Update Backend**
   - Click **Install/Update Studio UI**
   - Click **Start Backend**
   - Click **Run Health Test**
   - Click **Start Studio (Electron dev)**

`LAUNCH_EDMG_STUDIO_GUI.bat` still exists as a compatibility alias, but the
canonical launcher now lives under `studio/edmg-studio/RUN_ME.bat` and the
repo-root `RUN_ME.bat` simply forwards to it.

## Prereqs (installed once)
- **Python `>=3.10,<3.14`** (Windows: install from python.org)
- **Node.js LTS** (for the Electron UI)
- Optional but recommended:
  - **Ollama** running at `http://127.0.0.1:11434`
  - **ComfyUI** running at `http://127.0.0.1:8188`
  - **FFmpeg** on PATH (for MP4 assembly)

If Ollama/ComfyUI/FFmpeg aren’t installed yet, the app will still boot and show clear “Fix:” instructions in the Setup / logs.

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
python -m pytest
python scripts/run_pytest_scopes.py
```

- `python -m pytest` runs the repo-level test scope defined by `pytest.ini`.
- `python scripts/run_pytest_scopes.py` runs the repo-level tests first, then the backend-local pytest scope.

From `studio/edmg-studio/python_backend/`:

```powershell
python -m pytest
```

That backend-local command follows `pyproject.toml` and covers both:

- `enhanced_deforum_music_generator/tests`
- `edmg_studio_backend/tests`
