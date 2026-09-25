# Hybrid WSL2 Execution Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep one authoritative EDMG Studio FastAPI backend on Windows for WinUI 3 and Electron while delegating only Linux-first GPU/model workloads to managed WSL2 workers.

**Architecture:** Windows remains the control plane and owns API identity, projects, revisions, jobs, cancellation, scheduling, authentication, staging, validation, and publication. WSL2 is an execution plane reached through typed, immutable job manifests; it may read staged inputs and write attempt-scoped results, but it never mutates the authoritative project directly. The existing external-backend mode remains a separate deployment profile rather than being mixed with local WSL worker mode.

**Tech stack:** WinUI 3/.NET, Electron/React/TypeScript, FastAPI/Pydantic/Python 3.12, SQLite job store, `uv` 0.11.28, WSL2, CUDA, PyTorch, TensorRT, NCCL, FFmpeg/ffprobe, pytest, MSTest, Vitest.

**Spec:** This file implements the approved architecture decision in [Architecture decision](#architecture-decision). It must also preserve the acceptance criteria in `docs/DWCT-Studio-Project-Blueprint.md`, `blueprint/WINUI3_CONSOLIDATED_BLUEPRINT.md`, `blueprint/planning.md`, `studio/edmg-studio-winui/ChatLog3.md`, and `studio/edmg-studio-winui/ChatLog4.md`. The optional workstation references `C:\Users\user\Downloads\ChatLog5.md` and `C:\Scripts\EDMG_Studio_Master_Blueprint_AI_DAW_Timeline.md` were absent when this plan was written; their absence must not block implementation, but an implementer should check again before changing renderer architecture.

## Architecture decision

```text
WinUI 3  ─────┐
              ├──► One canonical FastAPI backend on Windows
Electron ─────┘                 │
                               ├── Windows-native workers
                               │   ├── project and storage management
                               │   ├── audio, FFmpeg, Whisper/Qwen where appropriate
                               │   ├── Windows TensorRT, Torch, and DirectML
                               │   └── lifecycle, health, scheduling, and publication
                               │
                               └── WSL2 Linux workers
                                   ├── HunyuanVideo-1.5
                                   ├── Linux-only or Linux-preferred runtimes
                                   ├── NCCL/multi-GPU execution
                                   └── future Linux-first model engines
```

The product supports three profiles:

| Profile | Backend | Workers | Intended audience |
| --- | --- | --- | --- |
| Standard | Windows | Windows-native; WSL capability may be absent | Normal packaged Studio users |
| Hybrid GPU | Windows | Windows plus managed WSL2 workers | Recommended AI workstation profile |
| External Linux | Linux workstation or server | Workers managed by that external backend | Render nodes, remote studios, and cloud systems |

Hybrid GPU is the recommended workstation profile. Standard must remain fully usable when WSL is absent. External Linux remains an explicit absolute HTTP(S) backend target and is not treated as a local worker.

## Global constraints

- WinUI and Electron always use one backend URL and the same API contracts.
- The Windows backend is the only authority for projects, settings, revisions, jobs, authentication, cancellation, retries, and output publication in Standard and Hybrid GPU profiles.
- Preserve all existing project data, Director/Reactive Lab drafts, reviewed camera and motion keyframes, render-profile compatibility, cache identities, and old request defaults.
- Preserve current dirty work. Before each task, run `git status --short --branch`; do not overwrite or stage unrelated paths.
- Coordinate with `STUDIO_PROGRESS.md`. Visual Studio Copilot owns its Implementer section and Codex owns its Reviewer section.
- Do not synchronize dependencies unless the task explicitly requires it. Use the pinned `uv` project and `--frozen --no-sync` validation commands.
- Automatic accelerator selection remains GPU-first. CPU execution requires explicit opt-in and is never a silent fallback from a requested CUDA, TensorRT, WSL, or external runtime.
- A WSL failure disables only the affected Linux execution targets. It must not prevent Studio startup, project editing, supported Windows analysis, or supported Windows rendering.
- Large Linux model assets and caches should live in the WSL ext4 filesystem. Windows remains authoritative for Studio projects, job records, and published outputs.
- A WSL worker receives an immutable manifest and writes only to its assigned attempt staging directory.
- An obsolete, canceled, or retried attempt must never publish output or overwrite a newer attempt.
- Windows and WSL GPU indices are separate namespaces. Resolve a physical-device identity from live inventory; never infer that `cuda:1` on Windows is the same device as WSL index `1`.
- Central scheduling must prevent uncoordinated Windows and WSL workers from overcommitting the same physical GPU.
- Runtime state must distinguish installed, reachable, GPU-visible, model-present, launchable, generation-started, artifact-validated, and runtime-qualified states.
- `runtime_ready` requires receipt-backed runtime evidence at the required validation level. A successful probe, process start, model load, or API response is not sufficient.
- Preserve a single canonical internal renderer. Do not create a second render pipeline for WSL.
- Bind local worker control channels to loopback. Do not expose an unauthenticated WSL service on the LAN.
- Packaged WinUI must retain its package-relative, fail-closed production Windows backend. WSL is an optional execution capability, not a package bootstrap requirement.
- The Windows backend must remain functional if WSL is stopped after Studio launches.
- New API fields must be additive and carry defaults that preserve legacy clients and render-cache compatibility.
- Never add `runtime: null`, `execution_environment: null`, or equivalent absent values to legacy fingerprints.

## Non-goals

- Moving the canonical FastAPI backend, job database, or project store into WSL.
- Letting WinUI or Electron invoke model workers directly.
- Running a separate backend per UI client.
- Replacing external-backend mode with WSL worker mode.
- Requiring WSL for non-Linux Studio operations.
- Sharing mutable project folders with a Linux worker as its primary protocol.
- Claiming all models should move to Linux; placement remains capability- and policy-driven.
- Implementing arbitrary remote worker clustering in this milestone.

## Review focus

Every item below must be covered by the owning task's tests:

1. **WSL disappears during a running attempt:** the attempt fails with a typed environment-unavailable result, retains logs, releases its GPU lease, and cannot publish partial output.
2. **Windows and WSL enumerate the same physical GPU differently:** scheduling uses UUID/PCI identity mapping rather than matching numeric indices.
3. **A canceled attempt finishes late:** the publication guard rejects its result and the newer attempt remains authoritative.
4. **A legacy client omits execution fields:** the backend preserves current automatic routing and cache fingerprints.
5. **A malicious or corrupt manifest/result escapes staging:** canonical path checks reject traversal, external absolute paths, cross-project publication, and mismatched manifest or attempt IDs.

## Target file map

The implementer must confirm exact line numbers against the current checkout before editing. The listed paths define ownership and intended responsibility.

### Backend files to create

- `studio/edmg-studio/python_backend/edmg_studio_backend/execution/contracts.py` — enums and versioned immutable execution manifest/result contracts.
- `studio/edmg-studio/python_backend/edmg_studio_backend/execution/inventory.py` — Windows and WSL GPU discovery plus physical-device reconciliation.
- `studio/edmg-studio/python_backend/edmg_studio_backend/execution/policy.py` — deterministic environment selection with explicit failure reasons.
- `studio/edmg-studio/python_backend/edmg_studio_backend/execution/staging.py` — attempt directory creation, safe path translation, input hashing, and result admission.
- `studio/edmg-studio/python_backend/edmg_studio_backend/execution/wsl.py` — bounded `wsl.exe` command execution, cancellation, timeout, logging, and process-tree shutdown.
- `studio/edmg-studio/python_backend/edmg_studio_backend/execution/dispatcher.py` — one dispatch interface for Windows and WSL execution adapters.
- `studio/edmg-studio/python_backend/edmg_studio_backend/execution/__init__.py` — public execution-plane exports only.
- `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_execution_contracts.py`
- `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_execution_inventory.py`
- `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_execution_policy.py`
- `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_execution_staging.py`
- `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_execution_wsl.py`
- `studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_execution_dispatcher.py`

### Backend files to modify

- `studio/edmg-studio/python_backend/edmg_studio_backend/schemas.py` — additive request fields and validation.
- `studio/edmg-studio/python_backend/edmg_studio_backend/contracts/v1.py` — execution data returned with jobs.
- `studio/edmg-studio/python_backend/edmg_studio_backend/store/jobs.py` — persist resolved execution data without changing job authority.
- `studio/edmg-studio/python_backend/edmg_studio_backend/services/render_settings.py` — profile and routing preferences.
- `studio/edmg-studio/python_backend/edmg_studio_backend/services/model_runtime_registry.py` — layered capability/readiness records.
- `studio/edmg-studio/python_backend/edmg_studio_backend/services/model_load_coordinator.py` — cross-environment physical-GPU leases.
- `studio/edmg-studio/python_backend/edmg_studio_backend/services/internal_video_models.py` — adapt the existing Hunyuan WSL runner to the execution interface rather than replacing it wholesale.
- `studio/edmg-studio/python_backend/edmg_studio_backend/services/internal_video.py` — consume resolved dispatch and preserve existing renderer semantics.
- `studio/edmg-studio/python_backend/edmg_studio_backend/revisions.py` — admit validated external-attempt results through existing publication guards.
- `studio/edmg-studio/python_backend/edmg_studio_backend/api/runtime.py` and `api/routers.py` — runtime profile, inventory, probe, and health endpoints.
- `studio/edmg-studio/python_backend/edmg_studio_backend/app.py` — composition wiring only; keep new implementation details in focused modules.

### WinUI files to create or modify

- Create `studio/edmg-studio-winui/src/EdmgStudio.Core/Models/ExecutionPlaneModels.cs` — API models and presentation state.
- Create `studio/edmg-studio-winui/src/EdmgStudio.Core/Models/ExecutionPlanePresentation.cs` — pure mapping from backend state to Ready/Warning/Blocked UI.
- Modify `studio/edmg-studio-winui/src/EdmgStudio.Core/Models/OperationRuntimeOptions.cs` and `InternalVideoRenderRequestBuilder.cs` — request-scoped execution preference.
- Modify `studio/edmg-studio-winui/Pages/SettingsPage.xaml` and `.xaml.cs` — Standard/Hybrid GPU/External Linux selection and diagnostics.
- Modify `studio/edmg-studio-winui/Pages/ModelsPage.xaml` and `.xaml.cs` — layered WSL/model readiness and probe actions.
- Modify `studio/edmg-studio-winui/Pages/RenderPage.xaml` and `.xaml.cs` — effective environment, physical GPU, and fallback/blocker disclosure.
- Add focused tests under `studio/edmg-studio-winui/tests/EdmgStudio.Core.Tests/ExecutionPlane*Tests.cs` and extend request-builder tests.

### Electron files to create or modify

- Modify `studio/edmg-studio/src/shared/api/contracts.ts` — shared execution-plane types.
- Create `studio/edmg-studio/src/components/ExecutionPlaneStatus.tsx` — reusable status component.
- Modify `studio/edmg-studio/src/pages/Settings.tsx`, `Models.tsx`, and `Render.tsx` — parity with the backend contract without adding a second launcher.
- Add `studio/edmg-studio/src/test/ExecutionPlaneStatus.test.tsx` and extend Settings, Models, Render, and API contract tests.

### Packaging and documentation files to modify

- Modify the existing packaged-backend manifest/build inputs under `studio/edmg-studio-winui/packaging/` only after locating the active manifest path from the project file.
- Modify `studio/edmg-studio/launcher_env.defaults.json` and the relevant documented settings schema only if new defaults are required.
- Create `docs/HYBRID_WSL2_EXECUTION_PLANE.md` for operator setup, diagnostics, storage placement, and recovery.
- Update `docs/STUDIO_ACCELERATOR_POLICY.md` to explain environment selection separately from accelerator selection.

## Public contracts

Use these exact names consistently across tasks unless an existing public contract already supplies an equivalent name.

```python
ExecutionEnvironment = Literal["auto", "windows", "wsl", "external"]
ResolvedExecutionEnvironment = Literal["windows", "wsl", "external"]
RuntimeProfile = Literal["standard", "hybrid_gpu", "external_linux"]

class ExecutionPreference(BaseModel):
    environment: ExecutionEnvironment = "auto"
    gpu_device_id: str | None = None
    allow_environment_fallback: bool = True

class PhysicalGpu(BaseModel):
    device_id: str
    name: str
    uuid: str | None = None
    pci_bus_id: str | None = None
    memory_total_bytes: int
    windows_index: int | None = None
    wsl_index: int | None = None

class ExecutionManifest(BaseModel):
    schema_version: Literal[1] = 1
    project_id: str
    job_id: str
    attempt: int
    engine: str
    environment: ResolvedExecutionEnvironment
    physical_gpu_device_ids: list[str]
    input_root: str
    output_root: str
    inputs: list[ManifestArtifact]
    parameters: dict[str, JsonValue]
    cancel_token_path: str

class ExecutionResult(BaseModel):
    schema_version: Literal[1] = 1
    project_id: str
    job_id: str
    attempt: int
    environment: ResolvedExecutionEnvironment
    status: Literal["succeeded", "failed", "canceled"]
    artifacts: list[ResultArtifact]
    receipts: list[ResultArtifact]
    error: ExecutionFailure | None = None
```

The JSON representation uses `snake_case`, matching the Python API. C# and TypeScript models map these names explicitly. `execution_preference` is omitted when the caller accepts legacy automatic behavior. Resolved execution data belongs in job status and receipts but must not silently alter legacy render fingerprints.

Typed failures use stable codes:

- `EXECUTION_ENVIRONMENT_UNAVAILABLE`
- `EXECUTION_ENVIRONMENT_NOT_SUPPORTED`
- `EXECUTION_GPU_NOT_VISIBLE`
- `EXECUTION_GPU_BUSY`
- `EXECUTION_MANIFEST_INVALID`
- `EXECUTION_RESULT_INVALID`
- `EXECUTION_WORKER_TIMEOUT`
- `EXECUTION_WORKER_EXITED`
- `EXECUTION_ATTEMPT_OBSOLETE`
- `EXECUTION_PUBLICATION_REJECTED`

## Task 1: Freeze the baseline and record compatibility fixtures

**Files:**

- Create: `studio/edmg-studio/python_backend/edmg_studio_backend/tests/fixtures/execution_plane/legacy_internal_video_request.json`
- Create: `studio/edmg-studio/python_backend/edmg_studio_backend/tests/fixtures/execution_plane/legacy_job_response.json`
- Test: existing schema, job-store, render-settings, runtime-registry, Hunyuan, and client contract suites

**Produces:** A candidate-bound baseline and legacy payload fixtures that later tasks must keep valid.

- [ ] Record `git rev-parse HEAD`, `git status --short`, `git diff --name-only`, UTC time, and current implementer-owned paths in a task evidence directory outside tracked source.
- [ ] Re-read `STUDIO_PROGRESS.md` immediately before starting and do not edit files listed by another active implementer until their checkpoint is complete.
- [ ] Capture representative legacy request and job-response JSON without new execution fields.
- [ ] Run the focused baseline without synchronization:

```powershell
uv run --project studio/edmg-studio/python_backend --frozen --no-sync --group test python -m pytest `
  studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_job_store.py `
  studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_jobs_router_contract.py `
  studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_render_settings.py `
  studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_model_runtime_registry.py `
  studio/edmg-studio/python_backend/edmg_studio_backend/tests/test_internal_video_models.py -q
```

- [ ] Run the WinUI request/runtime baseline and the Electron API-contract baseline.
- [ ] Save command, working directory, exit code, counts, commit, dirty-state hash, and log path. Do not label historical results as current baseline evidence.
- [ ] Commit only the fixtures and evidence index after confirming no implementer-owned files are staged.

## Task 2: Add immutable execution contracts

**Files:** Create `execution/contracts.py`; modify `schemas.py` and `contracts/v1.py`; add `test_execution_contracts.py`.

**Consumes:** Existing `project_id`, `job_id`, `attempt`, Pydantic contract conventions, and JSON serialization rules.

**Produces:** `ExecutionPreference`, `ExecutionManifest`, `ExecutionResult`, `ExecutionFailure`, `ManifestArtifact`, `ResultArtifact`, and their enums.

- [ ] Write failing tests proving that valid manifests round-trip, model instances are frozen, unknown schema versions fail closed, paths must be relative to their declared roots, artifact hashes require lowercase SHA-256, and result identity must match the manifest.
- [ ] Add a legacy test proving a request without `execution_preference` produces the exact pre-change normalized payload and fingerprint input.
- [ ] Run `test_execution_contracts.py` and confirm the new imports or fields fail before implementation.
- [ ] Implement the contracts with `ConfigDict(frozen=True, extra="forbid")`; use discriminated fields and bounded strings/lists rather than open arbitrary objects except for renderer parameters already accepted by existing schemas.
- [ ] Add the optional request field with exclusion-on-absence behavior. Do not serialize a null field into legacy requests.
- [ ] Re-run the focused tests and schema import test.
- [ ] Commit contracts and tests as one isolated change.

## Task 3: Resolve runtime profile and execution policy

**Files:** Create `execution/policy.py`; modify `services/render_settings.py`; add `test_execution_policy.py` and focused render-settings tests.

**Consumes:** Requested renderer/model, explicit execution preference, runtime profile, runtime registry capability, and live inventory.

**Produces:**

```python
def resolve_execution_environment(
    request: ExecutionRequestContext,
    settings: ExecutionSettings,
    capabilities: ExecutionCapabilities,
) -> ExecutionResolution
```

- [ ] Write table-driven failing tests for Standard, Hybrid GPU, and External Linux across `auto`, `windows`, `wsl`, and `external` preferences.
- [ ] Pin rules: explicit supported selection wins; explicit unsupported selection fails; Hunyuan selects WSL when available in Hybrid GPU; Windows-capable engines remain Windows by default; Standard never starts WSL automatically; External Linux means the UI connects to another backend and cannot be selected as a local worker.
- [ ] Test that `allow_environment_fallback=False` rejects any environment change and that fallback never changes an explicit GPU request into CPU execution.
- [ ] Implement a pure policy function with reason codes and no process probes.
- [ ] Expose saved `runtime_profile` and model-specific environment preferences through render settings while preserving old settings files.
- [ ] Re-run tests and commit.

## Task 4: Build physical GPU inventory and reconciliation

**Files:** Create `execution/inventory.py`; modify `services/model_runtime_registry.py`; add `test_execution_inventory.py`.

**Produces:**

```python
def discover_windows_gpus(run: CommandRunner) -> list[GpuObservation]
def discover_wsl_gpus(run: CommandRunner, distro: str) -> list[GpuObservation]
def reconcile_physical_gpus(
    windows: Sequence[GpuObservation],
    wsl: Sequence[GpuObservation],
) -> list[PhysicalGpu]
```

- [ ] Write failing parser tests using saved `nvidia-smi --query-gpu=index,name,uuid,pci.bus_id,memory.total --format=csv,noheader,nounits` output for Windows and WSL.
- [ ] Test reordered indices with matching UUIDs, UUID absence with normalized PCI fallback, duplicate/ambiguous identity, WSL exposing fewer GPUs, command timeout, missing distribution, and no NVIDIA hardware.
- [ ] Implement bounded discovery without importing CUDA frameworks into the API process.
- [ ] Reconcile by normalized UUID first, normalized PCI bus ID second, and never by numeric index alone.
- [ ] Return ambiguous devices as unavailable for cross-environment scheduling with an actionable reason.
- [ ] Extend runtime-registry output with separate Windows and WSL observations plus reconciled physical IDs.
- [ ] Re-run focused tests and commit.

## Task 5: Extend centralized GPU leases across Windows and WSL

**Files:** Modify `services/model_load_coordinator.py`; add focused cases to `test_model_load_coordinator.py`.

**Consumes:** Stable `PhysicalGpu.device_id` values from Task 4.

**Produces:**

```python
@contextmanager
def gpu_execution_lease(
    device_ids: Sequence[str],
    *,
    job_id: str,
    attempt: int,
    cancel_check: Callable[[], bool],
    timeout_seconds: float,
) -> Iterator[GpuLease]:
```

- [ ] Write failing multi-process tests proving Windows and simulated WSL contenders for the same physical UUID cannot overlap.
- [ ] Test deterministic sorted multi-GPU acquisition, cancellation while waiting, timeout, stale-owner recovery, release on exception, and two unrelated physical GPUs running concurrently.
- [ ] Keep the existing model-load lock behavior compatible; layer physical-GPU leases around execution rather than replacing model cache/build coordination.
- [ ] Persist lease metadata outside project data with atomic create/replace and owner liveness information.
- [ ] Ensure a killed WSL worker cannot strand the lease beyond its bounded recovery period.
- [ ] Re-run coordinator and model-worker dispatch tests and commit.

## Task 6: Implement safe attempt staging and result admission

**Files:** Create `execution/staging.py`; modify `revisions.py`; add `test_execution_staging.py` and extend `test_revision_publication_contract.py`.

**Consumes:** Existing `.job-staging/<job>/attempt-<n>` layout and job-store publication guard.

**Produces:**

```python
def prepare_execution_attempt(...) -> PreparedExecutionAttempt
def admit_execution_result(
    prepared: PreparedExecutionAttempt,
    result_path: Path,
    *,
    publication_guard: PublicationGuard,
) -> AdmittedExecutionResult
```

- [ ] Write failing tests for immutable input copies/links, SHA-256 verification, safe relative paths, Windows-to-WSL path translation, output containment, symlink/reparse-point escape, manifest identity mismatch, obsolete attempt, cancellation, cross-project output, and duplicate admission.
- [ ] Test the Review Focus case where a canceled old worker returns after a retry; admission must reject it without modifying published media or project revision.
- [ ] Prepare manifests using only attempt-scoped input/output roots. Never pass the mutable project root as the worker output root.
- [ ] Validate every declared artifact exists, is a regular file, remains below output root after canonicalization, matches its hash and media constraints, and belongs to the active attempt.
- [ ] Feed admitted artifacts into existing revision/publication mechanisms; do not invent parallel publication logic.
- [ ] Re-run staging, revision, and job-store tests and commit.

## Task 7: Add a bounded WSL process transport

**Files:** Create `execution/wsl.py`; add `test_execution_wsl.py`.

**Produces:**

```python
class WslExecutionTransport:
    def probe(self, distro: str, timeout_seconds: float) -> WslProbeResult: ...
    def execute(
        self,
        prepared: PreparedExecutionAttempt,
        command: Sequence[str],
        cancellation: CancellationToken,
    ) -> ExecutionProcessResult: ...
```

- [ ] Write failing tests around a fake process runner for argument preservation, no shell interpolation, UTF-8 logs, bounded stdout/stderr capture, cancellation, timeout, process-tree termination, nonzero exit, WSL shutdown, missing distro, and delayed result-file creation.
- [ ] Invoke `wsl.exe --distribution <name> --exec ...` with an argument array. Do not construct a shell command from user/model input.
- [ ] Pass the manifest path as a single translated path; the Linux entry point reads all remaining inputs from the manifest.
- [ ] Write stdout/stderr to attempt-owned logs and return their paths in the failure receipt.
- [ ] On cancellation, create the manifest's cancellation token, request graceful termination, then terminate the owned WSL process tree after a bounded grace period.
- [ ] Treat WSL disappearance as `EXECUTION_ENVIRONMENT_UNAVAILABLE`; release leases and retain staging/logs for diagnosis.
- [ ] Re-run tests and commit.

## Task 8: Adapt Hunyuan to the execution-plane interface

**Files:** Modify `services/internal_video_models.py`, `services/internal_video.py`, and relevant Hunyuan/runtime tests; create a small Linux entry point only if the existing worker cannot accept a manifest cleanly.

**Consumes:** Execution resolution, prepared attempt, GPU lease, WSL transport, and existing Hunyuan configuration.

**Produces:** A `WslHunyuanExecutionAdapter` behind the same dispatcher interface used by Windows adapters.

- [ ] Wait for or coordinate around current in-flight edits to `internal_video.py` and `internal_video_models.py`; rebase the task on the saved implementer checkpoint rather than overwriting it.
- [ ] Write failing adapter tests that preserve existing T2V/I2V behavior, configured distro/model paths, multi-GPU NCCL invocation, primary-GPU retry for recognized distributed CUDA failures, motion receipts, and cancellation.
- [ ] Test that an unrelated worker failure remains fail-closed and does not trigger a broad fallback.
- [ ] Replace direct project mutation with manifest inputs and attempt output while retaining the existing Hunyuan runner's proven Linux environment.
- [ ] Acquire physical GPU leases before model launch and include Windows/WSL index mapping plus UUIDs in the runtime receipt.
- [ ] Keep the recognized one-time primary-GPU retry and preserve distributed logs from the first attempt.
- [ ] Require ffprobe-validated video/audio streams, source/model/motion/segment receipts, and project-output admission before reporting a final render.
- [ ] Re-run Hunyuan, internal-video, staging, coordinator, and runtime-registry tests and commit.

## Task 9: Add a single execution dispatcher and job persistence

**Files:** Create `execution/dispatcher.py`; modify `store/jobs.py`, `contracts/v1.py`, `app.py`, and job/router/worker tests.

**Produces:**

```python
class ExecutionDispatcher:
    def resolve(self, context: ExecutionRequestContext) -> ExecutionResolution: ...
    def dispatch(self, context: ExecutionRequestContext) -> ExecutionResult: ...
```

- [ ] Write failing tests proving Windows, WSL, and external resolutions use one dispatch entry point while job ownership remains in the Windows store for Standard/Hybrid profiles.
- [ ] Persist `requested_environment`, `resolved_environment`, `physical_gpu_device_ids`, `worker_runtime`, and `resolution_reason` as additive job metadata.
- [ ] Test migration of an old SQLite jobs table and round-trip of old rows without execution metadata.
- [ ] Test retry behavior: a retry re-resolves live capability, records a new attempt resolution, and cannot be overwritten by the old attempt.
- [ ] Wire the dispatcher at the existing worker boundary in `app.py`; keep routing, staging, and adapter details out of the monolithic app module.
- [ ] Keep external-backend mode outside local dispatch. A Windows control plane must not pretend an external backend is one of its child workers.
- [ ] Re-run job-store, jobs-router, model-worker dispatch, execution, and legacy fixture tests and commit.

## Task 10: Expose truthful runtime profile and readiness APIs

**Files:** Modify `api/runtime.py`, `api/routers.py`, `services/model_runtime_registry.py`, schemas/contracts, and API tests.

**Produces:**

- `GET /v1/execution/profile`
- `PUT /v1/execution/profile`
- `GET /v1/execution/inventory`
- `POST /v1/execution/wsl/probe`
- additive execution fields on job and renderer readiness responses

- [ ] Write failing API tests for authenticated mutation, unauthenticated health-safe summaries, Standard without WSL, healthy Hybrid GPU, broken distro, GPU-not-visible, model-missing, launchable-but-unqualified, and receipt-qualified states.
- [ ] Return separate booleans or states for `wsl_installed`, `distribution_running`, `worker_environment_present`, `gpu_visible`, `model_installed`, `worker_launchable`, `generation_started`, `artifact_validated`, and `runtime_qualified`.
- [ ] Ensure the probe endpoint is bounded, cancellation-aware, and does not download models, synchronize dependencies, or run inference.
- [ ] Include actionable blocker codes/messages without leaking tokens, credentials, private paths unnecessarily, or worker environment variables.
- [ ] Preserve existing Hunyuan configuration endpoints as compatibility aliases or adapters until both clients have migrated.
- [ ] Re-run API, security, model-registry, and contract tests and commit.

## Task 11: Add WinUI runtime-profile and execution UX

**Files:** Create `ExecutionPlaneModels.cs` and `ExecutionPlanePresentation.cs`; modify Settings, Models, Render, and request models/builders; add focused Core tests.

**Consumes:** Task 10 API contracts.

**Produces:** Native controls for profile selection, effective routing, readiness layers, GPU mapping, and actionable blockers.

- [ ] Write C# contract parsing tests using saved backend JSON for all profiles and readiness states, including unknown additive fields.
- [ ] Write pure presentation tests for Ready, Warning, and Blocked mappings, with distinct text for installed, launchable, and runtime-qualified.
- [ ] Extend request-builder tests: omitted preference stays omitted; explicit Windows/WSL selection serializes correctly; no-fallback is retained; CPU is never silently substituted.
- [ ] Add Settings profile controls with **Standard**, **Hybrid GPU (recommended for AI workstations)**, and **External Linux backend**. Keep external URL configuration separate from WSL worker settings.
- [ ] Add Models diagnostics for distro, Linux model/cache path, GPU mapping, worker environment, last probe, and last qualification receipt.
- [ ] Add Render disclosure for requested/effective environment, selected physical GPU(s), Windows/WSL indices, fallback policy, and blockers before submission.
- [ ] Do not let WinUI launch a worker directly; every operation goes through the canonical backend.
- [ ] Run focused Core tests, then the full Core suite and Release x64/XAML build. Record build success separately from UI/runtime qualification.
- [ ] Commit the WinUI slice only after resolving overlap with any active Render-page implementation.

## Task 12: Add Electron contract and UX parity

**Files:** Modify shared API contracts and Settings/Models/Render; create `ExecutionPlaneStatus.tsx` and tests.

**Consumes:** The same Task 10 API contracts used by WinUI.

- [ ] Write Vitest contract tests using the same logical fixtures as the WinUI tests.
- [ ] Add a reusable status component that presents the profile, effective environment, GPU mapping, readiness layers, and blocker actions.
- [ ] Add request controls with the same defaults and fallback semantics as WinUI.
- [ ] Keep backend URL resolution unchanged: Electron connects to one backend and never starts its own WSL execution service.
- [ ] Verify simultaneous WinUI/Electron clients see the same job ID, attempt, execution environment, cancellation state, and published output through API tests or a deterministic integration harness.
- [ ] Run `pnpm exec vitest run` for the focused files with `--maxWorkers=1`, then `pnpm run test:ui`, `pnpm run typecheck`, and `pnpm run lint` from `studio/edmg-studio`.
- [ ] Commit the Electron slice.

## Task 13: Preserve packaged Windows behavior and add optional WSL setup diagnostics

**Files:** Modify active WinUI packaging inputs, Setup models/page, launcher defaults, and packaging/setup tests after locating the current package manifest path.

- [ ] Write tests proving a packaged Standard install starts and uses its package-relative Windows backend when WSL is absent.
- [ ] Write tests proving selecting Hybrid GPU with WSL absent produces an actionable optional-capability blocker without changing the backend target or corrupting saved settings.
- [ ] Do not install or enable WSL silently. Provide user-invoked guidance and a re-probe action.
- [ ] Keep models/cache path validation aware of Linux paths without treating them as Windows filesystem paths.
- [ ] Preserve the exact required publisher and fail-closed packaged backend discovery.
- [ ] Build the packaged backend and MSIX candidate only from a clean, candidate-bound snapshot after implementation tasks are integrated.
- [ ] Verify installed payload, signature/timestamp, application launch, backend connectivity, and absence-of-WSL Standard behavior as separate gates.
- [ ] Commit packaging/setup changes separately from generated release artifacts.

## Task 14: Add operator documentation and recovery procedures

**Files:** Create `docs/HYBRID_WSL2_EXECUTION_PLANE.md`; modify accelerator policy and relevant READMEs.

- [ ] Document the three profiles and clearly separate backend location from worker execution environment.
- [ ] Document recommended storage: Windows for authoritative projects/published outputs, WSL ext4 for Linux models/cache, attempt staging as the only exchange boundary.
- [ ] Document exact read-only diagnostics for WSL version, distro state, GPU inventory, model environment, backend health, execution inventory, and last qualification receipt.
- [ ] Document recovery for stopped WSL, missing distro, invalid Linux path, GPU mapping ambiguity, stale lease, worker timeout, late obsolete result, and disk pressure.
- [ ] Document that restarting or probing does not prove inference or final output qualification.
- [ ] Document privacy/security: loopback-only worker transport, authenticated backend mutations, redacted logs, and no secrets in manifests.
- [ ] Add a migration note: existing Standard users require no configuration change; existing Hunyuan WSL settings are imported into Hybrid GPU settings without moving project data.
- [ ] Run link/path checks available in the repository and commit documentation.

## Task 15: Run candidate-wide verification and staged rollout

**Files:** No implementation files unless a failing gate identifies a scoped defect. Store logs outside tracked source and update the appropriate handoff section only after re-reading it.

### Stage A: Contract and unit gates

- [ ] Run all new execution-plane tests plus job, revision, coordinator, runtime registry, Hunyuan, render settings, schema, and API security tests.
- [ ] Run WinUI Core tests and Electron focused tests.
- [ ] Confirm legacy JSON fixtures remain byte-equivalent where promised.

### Stage B: Full static/build gates

- [ ] Run frozen aggregate Python scopes:

```powershell
uv run --project studio/edmg-studio/python_backend --frozen --no-sync --group test python scripts/run_pytest_scopes.py
```

- [ ] From `studio/edmg-studio`, run:

```powershell
pnpm run test:ui
pnpm run typecheck
pnpm run lint
```

- [ ] Run the documented WinUI Core suite and Release x64/XAML build without assuming a build proves application launch.

### Stage C: Standard profile acceptance without WSL

- [ ] Stop only task-owned WSL workers; do not terminate unrelated distributions or user processes.
- [ ] Launch the exact candidate WinUI build and its managed Windows backend.
- [ ] Verify project open/edit/save, source upload, supported Windows analysis, job submission/cancellation, output publication, and actionable WSL-unavailable model states.
- [ ] Open Electron against the same backend and verify it observes the same project/job state.

### Stage D: Hybrid GPU WSL acceptance

- [ ] Confirm `wsl --list --verbose`, selected distro, and live WSL `nvidia-smi` inventory before configuring GPU indices.
- [ ] Confirm physical UUID/PCI mapping against Windows inventory.
- [ ] Probe the exact WSL worker environment and model paths without changing dependencies.
- [ ] Run a bounded Hunyuan smoke that produces fresh temporal output and a complete receipt chain.
- [ ] Verify cancellation, WSL shutdown during execution, retry, late obsolete result rejection, lease release, and recovery without restarting the UI.
- [ ] Verify both clients display the same requested/resolved environment, physical GPU identity, job attempt, and final admitted output.

### Stage E: External Linux regression

- [ ] Connect both clients to an authenticated absolute HTTP(S) external backend.
- [ ] Verify the local Windows backend and WSL dispatcher do not start or claim ownership in external mode.
- [ ] Verify server-side folders are not offered as locally openable Windows paths.

### Stage F: Packaged candidate

- [ ] Build the production backend payload and MSIX from the same candidate commit and dirty state.
- [ ] Verify Authenticode signature, timestamp, installed package payload, launch, backend connectivity, Standard-without-WSL operation, optional Hybrid GPU detection, uninstall/reinstall behavior, and upgrade preservation independently.
- [ ] Do not declare Store readiness until candidate-bound Partner Center and lifecycle gates also pass.

## Acceptance criteria

Implementation is complete only when all of the following are true:

- WinUI and Electron use one authoritative backend URL and observe the same project/job truth.
- Standard profile works on a Windows machine where WSL is unavailable.
- Hybrid GPU can execute Hunyuan through WSL2 without granting the worker direct authority over project state.
- Windows/WSL GPU mapping is identity-based and visible in status/receipts.
- Cross-environment leases prevent conflicting use of the same physical GPU.
- Cancellation, retry, timeout, WSL shutdown, and late-result races are receipt-backed and tested.
- Only active-attempt, hash-validated, contained artifacts can be published.
- Legacy requests, job rows, settings, and cache fingerprints remain compatible.
- No requested GPU workload silently falls back to CPU.
- Readiness surfaces distinguish installation, launchability, generation, artifact validation, and qualification.
- Both native WinUI and Electron expose profile, routing, readiness, and blockers; no feature is API-only.
- The packaged Windows product retains its native backend and treats WSL as optional.
- Fresh full-suite, Release x64/XAML build, frontend, Standard runtime, Hybrid WSL runtime, and packaged-candidate evidence are recorded separately.

## Rollback design

- Runtime profile defaults to `standard` when the new setting is absent or invalid.
- The new request field is optional, so older clients continue using current routing.
- Disabling Hybrid GPU stops new WSL dispatches but does not delete Linux models, caches, logs, or settings.
- In-flight jobs retain their recorded attempt resolution; cancel them explicitly rather than changing their environment underneath them.
- Database changes are additive. Older rows remain readable, and rollback code ignores new metadata columns/JSON keys.
- WSL result staging is disposable after retention expires; authoritative projects and published outputs remain on Windows.
- External backend mode is untouched and remains the escape hatch for a full Linux backend deployment.

## Recommended execution order

Execute Tasks 1–10 in order because contracts, identity, leases, staging, and dispatch are safety-critical dependencies. Tasks 11 and 12 may proceed in parallel only after Task 10's API contract is frozen and only if their owned files do not overlap active work. Task 13 follows stable client/backend behavior. Task 14 can begin after contracts are frozen but must be checked against final behavior. Task 15 is always last.

The recommended execution method is **subagent-driven development with a fresh review gate per task**, because this plan crosses Python process isolation, GPU scheduling, persistence, two clients, and packaging; a defect at a contract or publication boundary could corrupt project state or falsely claim runtime readiness. If implementation remains with one engineer, use the same task boundaries and require an independent whole-branch review before candidate qualification.
