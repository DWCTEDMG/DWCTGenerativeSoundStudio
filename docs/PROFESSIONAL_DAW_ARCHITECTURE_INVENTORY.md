# Professional DAW Architecture Inventory

This inventory is the Phase 0 safety baseline for the Professional DAW architecture roadmap. It records the implementation at commit `a5ebae7` (`Complete Phase 1 shared core contracts`) and must be updated when an ownership boundary or canonical path changes. The separate WinUI native-experience roadmap is not tracked here.

## Product and data ownership

| Concern | Authoritative owner | Compatibility or presentation surfaces |
| --- | --- | --- |
| Windows desktop UI | `studio/edmg-studio-winui/` | Electron/React remains the Linux and compatibility client in `studio/edmg-studio/` |
| API, project persistence, jobs, AI, rendering, and model lifecycle | `studio/edmg-studio/python_backend/edmg_studio_backend/` | WinUI and Electron consume the same authenticated localhost API |
| Project document | `<studio-home>/data/projects/<id>/project.json`, managed by the backend project store | Autosave journal, recovery snapshots, and migration backups are described in `docs/PROJECT_FORMAT.md` |
| Durable jobs | `<studio-home>/data/jobs.sqlite` | Per-project job JSON is retained for older tooling |
| Shared v1 schemas | `python_backend/edmg_studio_backend/contracts/` | C# contracts in `src/EdmgStudio.Core/Models/`; browser contracts in `studio/edmg-studio/src/contracts/` |

Existing project payloads are extensible. Adapters must preserve unknown fields, Director/Reactive Lab state, reviewed camera and motion keyframes, render profile identifiers, artifact lineage, and future provider metadata. Required or semantic schema changes require a new schema version and migration adapter.

## Renderer inventory

| Path | Entrypoint and implementation | Status and constraints |
| --- | --- | --- |
| Canonical internal render orchestration | `POST /v1/projects/{project_id}/render/internal/video`, assembled by `api/render.py` and `app.py` | Owns preflight, durable jobs, cancellation, progress, completion, and artifact publication |
| Unified internal diffusion/Deforum path | `services/internal_video.py::render_internal_video_variant` | Deforum schedules are support modules, not a second renderer; preserve `docs/UNIFIED_INTERNAL_RENDERER_PLAN.md` |
| HunyuanVideo-1.5 | `services/hunyuan_video15_worker.py` and dispatch in `services/internal_video_models.py` | Official isolated WSL/Linux runtime; T2V, I2V, chunking, offload, and low-memory controls remain capability-gated |
| LTX-2.5 Distilled | `services/ltx_25_runtime.py` and model runtime registry | Isolated pinned runtime; installation is not readiness until runtime validation succeeds |
| Other managed internal paths | `services/internal_video_models.py`, `services/model_runtime_registry.py`, and `services/model_catalog.py` | Includes supported diffusion, TensorRT, SVD, AnimateDiff, and configured model variants; all remain behind the canonical job path |
| Hosted/proxy render paths | Cloud routes and render-provider fallbacks in `api/cloud.py`, `api/render.py`, and `app.py` | Fallbacks must not replace or break local rendering; outputs must enter the ordinary artifact/media flow |
| Legacy standalone engines | Repo-root launch/install flows, A1111-compatible and archived surfaces | Compatibility only; do not delete until replacement acceptance tests pass |

Renderer logic stays in the Python backend. Timeline UI may submit normalized intent and insert a completed artifact, but must not select model internals or implement renderer behavior.

## Provider inventory

| Provider family | Current integration | Credential rule |
| --- | --- | --- |
| Rule-based planning | Built-in planner selected with `EDMG_AI_PROVIDER=rule_based` | No credential |
| Ollama | Local provider and status/discovery through provider APIs | Local endpoint configuration only |
| OpenAI-compatible / NVIDIA Nemotron cloud | Planner configuration documented in `docs/AI_PROVIDERS.md` | Token stored through Studio secret settings, never project JSON |
| Optional external AI service | HTTP planning mode configured by `EDMG_AI_MODE=http` | Endpoint configuration is operational state |
| ComfyUI | Backend status, workflow, and rendering integration | External runtime configuration; no workflow secrets in projects |
| Internal model runtimes | Model manager, runtime registry, catalogue, setup, and validation receipts | Runtime state belongs under Studio Home, not project data |

`api/providers.py` exposes operational status, discovery, and provider-neutral generation definitions. Phase 11 adds a normalized generation envelope at `/v1/projects/{project_id}/generation` and normalized durable queue projections under `/v1/generation/jobs`; legacy render and job routes remain compatibility surfaces over the same canonical queue.

## Timeline and project inventory

| Layer | Canonical responsibilities | Compatibility notes |
| --- | --- | --- |
| Backend project store | Atomic project saves, schema migration, autosave/recovery, revisions, and metadata persistence | Existing `project.json` shape remains authoritative until an explicit migration |
| Backend editor | `domain/editor_commands.py` and `api/editor.py`: revision-checked edit/replace/undo/redo, idempotency receipts, compact deltas, and locked-object validation | Multi-operation edits are one undo transaction; external changes invalidate unsafe history |
| Shared C# project model | `ProjectTimelineContracts.cs`: exact sample positions, ordered tracks/events, media pool, provenance, and extension-preserving rebuild | Operational JSON remains backward compatible |
| Shared C# mutations | `ProjectTimelineOperations.cs` and `CommandUndoContracts.cs` | Mutations build backend-compatible requests; timeline code must not move into page code-behind |
| WinUI timeline | `Pages/TimelinePage.xaml(.cs)` plus Core projection/viewport models | Presentation, selection, viewport, and command dispatch only |
| Legacy Python timeline helpers | `domain/timeline_commands.py` | Do not expand floating-point legacy paths; new persisted edits use canonical sample-based editor commands |

