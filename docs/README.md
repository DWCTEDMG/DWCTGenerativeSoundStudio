---
license: openrail
---

# Documentation

- [Root repo overview](../README.md)
- [Studio entrypoint](../README_STUDIO.md)
- [Native WinUI client and unified Workspace](../studio/edmg-studio-winui/README.md)
- [Unified Workspace acceptance and completion record](../WORKSPACE_UNIFIED_BLUEPRINT_TASK.md)
- [WinUI 3 consolidated blueprint](../blueprint/WINUI3_CONSOLIDATED_BLUEPRINT.md)
- [Professional DAW phase ledger](../blueprint/planning.md)
- [Backend and managed model runtimes](../studio/edmg-studio/python_backend/README.md)
- [GPU-first accelerator policy](STUDIO_ACCELERATOR_POLICY.md)
- [Windows Setup.exe packaging](../studio/edmg-studio/packaging/windows/README.md)
- [Linux and compatibility client](../studio/edmg-studio/README.md)
- [Studio repo map](STUDIO_REPO_MAP.md)
- [Testing quickstart](TESTING_QUICKSTART.md)
- [Studio release runbook](STUDIO_RELEASE_RUNBOOK.md)
- [Architecture](architecture.md)
- [AI providers](AI_PROVIDERS.md)
- [AI integration design](AI_INTEGRATION.md)
- [Model manager](MODEL_MANAGER.md)
- [ComfyUI workflows](COMFYUI_WORKFLOWS.md)
- [HF video models](HF_VIDEO_MODELS.md)
- [Benchmarking](BENCHMARKING.md)
- [Studio Forge](STUDIO_FORGE.md)
- [Studio modularity roadmap](../studio/edmg-studio/docs/STUDIO_MODULARITY.md)
- [Unified internal renderer plan](UNIFIED_INTERNAL_RENDERER_PLAN.md)
- [Visual DNA and Render Conductor spec](VISUAL_DNA_AND_RENDER_CONDUCTOR_SPEC.md)
- [Starlift VM deploy](STARLIFT_VM_DEPLOY.md)
- [GCP GPU VM deploy](GCP_GPU_VM_DEPLOY.md)

## Optional Studio-wide TensorRT capability

EDMG Studio supports optional TensorRT acceleration through the shared backend runtime manager. Studio settings provide the global switch; native Render controls can override the preference, precision, and fallback for an individual internal render. Turning TensorRT off preserves the original runtime and does not require TensorRT to be installed.

This area retains its existing runtime and workflow; the shared Studio policy applies only to eligible internal inference components. The SD1.5 VAE decoder has an adapter; other model components remain on their existing runtimes until separately converted and validated. Hosted providers, audio processing, compositing, and exports do not acquire a TensorRT dependency. See the [Studio-wide TensorRT blueprint](../EDMG_TensorRT_Full_Studio_Wide_Blueprint.md) for component admission and validation requirements.
