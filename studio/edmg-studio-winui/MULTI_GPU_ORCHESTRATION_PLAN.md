# EDMG Studio Multi-GPU Orchestration Plan

**Status:** Proposed implementation plan; no multi-GPU qualification is implied.
**Product surface:** Native WinUI 3 Studio with the shared Python backend.
**Related gate:** Gate E in `..\..\blueprint\WINUI3_CONSOLIDATED_BLUEPRINT.md`.
**Current delivery target:** Phase 0 contracts and deterministic fixtures only; launch behavior remains unchanged.

## 1. Goal

Add an optional, resource-aware multi-GPU execution layer that can assign independent jobs to
different adapters and split a single model only when its runtime genuinely supports distributed or
model-parallel execution. Preserve the current single-GPU path as the safe default and fallback.

This is not a plan to move the entire application onto CUDA. WinUI composition, audio playback,
timeline editing, API routing, project storage, media authorization, and ordinary FFmpeg work remain
on their appropriate UI, CPU, audio, or I/O paths. Hardware encoding can use a GPU independently of
AI model scheduling when its own capability checks pass.

## 2. Current foundation and limits

| Area | Current foundation | Current limit |
| --- | --- | --- |
| Managed Qwen Director | llama.cpp can expose multiple CUDA devices and use layer/tensor splitting. | Device selection and split policy are runtime-specific rather than centrally scheduled. |
| HunyuanVideo-1.5 | The launcher supports distributed PyTorch workers and VAE tile parallelism. | No shared Studio reservation prevents another job from competing for the same adapters. |
| LTX-2.5 | An isolated process can be pinned through `CUDA_VISIBLE_DEVICES`. | One process currently targets one CUDA device; no qualified model split exists. |
| Whisper/audio analysis | Work can be isolated as a job and assigned to an accelerator. | There is no central adapter lease or cross-workload priority policy. |
| ComfyUI | The node pool tracks health, capacity, and in-flight requests. | Node capacity is not unified with local physical-GPU inventory and reservations. |
| Job workers | Backend worker concurrency is configurable. | Concurrency alone can oversubscribe one GPU and cause out-of-memory failures. |
| Native WinUI | Models, Settings, Workspace, and Render already expose runtime and preflight concepts. | There is no unified GPU policy editor, inventory view, assignment status, or lease diagnostic. |

Installation, device detection, successful launch, and deterministic simulation do not establish
real model readiness. Existing Level-3 execution admission and Level-5 smoke qualification remain
separate, and every multi-GPU claim requires matching hardware/runtime evidence.

## 3. User-visible operating modes

The setting is optional and project-overridable. Existing installations migrate to `Automatic`,
which must produce a valid single-GPU plan when no safe multi-GPU plan exists.

| Mode | User intent | Scheduler behavior |
| --- | --- | --- |
| `Automatic` | Use available acceleration safely without manual placement. | Select compatible adapters by capability, free VRAM, reservation state, and workload policy. |
| `Single GPU` | Keep all eligible local model work on one adapter. | Pin child processes to the selected stable adapter ID. |
| `Parallel Jobs` | Maximize throughput across independent scenes and analyses. | Assign separate jobs to separate adapters; do not split one model. |
| `Model Split` | Run a supported model that benefits from or requires several adapters. | Use only a runtime-declared split strategy and validated device set. |
| `Dedicated Roles` | Reserve adapters for Director, analysis, preview, or rendering. | Apply user role bindings before automatic selection. |
| `Custom` | Control device lists, concurrency, priorities, and VRAM reserves. | Validate the policy and reject incompatible or unsafe assignments with actionable diagnostics. |

Global settings provide defaults. Project settings may narrow the allowed devices or mode but must
not silently broaden access. A render request records the resolved policy and assigned devices so a
reopened project or diagnostic report can explain what actually ran.

## 4. Architecture

### 4.1 Control flow

`WinUI policy -> backend GPU inventory -> capability matcher -> reservation scheduler -> runtime adapter -> isolated child process -> telemetry/receipt -> lease release`

The backend is authoritative for inventory, policy validation, assignment, leases, and persisted job
evidence. WinUI owns configuration, approval, status, and diagnostics. Runtime adapters remain
responsible for translating a granted assignment into their native command-line or process model.

### 4.2 Core backend contracts

Add versioned contracts with extension-field preservation where they are persisted:

