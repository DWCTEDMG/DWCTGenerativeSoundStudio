# Enhanced Deforum Music Generator (EDMG) — Unified Repo

This repo merges:
- EDMG Studio, the primary desktop product
- Standalone EDMG engine (Gradio UI + CLI + API)
- Legacy A1111/engine integration paths
- Installer/build scripts for advanced and legacy workflows

## Quick start (recommended)

### 1) Launch EDMG Studio
```bash
RUN_ME.bat
```

Or on macOS/Linux:
```bash
./run_me.sh
```

The launcher opens the canonical unified Studio flow:
- installs Studio backend/UI dev dependencies when needed
- starts EDMG Studio
- keeps runtime data and caches under your chosen Studio home
- lets Studio’s in-app Setup page handle Ollama, local OpenAI-compatible providers, ComfyUI Portable, model packs, and EDMG Core repair/install

### 2) Use Studio Setup
Inside Studio:
- set **Studio Home** to `D:\...` if you want the full product off `C:\`
- run **Full Setup** for Ollama + ComfyUI Portable
- optionally install **EDMG Core** from the same Setup page for the fully unified workflow

## CLI / scripts (manual)

### Install (creates `./venv`)
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

### Run EDMG UI
Linux/Mac:
```bash
./start.sh
```

Windows:
```powershell
.\start.bat
```

## UI default mode: Deforum JSON Expert

The Gradio UI defaults to **“Deforum JSON Expert”** mode:
- A full Deforum settings template is shown as editable JSON
- EDMG generates audio-reactive schedules + prompts
- Your edited template **overrides** the generated output keys when merged

## Legacy desktop shell

An older Electron shell still exists here:

```
desktop/electron
```

It is superseded by `studio/edmg-studio`, which is now the canonical desktop product.

## A1111 / legacy integration

This repo still contains legacy engine and integration paths, but it does **not**
ship a bundled `a1111_extension/` folder anymore.

If you need Automatic1111 integration, treat it as an external/legacy workflow
alongside the standalone EDMG engine. The authoritative desktop product path is:

- `studio/edmg-studio/`

## Notes

- This project installs Python dependencies but does **not** install GPU drivers.
- First run of the legacy A1111 path can take time because Stable Diffusion WebUI
  creates and populates its own environment.

## Documentation

- [AI integration design (API + local providers)](docs/AI_INTEGRATION.md)
