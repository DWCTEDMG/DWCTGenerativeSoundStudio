# Studio Forge

Studio Forge is the default-visible, Studio-side 1.0 readiness and guided-workflow surface for EDMG Studio. It reports what the current machine, selected project, selected variant, models, providers, storage, and render routes can actually do, then sends the user to the canonical Studio page that owns the next safe action.

Forge is available by default. To hide it for a packaging or support fallback, set:

```bash
VITE_EDMG_DISABLE_STUDIO_FORGE=1
```

The earlier `VITE_EDMG_ENABLE_STUDIO_FORGE` flag remains a compatibility control, but a normal build no longer needs an opt-in value.

## Studio-side 1.0 scope

Forge provides:

- live system, storage, CUDA/accelerator, provider, model, and task readiness derived from existing Studio APIs
- active-project and selected-variant readiness, including audio, analysis, plan, output, Deforum, Unreal, and live-publisher state
- selectable recipes whose stages are labeled completed, current, or blocked
- safe calls to action into the canonical `Setup`, `Models`, `Workspace`, `Render`, `Review`, and `Outputs` pages
- partial-failure, offline, degraded, loading, error, and empty states without presenting missing data as ready
- Unreal bridge status and handoff links without making Unreal a required runtime

Forge does not own setup, model installation, project mutation, rendering, review publishing, or output import/export. Those actions remain on their canonical pages. Forge also does not generate code, execute shell commands, install runtimes, or silently fall back in a way that presents a failed capability as available.

## Live publishers

`Review` owns the existing OSC, MIDI, and WebSocket live-publisher controls and status. Forge can report that readiness and route the user to Review, but it does not duplicate or replace the publisher implementation.

These publishers are Studio handoffs. They are not a direct Unreal Remote Control integration.

## Unreal bridge status

Supported on the Studio side:

- preview the Unreal bridge contract for the active project and variant
- export a controlled Unreal bundle
- generate the bundle import plan
- import returned media into canonical project outputs
- route the user to `Workspace` and `Outputs`, where the authoritative preview/export/import-plan/returned-media actions live
- use `studio/edmg-studio/tools/unreal/import_unreal_bridge_bundle.py` as the first Unreal-side consumer

Current backend contracts include:

- `GET /v1/projects/{project_id}/unreal/preview`
- `POST /v1/projects/{project_id}/export/unreal`
- `POST /v1/projects/{project_id}/unreal/import-plan`
- `POST /v1/projects/{project_id}/import/unreal`

The importer remains a first-pass Sequencer consumer: it creates cameras, cuts, markers, and plan metadata. It does not yet ingest or construct the full scene, control Unreal directly, or launch a render.

Explicitly outside the current completion claim:

- no verified in-editor Unreal smoke test
- no packaged Unreal plugin or module
- no direct Unreal Remote Control integration
- no Movie Render Queue (MRQ) automation
- no one-click Unreal editor or render-job launch
- no full editor, scene-build, or returned-render automation

Honest status:

- Studio Forge readiness and guided routing: Studio-side 1.0
- Studio Unreal preview/export/import-plan/returned-media handoffs: supported through canonical pages
- Unreal importer: first-pass and not yet proven in-editor
- full Unreal automation: not implemented