- `GpuDevice`: stable ID, backend (`cuda`, `directml`, or other qualified backend), display name,
  vendor, total and available memory, compute capability, driver/runtime identity, health, and
  observation timestamp.
- `GpuPolicy`: mode, allowed and excluded device IDs, role bindings, per-device VRAM reserve,
  maximum parallel jobs, sharing policy, and model-split preferences.
- `GpuWorkloadRequest`: job ID, workload kind, runtime, required capabilities, estimated peak VRAM,
  device count, exclusivity, priority, cancellation token, and qualification requirements.
- `GpuAssignment`: selected stable IDs, process-visible indices, strategy, memory budget, scheduler
  reason, warnings, and expiration.
- `GpuLease`: assignment owner, acquisition and heartbeat times, state, release reason, and recovery
  metadata.
- `GpuRuntimeCapability`: supported backends, minimum device count, model-parallel strategies,
  heterogeneous-device support, sharing safety, and evidence level.

Stable IDs must not depend only on CUDA ordinal because ordinals can change after driver updates,
docking, or environment filtering. Runtime adapters map stable IDs to process-local ordinals only
after a lease is granted.

### 4.3 Inventory service

Create a backend inventory provider that:

1. Detects adapters without importing every model runtime into the API process.
2. Records static properties separately from sampled free memory and utilization.
3. Degrades explicitly when vendor tools or runtime libraries are unavailable.
4. Never reports an adapter as model-qualified solely because it was detected.
5. Supports deterministic fixture providers for tests without presenting them as real hardware.
6. Refreshes on demand and at a bounded interval without blocking request or audio-critical threads.

CUDA should be the first fully supported backend because Qwen, Hunyuan, LTX, and the active GPU
environment already use it. Other backends remain capability-gated until their model paths pass the
same acceptance gates.

### 4.4 Reservation scheduler

Implement one process-safe scheduler for local GPU jobs. Its selection order is:

1. Filter by policy, health, runtime compatibility, and required evidence.
2. Exclude devices with conflicting exclusive leases.
3. Preserve configured VRAM for desktop composition, preview, and other dedicated roles.
4. Prefer assignments that fit on one adapter before model splitting unless the user explicitly
   requests `Model Split`.
5. For parallel jobs, select the lowest safe projected load rather than round-robin ordinals.
6. For heterogeneous adapters, use per-device memory weights only when the runtime supports them.
7. Return an actionable blocked result instead of launching an unsafe process.

Leases must be acquired atomically before process launch. They are released on completion,
cancellation, launch failure, or supervised process exit. Heartbeats and bounded expiration recover
leases after backend or worker failure. Recovery must verify process ownership before reclaiming a
lease so a live detached render is not double-scheduled.

The first implementation should keep active lease state in the backend's durable store rather than
in page state or a module-global dictionary. Multiple backend workers must coordinate through the
same transactional store. If reliable cross-process coordination is unavailable, multi-GPU worker
concurrency remains capped at one rather than pretending to be safe.

### 4.5 Runtime adapters

Each adapter consumes `GpuAssignment` and must reject unsupported strategies.

- **Qwen llama.cpp:** preserve layer split and generate `--tensor-split` from assigned-device memory
  weights. Equal splits are allowed only for equivalent devices or an explicit custom policy.
- **Hunyuan:** set the granted device list, launch the matching distributed world size, and keep VAE
  tile parallelism tied to actual ranks. A rank failure fails the render and releases the full lease.
- **LTX:** initially support one assigned GPU per process. Gain multi-GPU throughput through parallel
  scene jobs; do not advertise model splitting until the pinned runtime supports and passes it.
- **Whisper:** initially support one assigned GPU per analysis process, with scheduling based on model
  size and estimated memory. Cache reuse must avoid unnecessary duplicate analysis.
- **ComfyUI:** represent each configured node as a schedulable execution target. Local nodes may map
  to physical GPU IDs; remote nodes expose declared capacity without inventing local device details.
- **Other Diffusers/internal renderers:** remain single-GPU unless they declare and test a concrete
  distributed strategy.

Every child process receives an isolated environment. Do not mutate the backend's global
`CUDA_VISIBLE_DEVICES`. Persist both stable physical IDs and process-visible indices in diagnostics.

### 4.6 Job planning and rendering

Add GPU requirements to the normalized job envelope and renderer preflight. Independent scenes are
the primary unit of parallelism because they provide useful throughput without distributed-model
overhead. Preserve deterministic scene order and artifact lineage when results finish out of order.