At the baseline commit, track creation/reordering/state and canonical persistence are stable. Move, trim, split, duplicate, delete, markers, snapping, and their UI are active working-tree development and are not part of this baseline until committed and validated.

## Media inventory

| Capability | Current path | Gap retained for Phase 3 |
| --- | --- | --- |
| Project audio/overlay/mask upload | `api/project_media.py` | General typed media import and deduplication service |
| Secure media URL/preview validation | `api/media.py` | Missing-media availability and relink workflow |
| Project media pool | Canonical project timeline/media contracts and artifact insertion | Lifecycle service with content-hash identity across all imported media |
| Metadata probe and preview decode | WinUI Core media classes including `FfmpegVideoDecoder`, `VideoMetadata`, and `VideoPlaybackSession` | Unified backend audio/video/image probe contract |
| Generated artifacts | Sidecar manifests and v1 artifact provenance | Queue-completion-to-timeline acceptance for every renderer/provider |
| Waveforms, thumbnails, proxies | No canonical persistent service | Hash-invalidated asynchronous waveform/thumbnail caches and proxy generation |

FFmpeg preview decoding is a media-preview facility. It is not the DAW audio engine.

## Audio backend inventory

No production real-time DAW audio backend exists at this baseline. The repository has audio upload, offline analysis, FFmpeg media decoding, and preview transport controls, but it does not have an authoritative sample clock, ASIO/WASAPI device backend, multitrack render graph, real-time callback boundary, routing, metering, or glitch-safety tests.

Phase 4 must introduce narrow transport, device, and render-graph interfaces with a deterministic fake backend before native output. UI, AI, filesystem, network, allocation-heavy, and blocking work must never execute on the real-time callback.

## Stable behavior and regression matrix

| Behavior to preserve | Regression evidence |
| --- | --- |
| Existing and long-duration exact sample/time conversion | `python_backend/edmg_studio_backend/tests/test_project_time.py`; Core project/timeline contract tests |
| Extension-safe project/timeline round trips | `EdmgStudio.Core.Tests/ProjectTimelineContractsTests.cs` |
| Revision-safe grouped editor commands, undo/redo, and idempotency | `python_backend/edmg_studio_backend/tests/test_editor_commands.py`; `CommandUndoContractsTests.cs` |
| Director draft recovery without routine reanalysis | `python_backend/edmg_studio_backend/tests/test_director_workflow.py`; `ReactiveDraftCompatibilityTests.cs` |
| Partial/null Reactive Lab payloads remain loadable | `ReactiveDraftCompatibilityTests.cs` |
| Reviewed camera/motion keyframes survive Director and project persistence | Director/provider and timeline camera projection tests |
| Render-profile and backend schema compatibility | Contract schema/adaptor tests in `test_contracts_v1.py`; render request-builder tests |
| Generated artifact identity and provenance survive timeline insertion | Project timeline and render-result insertion tests |
| FFmpeg discovery, probing, cancellation, spool limits, and cleanup | `EdmgStudio.Core.Tests/MediaPipelineTests.cs` |
| Hunyuan and LTX runtime dispatch remain capability-gated | Focused internal-video, Hunyuan, LTX, model-runtime, and motion-quality tests |
| WinUI XAML pages compile | Release build of `studio/edmg-studio-winui/EdmgStudio.WinUI.slnx` |

The Director/Reactive Lab workflow rules in `studio/edmg-studio-winui/ChatLog3.md`, `ChatLog4.md`, and the workstation `ChatLog5.md` are regression requirements: applying a saved Director draft must reconnect persisted analysis/keyframes, reanalysis is exceptional rather than routine, and applying review guidance must retain draft identity/revision safeguards.

## Migration and delivery baseline

- Baseline commit: `a5ebae7`, on the historical integration/default branch `codex/Unified`.
- Architecture work lands as focused commits with additive adapters before stored-format replacement.
- Existing uncommitted work is not baseline evidence and must never be overwritten or reverted.
- The target branch policy is documented in `docs/BRANCH_POLICY.md`: focused implementation branches feed `next`, then protected `main`. Repository-admin branch migration remains an external operation and is not performed implicitly.
- Before deleting or redirecting a compatibility path, add behavior-equivalent tests and pass the relevant acceptance matrix.
- Before claiming a model or hardware tier ready, retain a matching real-inference validation receipt; installation or mocked tests alone are insufficient.
- Every project migration creates a backup, preserves extensions, has rollback notes, and is exercised against legacy fixtures.

## Ordered implementation boundary

1. Finish remaining Phase 1 hardware, renderer, time, and event contracts.
2. Stabilize the active Phase 2 sample-accurate edit/marker/snap work before building dependent features.
3. Build Phase 3 import/probe/pool/cache foundations.
4. Establish the headless Phase 4 transport/audio boundary before mixer, plugins, or remote controls.
5. Preserve the implemented Director, Hunyuan, LTX, and Director Review flows while closing their real-runtime and queue-to-timeline acceptance gaps.
6. Implement provider normalization, remote controls, and professional post features only on stable timeline, transport, mixer, and media contracts.
