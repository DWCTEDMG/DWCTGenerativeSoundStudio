# Unified Internal Renderer Plan

## Canonical entrypoint

Studio still has one canonical video render entrypoint:

- backend route: `studio/edmg-studio/python_backend/edmg_studio_backend/app.py`
  - `POST /v1/projects/{project_id}/render/internal/video`
- runtime worker: `_run_internal_video(...)`
- canonical engine: `render_internal_video_variant(...)` in `studio/edmg-studio/python_backend/edmg_studio_backend/services/internal_video.py`

Hosted and proxy paths remain fallbacks around the same Studio job orchestration. No second Deforum renderer exists.

## Where temporal rendering lives

Temporal rendering stays inside `render_internal_video_variant(...)`.

- keyframe generation happens first
- `temporal_mode="frame_img2img"` keeps the sequential img2img loop inside the same function
- progress reporting, checkpointing, output folders, cache tags, and muxing remain unchanged

## Where prompts and motion resolve now

Prompt and motion resolution are now factored into shared support modules under `edmg_studio_backend/services/`:

- `deforum_schedule.py`
  - parses and interpolates Deforum-style numeric schedules
- `deforum_prompt_timeline.py`
  - resolves prompt maps by frame with latest-keyframe-wins semantics
- `deforum_motion.py`
  - evaluates camera/diffusion motion state per frame
- `deforum_normalize.py`
  - normalizes Studio scenes, timeline tracks, variant motion schedules, and optional request overrides into one render context

`internal_video.py` consumes that normalized context but remains the renderer.

## Current integration seam

The safe merge seam is inside the existing render loop, before prompt encoding and before camera/init-frame warping:

1. Build one normalized Deforum context from:
   - canonical Studio scenes
   - canonical Studio timeline tracks
   - variant `motion_schedules`
   - optional `InternalVideoRenderRequest` Deforum override fields
2. Resolve prompt and negative prompt for the current schedule frame.
3. Evaluate motion state for the current schedule frame.
4. Feed those values into the existing keyframe generation, camera transform, and frame-to-frame img2img path.

That keeps Deforum-style logic as support code inside the existing engine rather than creating a sibling runtime.

## Temporal img2img

Frame-to-frame img2img still happens in `render_internal_video_variant(...)`:

- the previous rendered frame is camera-warped
- prompt embeddings are resolved/blended for the current interval
- schedule-driven strength / cfg / steps / denoise values are applied
- the same internal diffusion pipeline renders the next frame

## Result

The end state is one unified Studio renderer:

- one route
- one internal render worker
- one internal diffusion render loop
- Deforum-style schedules as utility/support code only

No external WebUI runtime dependency was added.
