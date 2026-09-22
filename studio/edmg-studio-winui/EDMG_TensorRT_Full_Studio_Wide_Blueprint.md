# EDMG Studio Full TensorRT Capability — WinUI Delivery Blueprint

This is the WinUI-facing copy of the root TensorRT blueprint. It defines how the native Studio surface exposes a Studio-wide optional TensorRT capability while every existing workflow remains usable without TensorRT.

## Native user experience

TensorRT is a backend capability, not a new renderer page. WinUI continues to expose Workspace, AI Planner, Director, Storyboard, Reactive Lab, Timeline, Render, Models, and Settings. Runtime controls appear in the existing Settings and advanced Render/Models surfaces.

The normal path remains:

```text
Select model and creative settings → Render → backend selects each component runtime
```

Advanced controls are:

- Runtime: Automatic, Compatibility, Performance, PyTorch CUDA, TensorRT, CPU/Fallback.
- TensorRT enabled globally.
- Automatic engine build policy.
- Fallback allowed.
- Preferred precision.
- GPU/device selection for the operation.
- Strict diagnostics mode.
- Run diagnostics, optimize model, rebuild, and clear selected cache.

The default is Automatic with fallback enabled. A normal user is not required to install, configure, or understand TensorRT.

## Native page responsibilities

### Settings

Show Installed, Available, Healthy, Compatible, and Accelerating as separate states. Show TensorRT version, CUDA/PyTorch status, GPU list, cache usage, last diagnostic receipt, and supported component count. Clearly label a receipt as a prior test rather than live inference proof.

### Models

For each installed model show declared component support, validated engine count, profile coverage, last benchmark, and fallback state. Offer Optimize only when the backend says the model/component is eligible. Model download remains independent of engine compilation.

### Render and Workspace

Keep normal creative controls uncluttered. Put per-operation runtime controls under Advanced options. Preserve render profile compatibility and exact timeline/project state. Runtime selection is submitted as request data; WinUI never performs selection itself.

### Job queue

Show engine build, validation, benchmark, cancellation, quarantine, and fallback events through the existing job APIs. A failed TensorRT build must be understandable and must not make an ordinary render unusable.

## Backend contract consumed by WinUI

- `GET /v1/runtime/status`
- `POST /v1/runtime/settings`
- `POST /v1/runtime/jobs`
- `DELETE /v1/runtime/tensorrt/cache/{engine_id}`
- Existing job, progress, log, cancel, and result endpoints.

Both WinUI and Electron consume these APIs. There is no native TensorRT DLL boundary.

## Native safety and fallback rules

- Startup must succeed when TensorRT is absent.
- Settings status must distinguish absent, disabled, unprobed, broken, ready, and currently accelerating.
- A failed engine is quarantined by the backend and cannot be retried repeatedly in one job.
- A normal render falls back to the original PyTorch/specialized runtime when permitted.
- Strict mode is for diagnostics and is off by default.
- Resume can change runtime if the checkpoint remains compatible.
- GPU 0, GPU 1, and later GPUs remain separate devices.

## WinUI implementation phases

1. Inventory current pages, API client, navigation, settings persistence, job queue, theme resources, and accessibility patterns.
2. Add typed API-client methods and status models without changing current render defaults.
3. Add the Settings runtime panel using stock WinUI controls and theme resources.
4. Add Models capability/optimization status and Render advanced per-operation controls.
5. Add job progress and fallback history through the existing queue.
6. Verify narrow, medium, and wide layouts; keyboard navigation; Narrator names; light/dark themes; packaged and unpackaged storage.
7. Build and launch-verify the native app, then run backend and frontend regression suites.

## Component rollout shown in WinUI

Only components with backend qualification receipts are selectable in Automatic. The initial staged component is the SD1.5 VAE decoder. Future waves add SDXL/SD3 components, text/vision encoders, SD transformers, LTX, Wan, Hunyuan components, and other declared model adapters one at a time. Unsupported Hunyuan/LTX/Wan transformers continue to show their existing runtime and PyTorch fallback until separately qualified.

## Documentation updates

The WinUI README must describe the native controls, page responsibilities, backend-only runtime boundary, optional installation, fallback behavior, accessibility expectations, and the distinction between compiled/build evidence and live-window verification. The root, backend, packaging, and Studio docs remain authoritative for their respective scopes and should be linked rather than copied wholesale.

## Acceptance

The native feature is ready only when the WinUI build passes, a real updated top-level window is verified, backend and frontend tests pass, TensorRT-absent startup is demonstrated, status labels are truthful, and every enabled component has a separate engine/quality/fallback receipt. A successful build alone does not prove live UI or full TensorRT model qualification.