The queue must enforce:

- per-device and global concurrency limits;
- cancellation fencing and idempotent publication;
- no duplicate artifact publication after retry;
- project/revision and schedule identity on every result;
- bounded retry only for retryable launch or infrastructure failures, never automatic retry after an
  ambiguous completed inference;
- CPU or external fallback only when the existing user policy permits it.

FFmpeg encoding or muxing is scheduled separately. NVENC, if enabled, declares its own encoder
capacity and VRAM reserve rather than borrowing an AI lease implicitly.

## 5. Native WinUI surfaces

Backend support is incomplete until it is controllable and observable in WinUI.

### Settings > Acceleration

- Show detected adapters, stable identity, memory, backend, health, and qualification status.
- Select the default mode and allowed devices.
- Configure dedicated roles, maximum parallel jobs, and per-device VRAM reserves.
- Validate before saving and provide a `Restore safe automatic defaults` action.
- Clearly separate detected, execution-admitted, and smoke-qualified states.

### Models

- Show each runtime's supported placement strategies and currently selected policy.
- Run model qualification against the exact device set and strategy being qualified.
- Display receipts by runtime fingerprint, model assets, driver/runtime, and assigned devices.
- Keep unsupported model splitting disabled with a reason rather than hiding it.

### Workspace and Render

- Add an acceleration summary to guided preflight: mode, route, proposed devices, estimated memory,
  fallback policy, warnings, and blockers.
- Let users accept an automatic plan or open Settings/Models to resolve it.
- Preserve specialist Render controls for per-job overrides.

### Queue and diagnostics

- Show queued, reserved, running, releasing, and recovered lease states.
- Display assigned devices, runtime strategy, progress, and cancellation state per job.
- Include a copyable diagnostic report with policy, inventory timestamp, assignment reason, and
  relevant log correlation IDs, excluding secrets and private service credentials.

## 6. API and persistence

Add versioned endpoints under the existing backend API conventions:

- `GET /hardware/gpus` for inventory and observation freshness;
- `GET/PUT /settings/gpu-policy` for validated global defaults;
- project-scoped GPU policy read/update endpoints if project overrides are persisted separately;
- `POST /hardware/gpus/plan` for a side-effect-free assignment preview;
- lease and assignment fields on existing job/status/preflight responses;
- an administrative lease diagnostic endpoint that does not expose process secrets.

Use optimistic concurrency for persisted policy changes. Unknown fields survive read/write cycles.
Never accept raw shell arguments, executable paths, or arbitrary environment variables through GPU
policy APIs.

## 7. Delivery phases

### Phase 0 - Contracts and fixtures

- Inventory existing Qwen, Hunyuan, LTX, Whisper, ComfyUI, worker, job, and WinUI preflight paths.
- Define versioned policy, device, workload, assignment, lease, and runtime-capability contracts.
- Add deterministic device fixtures for equal, mixed-memory, missing-tool, unhealthy, and reordered
  adapter scenarios.

**Gate:** Contract serialization, extension preservation, migration, and deterministic policy tests
pass without changing current launch behavior.

### Phase 1 - Inventory and diagnostics

- Implement bounded CUDA inventory probing and explicit unavailable states.
- Add inventory APIs and native Settings read-only inventory UI.
- Add correlation-aware inventory and scheduler logging with no high-frequency log spam.

**Gate:** Adapter reorder and missing-provider tests pass; WinUI XAML compiles; real hardware evidence
is labeled separately from deterministic fixtures.

### Phase 2 - Single-device leases

- Add transactional leases and integrate one single-GPU runtime at a time.
- Start with LTX or Whisper process pinning because the assignment is unambiguous, then cover all
  existing single-device launchers.
- Preserve current behavior when the scheduler feature is disabled.

**Gate:** Concurrent requests cannot acquire conflicting exclusive leases; cancellation, crash,
expiration, and backend restart recover correctly; existing single-GPU regression tests remain green.

### Phase 3 - Parallel jobs

- Make scene and analysis jobs declare resource estimates and priorities.
- Distribute independent jobs across leases while preserving output order, idempotency, and lineage.
- Integrate local and remote ComfyUI targets with explicit capacity boundaries.

**Gate:** Deterministic multi-device tests prove no oversubscription, starvation, duplicate
publication, or leaked leases. A real two-GPU run is required before advertising this mode as
qualified.

