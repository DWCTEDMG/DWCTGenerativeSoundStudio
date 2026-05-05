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

`VITE_EDMG_ENABLE_STUDIO_FORGE=1`

Current features:

- runtime status overview
- runtime-aware recommendations
- template preview
- workflow recipe preview
- Unreal bridge preview cards
- backend Unreal bridge contract preview via `/v1/projects/{project_id}/unreal/preview`
- backend Unreal bridge export bundle via `POST /v1/projects/{project_id}/export/unreal`
- validation checklist

Studio Forge v1 does not generate code, run workflows, write files, install runtimes, or mutate project data.
