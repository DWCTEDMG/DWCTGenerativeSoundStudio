# Studio Forge

Studio Forge is an experimental, opt-in AI builder workbench for EDMG Studio.

It is currently read-only. It does not replace:
- Electron shell
- React frontend
- FastAPI backend
- Setup Wizard
- internal renderer
- ComfyUI integration
- model manager
- render queue
- packaging scripts

Enable in development with:

```bash
VITE_EDMG_ENABLE_STUDIO_FORGE=1
```

Current features:
- runtime status overview
- template preview
- workflow recipe preview
- validation checklist

Studio Forge v1 does not generate code, run workflows, install runtimes, pull models, mutate project data, or execute shell commands from the frontend.