### Phase 4 - Supported model splitting

- Adapt Qwen tensor splitting to assigned devices and weighted memory.
- Adapt Hunyuan distributed launch to scheduler grants and full-rank supervision.
- Keep LTX, Whisper, and other runtimes single-device unless separately qualified.

**Gate:** Each advertised model/device topology has a matching Level-5 smoke receipt. Worker or rank
failure releases all devices and produces an actionable failure rather than degraded success.

### Phase 5 - Full native controls

- Complete Settings policy editing, Models capability/qualification, Workspace preflight, Render
  override, Queue occupancy, and diagnostics surfaces.
- Add accessibility names, keyboard navigation, narrow-window behavior, and localization-ready text.

**Gate:** Native UI automation covers policy edit, invalid policy, automatic fallback, blocked
preflight, cancellation, and recovery. Interactive validation is recorded separately.

### Phase 6 - Qualification and rollout

- Run real single-, dual-, and mixed-GPU matrices on supported Windows/CUDA configurations.
- Measure throughput, peak memory, launch overhead, cancellation latency, and desktop responsiveness.
- Add a feature flag and staged rollout; retain immediate return to `Single GPU`.
- Update operator, model, troubleshooting, and release documentation.

**Gate:** No mode is advertised as supported without matching hardware/runtime receipts. Packaging,
clean-machine, upgrade, rollback, and long-render soak evidence are required for release claims.

## 7.1 Phase 0 implementation map

Phase 0 should be a contract-only vertical slice. It must compile and serialize through both backend
and WinUI layers, but it must not probe hardware, acquire leases, alter environment variables, or
change any model launch command.

| Responsibility | Initial path | Required output |
| --- | --- | --- |
| Backend contracts | `studio/edmg-studio/python_backend/edmg_studio_backend/domain/gpu_orchestration.py` | Frozen/versioned device, policy, workload, assignment, lease, capability, warning, and blocked-reason models. |
| Policy normalization | `studio/edmg-studio/python_backend/edmg_studio_backend/services/gpu_policy.py` | Pure validation and default resolution with no hardware or process side effects. |
| Deterministic fixtures | `studio/edmg-studio/python_backend/edmg_studio_backend/tests/fixtures/gpu_inventory.py` | Named single, equivalent-dual, mixed-memory, reordered, stale, unhealthy, and unavailable-provider inventories. |
| Backend contract tests | `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_gpu_orchestration_contracts.py` | Round-trip, migration, validation, stable-ID, deterministic-plan, and extension-preservation coverage. |
| Native DTOs | `studio/edmg-studio-winui/src/EdmgStudio.Core/Models/GpuOrchestrationModels.cs` | JSON-compatible records matching backend wire names and nullable semantics. |
| Native contract tests | `studio/edmg-studio-winui/tests/EdmgStudio.Core.Tests/GpuOrchestrationModelsTests.cs` | Representative payload deserialization, unknown-field tolerance, enum fallback, and round-trip coverage. |

Do not add Phase 0 contracts to the general-purpose `BackendModels.cs`; the orchestration boundary is
large enough to remain independently reviewable. Do not add API routes or visible controls until the
contract tests establish a stable wire format.

### Phase 0 defaults and invariants

- `schema_version` starts at `1` on every persisted envelope. Readers reject unsupported future major
  versions but preserve unknown object members for a same-major read/write cycle.
- A missing policy resolves to `Automatic`, `maximum_parallel_jobs = 1`, no role bindings, no model
  splitting, and the existing runtime fallback behavior. This is compatibility behavior, not evidence
  that a detected GPU is qualified.
- Stable device IDs are opaque strings. Tests may use fixture IDs such as `cuda:pci-0000-01-00-0`, but
  production ID format is owned by the later inventory provider and is never parsed by policy code.
- Byte counts use non-negative 64-bit integers. Utilization is nullable when unavailable. Timestamps
  are UTC ISO-8601 values. Process-visible ordinals are assignment output, never persisted policy input.
- Policy validation is deterministic for identical policy, inventory snapshot, runtime capability,
  and workload request. Tie-breaking uses stable device ID after all safety and load criteria.
- A blocked plan is a typed result with reason codes and user-facing detail; it is not an exception or
  an empty successful assignment. Programmer errors and malformed contracts remain explicit errors.
- Phase 0 feature state is off by default. No existing Qwen, Hunyuan, LTX, Whisper, ComfyUI, render,
  analysis, or worker path may consume these contracts yet.

### Phase 0 contract decisions

Use string-valued wire enums with explicit unknown handling in WinUI. The initial canonical values are:

- policy mode: `automatic`, `single_gpu`, `parallel_jobs`, `model_split`, `dedicated_roles`, `custom`;
- lease state: `pending`, `reserved`, `running`, `releasing`, `released`, `expired`, `recovered`, `failed`;
- assignment strategy: `single_device`, `parallel_job`, `tensor_split`, `distributed`, `external_node`;
- device health: `healthy`, `degraded`, `unavailable`, `stale`, `unknown`.

`GpuPolicy` contains user intent only. Sampled memory, resolved ordinals, runtime fingerprints, and
qualification receipts belong to inventory, assignment, and evidence records. Project overrides are
represented as restrictions over the global policy; Phase 0 validates that they cannot add devices,
raise concurrency, enable splitting, or weaken qualification requirements beyond the global policy.

### Phase 0 definition of done

1. Backend and native models deserialize the same checked-in representative payloads.
2. Missing-policy migration produces the safe defaults above without modifying current settings.
3. Unknown fields survive backend persisted-envelope round trips and do not break WinUI reads.
4. Reordered fixture ordinals retain the same stable IDs and deterministic assignment choice.
5. Invalid negative memory, duplicate device IDs, contradictory allow/exclude lists, unsupported split
   requests, and project policy broadening return specific validation errors.
6. Existing targeted model-runtime, render-preflight, job-store, API-client, and XAML build checks remain
   green, demonstrating code presence without claiming working GPU integration.
7. No subprocess, CUDA import, dependency synchronization, environment mutation, API route, durable
   lease row, or native control is added in this phase.

## 8. Validation matrix

### Deterministic tests

- Policy migration and unknown-field preservation.
- Stable-ID mapping after CUDA ordinal reorder.
- Equal and heterogeneous VRAM assignment.
- Exclusive versus shareable lease conflicts.
- Atomic acquisition across concurrent workers.
- Lease release after success, cancellation, failed launch, crash, timeout, and backend restart.
- Single-GPU fallback when only one compatible adapter exists.
- Rejection of unsupported model split, unhealthy devices, stale inventory, and unsafe memory plans.
- Out-of-order scene completion with deterministic artifact ordering and no duplicate publication.
- WinUI API serialization, view-model state transitions, XAML compilation, and accessibility metadata.

### Real-hardware qualification

- One supported NVIDIA GPU as the compatibility baseline.
- Two equivalent GPUs for parallel jobs and supported model split.
- Mixed-memory GPUs for weighted assignment and dedicated-role behavior.
- GPU loss or child-process failure during a render.
- Simultaneous Director, Whisper, preview, and render workloads under configured limits.
- Long render with cancellation, restart recovery, and log/receipt inspection.

Record driver, CUDA/runtime, model and package fingerprints, physical device IDs, assignment,
strategy, peak memory, output validity, and artifact hashes. Simulation is never substituted for
real-device evidence.

## 9. Safety and compatibility requirements

- Preserve all current single-GPU environment variables and launch behavior behind an adapter until
  their scheduler replacements pass regression and hardware gates.
- Never synchronize or replace the selected CUDA environment as part of probing or reporting.
- Do not make GPU count, model name, or memory thresholds hard blockers when a valid supported
  single-GPU or external route exists under user policy.
- Keep genuine incompatibilities, missing adapters, invalid configuration, corrupt assets, and
  unsupported compute as blockers.
- Avoid broad exception catches and success-shaped fallbacks; surface scheduler and runtime failures.
- Do not allow GPU probes, telemetry, or lease persistence on audio/render-critical UI threads.
- Do not change deliberate existing device defaults until the migration policy and user override are
  defined and tested.

## 10. Completion criteria

The multi-GPU option is complete when the native Studio can discover and identify supported devices,
persist a validated policy, preview and reserve safe assignments, launch isolated runtime processes,
recover every lease terminal path, report actual assignments in WinUI, and preserve project and
artifact correctness under parallel completion. Existing single-GPU workflows must remain available,
and every advertised model-split or multi-device mode must have a matching real-hardware Level-5
receipt and release evidence.

Until those gates pass, the existing runtime-specific multi-GPU mechanisms remain implementation
foundations rather than a unified or release-qualified whole-Studio feature.
