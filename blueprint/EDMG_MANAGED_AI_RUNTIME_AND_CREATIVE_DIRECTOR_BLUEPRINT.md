# EDMG Studio Managed AI Runtime and Creative Director Blueprint

**Status:** Proposed forward architecture and implementation plan. Nothing in this document, by itself, proves model installation, runtime compatibility, GPU execution, multimodal correctness, production readiness, packaging, or release acceptance.

**Product surface:** Native WinUI 3 EDMG Studio with the shared Python backend and isolated Windows/WSL2/Linux execution workers.

**Primary model policy:** NVIDIA Nemotron 3 Nano Omni is the default Director. NVIDIA Cosmos Reason2 is its optional visual-reasoning specialist. Qwen remains an explicit, user-visible fallback and compatibility route; it is not the automatic default.

**Related plans:**

- `blueprint/WINUI3_CONSOLIDATED_BLUEPRINT.md`
- `blueprint/MULTI_GPU_ORCHESTRATION_PLAN.md`
- `blueprint/EDMG_STUDIO_AUDIO_TO_VIDEO_PRODUCTION_BLUEPRINT.md`
- `blueprint/planning.md`
- `HYBRID_WSL2_EXECUTION_PLANE_IMPLEMENTATION_PLAN.md`

## 1. Executive decision

EDMG Studio must not be designed around a single inference engine. NIM, vLLM, TensorRT-LLM, and direct Transformers are replaceable execution backends, not the product. The product is a local-first, music-aware directing and production environment that understands a complete song, proposes a coherent audiovisual treatment, compiles approved direction into editable production data, executes it through the best qualified runtime and renderer, and records truthful evidence of what happened.

The target architecture is a **Studio-owned managed runtime system**:

```text
Native WinUI Studio
  |
  +-- Unified Workspace and specialist pages
  |
  +-- Music Intelligence and project evidence
  |
  +-- Nemotron Director + Cosmos specialist
  |
  +-- Deterministic DirectorPlan validation/review/apply
  |
  +-- Managed AI Runtime Supervisor
  |     +-- direct Transformers adapter
  |     +-- vLLM adapter
  |     +-- TensorRT-LLM adapter
  |     +-- NVIDIA NIM adapter
  |     +-- Qwen compatibility adapter
  |
  +-- GPU inventory, leases, residency, and telemetry
  |
  +-- Windows / WSL2 / external Linux execution planes
  |
  +-- Render, finishing, validation, and publication
  |
  +-- Runtime receipts and artifact provenance
```

The user chooses the creative objective and, when desired, the model. Studio chooses the runtime, device placement, service lifecycle, and safe fallback according to capabilities and qualification evidence. Endpoint URLs, ports, container names, tensor-parallel flags, and runtime-specific command lines are implementation details. They are available in expert diagnostics but are not normal user configuration.

## 2. Product thesis and differentiation

EDMG Studio must stand out through the combination of capabilities around the models, not merely through access to the models.

### 2.1 Understand the whole song as time

The Studio builds reusable, evidence-backed musical understanding tied to exact project time and source samples:

- waveform and media identity;
- duration, sample rate, channels, and source hash;
- beat, bar, phrase, section, and transition structure;
- onset density, loudness, spectral motion, energy, and silence;
- stems and stem-derived envelopes when available;
- vocal activity, transcript, lyrics, and semantic evidence;
- user annotations and locked musical landmarks;
- provenance for the analyzer and model revisions that produced the evidence.

Director decisions reference that evidence rather than treating the track as a generic attachment. A scene change, camera accent, subject motion, color transition, or cut-density change can be traced to an exact musical range.

### 2.2 Direct instead of vending one opaque result

Nemotron is a creative Director, not an unrestricted timeline editor. It produces a structured proposal. Cosmos supplies specialist evidence. EDMG validates the proposal. The user reviews and approves it. A deterministic compiler applies approved changes through the existing project revision, undo/redo, locking, and recovery systems.

```text
Analyze -> Propose -> Validate -> Review -> Apply -> Edit -> Render -> Verify
```

Generated output cannot bypass review/apply, overwrite locked scenes, silently change exact timing, invent unauthorized paths, or execute arbitrary commands.

### 2.3 Compile creative intent into editable production data

The durable product advantage is the translation from semantic direction into editable structures:

- scenes and exact ranges;
- storyboard shots and continuity constraints;
- camera keys and motion keys;
- Reactive Lab mappings;
- prompt tracks and negative prompts;
- per-scene renderer and model recommendations;
- transition and interpolation policies;
- Story Bible identity and environment locks;
- render manifests and output ownership.

The output is not only an MP4. It is a recoverable, versioned audiovisual production that can be changed without regenerating everything.

### 2.4 Use specialist intelligence with a clear authority model

The authority chain is explicit:

```text
Cosmos observes and advises.
Nemotron directs.
EDMG validates and compiles.
The user approves.
The execution plane renders.
```

Cosmos results are evidence, never project mutations. Nemotron remains authoritative for the proposed Director plan. Neither model can bypass project authorization or the deterministic mutation boundary.

### 2.5 Hide infrastructure without hiding truth

Studio owns runtime complexity while showing truthful status:

- which exact model revision is installed;
- which modalities are qualified;
- which runtime was selected and why;
- which physical GPUs were used;
- whether fallback occurred;
- whether output passed schema, media, motion, and artifact validation;
- what remains installed-only, execution-ready, or runtime-qualified.

This combination of approachable workflow and evidence-grade diagnostics is a core differentiator.

### 2.6 Local-first with optional scale-out

Projects, musical evidence, Director drafts, and timeline state remain local by default. The same immutable execution contracts may later target WSL2, a remote Linux worker, Azure, or another authorized GPU provider without turning the desktop project into a cloud-owned artifact.

## 3. Non-goals

This plan does not make EDMG:

- a generic model-server configuration dashboard;
- a thin wrapper around ComfyUI, NIM, vLLM, or TensorRT-LLM;
- a prompt-to-video vending machine;
- a set of unrelated AI pages with separate project state;
- a benchmark demo that values tokens per second over multimodal correctness;
- a system that silently substitutes a different model or CPU path;
- a public network inference service by default;
- proof that Ampere GPUs support every upstream optimized profile;
- permission to remove Qwen, existing renderers, or working execution paths before migration and rollback gates pass.

## 4. Operating principles

1. **WinUI is the product surface.** Every new managed-runtime capability has a native control, status, action, or diagnostic path.
2. **The backend is authoritative.** Project revisions, model installation, runtime selection, GPU leases, jobs, media authorization, and receipts are backend-owned.
3. **Models and runtimes are separate identities.** Nemotron is a model; vLLM is a runtime. A model may have several qualified runtime routes.
4. **Transport is not configuration.** Loopback HTTP, subprocess IPC, named pipes, and direct Python calls are internal transport choices.
5. **Capabilities are evidence-backed.** Text support does not prove audio, image, video, structured output, cancellation, or multi-GPU support.
6. **Qualification is exact.** Evidence binds model revision, runtime version, dependencies, GPU identity, precision, topology, settings, and smoke input.
7. **Fallback is explicit.** The job records requested, selected, actual, and fallback routes plus the reason.
8. **No implicit CPU fallback for large models.** A GPU admission failure returns an actionable blocked result unless the user explicitly selects a qualified CPU route.
9. **No silent model substitution.** Nemotron failure does not silently become Qwen. Qwen use is explicit or governed by a user-visible policy.
10. **Preserve editability.** Generated output enters versioned drafts and established apply paths.
11. **Preserve active work.** Runtime work must not discard projects, saved drafts, extension fields, render profiles, or unrelated worktree changes.
12. **Security defaults to local isolation.** Managed HTTP runtimes bind to loopback and reject arbitrary file or media access.

## 5. Current baseline and known gap

The repository now contains pinned Studio catalog entries for Nemotron and Cosmos, local installation and license handling, endpoint-settings migration, and a direct Transformers execution path in the isolated Director worker. Nemotron is the configured default and Qwen remains explicitly selectable.

That is the correct compatibility baseline, not the final production runtime. The remaining gaps include:

- the large Nemotron model may be loaded for individual worker jobs rather than held by a supervised persistent service;
- exact live Nemotron and Cosmos installations and multimodal smoke receipts remain environment-dependent;
- runtime selection is not yet unified across Transformers, vLLM, TensorRT-LLM, and NIM;
- lifecycle, internal port, readiness, crash recovery, and residency policy are not yet one backend service;
- model capability and runtime qualification are not yet presented as one consistent Models-page matrix;
- the three RTX A6000s require coordinated allocation with render and analysis workloads;
- simultaneous residency of Nemotron, Cosmos, render models, and preview workloads can overcommit VRAM;
- optimized runtime support for each exact multimodal route must be proven rather than inferred from architecture support.

## 6. Target system architecture

### 6.1 Control flow

```text
WinUI request
  -> backend Director/Model API
  -> capability requirements
  -> model revision resolver
  -> runtime route resolver
  -> execution-plane resolver
  -> GPU lease and residency planner
  -> managed runtime adapter
  -> inference result
  -> schema/security validation
  -> draft persistence
  -> review/apply
  -> runtime receipt and diagnostics
```

### 6.2 Major components

#### Managed Model Registry

Owns stable Studio model IDs, upstream repositories, immutable revisions, licenses, required files, expected model families, modalities, memory guidance, supported runtime candidates, and installation state.

#### Capability Registry

Separates declared support from verified support. It records capability state for each model/runtime/revision/hardware tuple.

#### Runtime Route Resolver

Selects a route only when its required capabilities and evidence level satisfy the job. It returns a reasoned decision, not only a runtime name.

#### Runtime Supervisor

Starts, monitors, reuses, drains, restarts, and stops managed runtimes. It owns hidden ports, working directories, environment variables, container/process identity, logs, readiness, and shutdown fencing.

#### GPU Scheduler and Residency Manager

Builds on the existing multi-GPU and model-load coordination foundations. It allocates stable physical GPU identities, enforces VRAM reserves, prevents incompatible concurrent residency, and distinguishes independent-job parallelism from model splitting.

#### Execution-Plane Adapter

Maps an admitted job to Windows, WSL2, external Linux, or a later cloud worker. It preserves immutable manifests and translates physical GPU identities into environment-local indices.

#### Director Orchestrator

Builds multimodal context, invokes Cosmos when policy calls for it, invokes Nemotron, validates the returned DirectorPlan, attaches provenance, and persists only a draft.

#### Receipt Store

Persists readiness, smoke, execution, fallback, performance, and artifact evidence without converting old evidence into proof for a changed runtime or model.

## 7. Versioned backend contracts

All persisted contracts require an explicit schema version and extension preservation where project compatibility requires it.

### 7.1 Model identity

```json
{
  "schema_version": "1.0",
  "studio_model_id": "hf_nemotron3_nano_omni_30b_a3b_reasoning_bf16",
  "upstream_model_id": "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-BF16",
  "revision": "e5e9932441de940c9a62185c870ea5bcd4cd24e2",
  "family": "nemotron3_nano_omni_moe",
  "modalities": ["text", "audio", "image", "video"],
  "role": "director"
}
```

The Cosmos entry follows the same contract with role `director_specialist`. Qwen entries use role `director_fallback` or `director_compatibility`.

### 7.2 Runtime descriptor

```json
{
  "runtime_id": "vllm-wsl",
  "kind": "vllm",
  "version": "pinned-version",
  "execution_plane": "wsl",
  "transport": "loopback_http",
  "lifecycle": "studio_supervised",
  "network_exposure": "loopback_only",
  "capabilities": {}
}
```

Supported `kind` values initially are `transformers`, `vllm`, `tensorrt_llm`, `nim`, and `qwen_legacy`. Future additions require a new adapter and capability evidence; they do not require changing model identity.

### 7.3 Capability evidence

Each route tracks these independently:

- load;
- text generation;
- structured DirectorPlan output;
- audio input;
- image input;
- video input;
- tool/schema guidance where applicable;
- cancellation;
- streaming;
- long-context behavior;
- single-GPU execution;
- multi-GPU model split;
- concurrent request handling;
- clean unload;
- crash recovery;
- packaged or deployed availability.

States are:

- `unsupported`;
- `unknown`;
- `declared`;
- `installed`;
- `execution_ready`;
- `smoke_qualified`;
- `production_qualified`;
- `quarantined`.

### 7.4 Runtime selection request

```json
{
  "model_id": "hf_nemotron3_nano_omni_30b_a3b_reasoning_bf16",
  "required_capabilities": {
    "text": true,
    "audio": true,
    "structured_output": "director_plan_1_0",
    "cancellation": true
  },
  "preference": "automatic",
  "allow_runtime_fallback": true,
  "allow_model_fallback": false,
  "latency_class": "interactive",
  "project_id": "...",
  "job_id": "..."
}
```

### 7.5 Runtime decision

The decision records considered candidates, rejection reasons, selected route, required GPU assignment, evidence reference, warnings, and whether user confirmation is required.

### 7.6 Runtime receipt

Every real job records:

- project, job, operation, and correlation IDs;
- requested and actual model IDs and revisions;
- requested, selected, and actual runtime routes;
- runtime and dependency versions;
- execution plane;
- physical GPU UUIDs and process-visible indices;
- precision, parallelism, context length, and memory policy;
- input artifact hashes and authorized relative paths;
- timing, token, memory, and cancellation observations;
- fallback chain and reasons;
- schema validation result;
- output artifact identity;
- warnings and qualification level.

Secrets, raw authorization headers, and private tokens are never stored in receipts.

## 8. Runtime adapters

### 8.1 Direct Transformers adapter

Purpose:

- compatibility truth;
- first route for new models;
- custom model and processor code;
- exact multimodal behavior;
- reference output for optimized-route comparisons.

Requirements:

- load only the installed pinned directory with `local_files_only`;
- isolate model code in a worker process;
- set an explicit device map and visible-device set;
- enforce media containment and type/size/duration limits before processing;
- support cancellation by terminating the owned worker when cooperative cancellation is unavailable;
- report load and generation phases separately;
- release CUDA memory and leases on every terminal path;
- never fetch a mutable upstream revision at inference time.

Direct Transformers remains available even after optimized routes ship, but automatic selection should prefer a qualified persistent runtime for repeated interactive Director use.

### 8.2 vLLM adapter

Purpose: likely primary persistent Nemotron runtime after exact qualification.

Responsibilities:

- launch a pinned WSL2/Linux environment or pinned official container;
- use a Studio-selected local model directory or immutable model revision;
- choose tensor parallelism only from a validated physical GPU assignment;
- bind to `127.0.0.1` or private execution-plane networking;
- allocate a hidden port and verify process ownership;
- poll model and readiness endpoints before admitting requests;
- normalize streaming, errors, cancellation, and usage into Studio contracts;
- drain active requests before restart or upgrade;
- keep logs and metrics accessible from Models diagnostics;
- put any remotely reachable deployment behind a hardened authenticated proxy.

The route cannot be promoted from text-only evidence. Nemotron needs independent audio, image, video, and structured-plan qualification. Current vLLM documentation describes OpenAI-compatible serving and warns that built-in API-key protection does not cover every endpoint, so loopback-only is the default security boundary: <https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/>.

### 8.3 TensorRT-LLM adapter

Purpose: NVIDIA-optimized promotion route after compatibility is established.

Responsibilities:

- run in a version-isolated Linux environment;
- preserve the existing separation between TensorRT-LLM's compatible TensorRT version and standalone Windows TensorRT installations;
- verify exact model and modality support;
- record build/quantization/import configuration where applicable;
- validate output against the Transformers reference route;
- use tensor, pipeline, or expert parallelism only when the model/runtime combination supports it;
- support persistent serving through the current recommended TensorRT-LLM serving interface;
- quarantine incompatible engines/checkpoints rather than retrying them indefinitely.

TensorRT-LLM is not considered active merely because its package imports. NVIDIA describes it as an optimized LLM inference toolkit with multi-GPU parallelism, KV-cache management, in-flight batching, CUDA Graphs, and quantization: <https://nvidia.github.io/TensorRT-LLM/overview.html>.

### 8.4 NVIDIA NIM adapter

Purpose: packaged NVIDIA deployment when an exact model/profile/hardware route is supported or locally qualified.

Responsibilities:

- manage container acquisition, license/credential prerequisites, cache mounts, GPU assignment, and image version;
- inspect manifest/profile metadata rather than guessing compatibility;
- use liveness, readiness, metadata, version, and metrics endpoints;
- normalize the OpenAI-compatible inference contract into Studio's internal request and receipt types;
- preserve a non-NIM route when no suitable profile exists;
- never infer A6000 support from support for a different Ampere, Hopper, or Blackwell SKU.

NIM is an optional route, not a mandatory installation dependency. NVIDIA documents NIM's OpenAI-compatible inference and additional management endpoints here: <https://docs.nvidia.com/nim/large-language-models/latest/reference/api-reference.html>.

### 8.5 Qwen compatibility adapter

Qwen remains installable and selectable. Policies:

- it is never an invisible substitute for Nemotron;
- automatic model fallback is off by default;
- a project created with Qwen can reopen and preserve its model identity;
- legacy Qwen runtime settings migrate without being deleted until the user removes them;
- Qwen-specific diagnostics remain available in Models and Settings under a clearly labeled fallback/legacy section;
- removal of a Qwen runtime must not remove projects, Director drafts, or shared analysis.

## 9. Default runtime policy by model

### 9.1 Nemotron

Order after qualification:

1. TensorRT-LLM when the exact required modalities and output contract are production-qualified.
2. vLLM when the exact required modalities and output contract are smoke- or production-qualified.
3. Direct Transformers when locally qualified and sufficient aggregate VRAM is admitted.
4. Block with an actionable result.
5. Offer Qwen only as an explicit user decision.

The initial practical target is persistent vLLM with direct Transformers as the compatibility route. TensorRT-LLM is promoted later based on measured benefit and complete capability parity.

### 9.2 Cosmos Reason2

Initial order:

1. Direct Transformers with exact video preprocessing and 4 FPS sampling.
2. vLLM after visual/video and structured specialist-output parity passes.
3. TensorRT-LLM or NIM only after exact route qualification.

Cosmos is normally loaded on demand and evicted after an idle period. Its unavailability degrades Advanced direction to Nemotron without specialist evidence; it does not automatically replace Nemotron or fail ordinary Standard direction.

### 9.3 Qwen

Use the existing qualified Qwen route selected by the user or by an explicit compatibility policy. Preserve current llama.cpp/TensorRT-LLM behavior and evidence boundaries.

## 10. GPU, memory, and residency policy

### 10.1 Physical identity

Reconcile Windows, WSL2, container, and remote views using stable GPU UUID/PCI identity rather than ordinal alone. Record both the physical ID and runtime-visible index.

### 10.2 Workload classes

- `interactive_director` — high responsiveness; Nemotron requests.
- `specialist_analysis` — Cosmos visual/video analysis.
- `audio_analysis` — Whisper, stems, and signal processing.
- `preview` — still/video preview and UI support.
- `render` — diffusion/video generation.
- `finishing` — decode, encode, optical flow, FRUC, and validation.

### 10.3 Admission

Before launch or model load, the scheduler must account for:

- model weights;
- runtime overhead;
- KV cache or context budget;
- multimodal encoders/processors;
- expected activation peak;
- CUDA Graph reservation where used;
- desktop/preview reserve;
- active leases and resident models;
- render jobs already admitted;
- cleanup uncertainty after a crashed process.

If a safe assignment cannot be proven, return a blocked result. Do not launch and wait for an avoidable out-of-memory failure.

### 10.4 Residency modes

| Mode | Behavior |
| --- | --- |
| Automatic | Keep the active Director resident when safe; evict specialists and render models by policy. |
| Director session | Prioritize Nemotron responsiveness and prevent competing high-memory renders. |
| Render session | Drain or evict Director models before admitting large video models. |
| Balanced | Allow bounded concurrency only when projected memory fits with reserves. |
| Manual expert | Honor explicit roles and devices after validation; never accept an unsafe assignment silently. |

### 10.5 Eviction

Eviction is graceful and observable:

1. stop admitting requests;
2. drain or cancel according to job policy;
3. close the runtime/model;
4. verify process/container termination;
5. verify lease release;
6. sample memory recovery;
7. record the transition.

The scheduler must not assume that Python garbage collection proves CUDA memory release.

## 11. Director and specialist orchestration

### 11.1 Context assembly

The backend builds a bounded, authorized context containing:

- source Director document;
- exact timeline range and revision;
- audio path only after project-media authorization;
- signal analysis and musical sections;
- transcript and transcript evidence;
- Story Bible and visual identity locks;
- existing camera, motion, and Reactive Lab state;
- locked scene IDs and locked ranges;
- authorized reference image/video assets;
- current renderer capabilities;
- user instruction and quality mode.

Large media is passed through runtime-specific multimodal mechanisms; it is not embedded indiscriminately into project JSON or logs.

### 11.2 Cosmos routing

Cosmos is considered when:

- Advanced quality is selected;
- specialist use is enabled;
- authorized visual/video evidence exists or the task explicitly requires motion, spatial, continuity, or physical reasoning;
- a qualified route and safe GPU assignment exist.

Cosmos returns a versioned `SpecialistResult` with evidence, continuity risks, motion notes, confidence, and provenance. Invalid or unavailable specialist output is recorded and omitted from Nemotron context.

### 11.3 Nemotron generation

Nemotron receives project evidence, the user instruction, and valid specialist results. It returns `DirectorPlan 1.0`. The orchestrator permits one bounded repair attempt for invalid JSON/schema output. It then:

- validates schema;
- rejects changes to locked scenes/ranges;
- validates sample ordering and project bounds;
- validates referenced renderer/model identities;
- removes no unknown project extension fields;
- records diagnostics;
- saves a draft only.

### 11.4 Review and apply

The native review experience compares the current project state with the proposal. It exposes:

- musical evidence supporting major changes;
- Cosmos contribution, if any;
- continuity and identity risks;
- renderer/model recommendations;
- locked content preserved;
- estimated runtime/resource impact;
- runtime/model provenance.

Apply uses existing revision-safe commands and remains undoable. A stale source revision fails with a refresh/rebase path.

## 12. Native WinUI experience

### 12.1 Workspace

Workspace remains the guided control room:

1. choose or verify source media;
2. reuse or run analysis;
3. review musical evidence;
4. enter the creative brief;
5. select Automatic/Nemotron/Qwen when expert control is desired;
6. show readiness without endpoint configuration;
7. generate a draft;
8. review specialist and Director reasoning;
9. apply to Storyboard, Reactive Lab, and Timeline;
10. hand off to Render.

Workspace shows an actionable install/start/blocked message if Nemotron is unavailable. It never asks for a local port.

### 12.2 Models

Models becomes the authoritative capability center. Each managed model card shows:

- model name, role, exact revision, source, and license;
- install, pause/cancel, validate, repair, remove;
- installed size and expected memory class;
- modality matrix;
- runtime routes and qualification state;
- selected route and automatic-selection reason;
- current residency and GPUs;
- start, stop, restart, unload, and smoke actions where meaningful;
- logs, metrics, last error, last receipt, and quarantine state;
- upgrade availability without silently changing the installed revision.

Default compact status:

```text
Nemotron Director     Ready        vLLM · GPUs 0,1,2
Cosmos Specialist     Installed    Loads on demand
Qwen Fallback         Available    Explicit use only
```

### 12.3 Settings

Settings contains policy, not endpoints:

- Director quality default;
- Cosmos enabled and routing policy;
- automatic runtime selection;
- allowed execution planes;
- runtime fallback allowed;
- model fallback allowed;
- residency mode and idle timeout;
- GPU policy and expert placement;
- telemetry retention;
- local-only versus explicitly configured remote execution.

An expert diagnostics expander may reveal internally assigned ports, commands, environment, container IDs, and logs, but these values are read-only runtime state unless an explicit developer mode is enabled.

### 12.4 Director specialist page

The specialist Director page preserves expert controls for:

- complete prompt/context preview with sensitive paths redacted;
- exact model and runtime selection;
- scene locks;
- specialist routing;
- proposal comparison;
- schema and lock diagnostics;
- provenance;
- retry with same or different runtime;
- explicit Qwen fallback.

### 12.5 Queue and diagnostics

Managed runtime transitions are durable jobs or job phases:

- acquiring GPU lease;
- starting execution plane;
- launching runtime;
- loading model;
- warming runtime;
- generating;
- validating;
- unloading;
- publishing draft.

The global queue exposes cancellation and avoids presenting “Generating” during a ten-minute model load.

## 13. Internal APIs

Names are indicative and should follow existing router conventions.

### Inventory and policy

- `GET /v1/models/runtime-inventory`
- `GET /v1/models/{model_id}/runtime-status`
- `GET /v1/models/{model_id}/capabilities`
- `GET /v1/runtime/policy`
- `PUT /v1/runtime/policy`
- `GET /v1/runtime/gpus`
- `GET /v1/runtime/leases`

### Lifecycle

- `POST /v1/models/{model_id}/runtime/start`
- `POST /v1/models/{model_id}/runtime/stop`
- `POST /v1/models/{model_id}/runtime/restart`
- `POST /v1/models/{model_id}/runtime/unload`
- `POST /v1/models/{model_id}/runtime/smoke`
- `GET /v1/runtime/instances/{instance_id}`
- `GET /v1/runtime/instances/{instance_id}/logs`

### Qualification and receipts

- `GET /v1/models/{model_id}/qualification`
- `GET /v1/models/{model_id}/receipts`
- `GET /v1/runtime/receipts/{receipt_id}`
- `POST /v1/models/{model_id}/qualification/quarantine`

All mutation endpoints require the existing local backend authorization, idempotency where applicable, and bounded payloads.

## 14. Security model

### 14.1 Network

- Bind managed servers to loopback or private worker networking by default.
- Never expose vLLM/NIM/TensorRT-LLM on `0.0.0.0` merely for convenience.
- Treat runtime API-key switches as defense in depth, not the sole boundary.
- Require explicit remote mode, authenticated transport, allowlisted host, TLS, and firewall guidance for remote services.
- Allocate internal ports through the supervisor and verify the listening process owns the expected executable/container.

### 14.2 Model code and supply chain

- Pin immutable revisions.
- Validate required files, hashes where manifests provide them, and model family before activation.
- Run custom Hugging Face code in an isolated worker with no arbitrary project filesystem access.
- Do not update a model or runtime automatically during an active project job.
- Preserve SBOM and dependency audit coverage for packaged runtime components.
- Quarantine a changed or invalid snapshot.

### 14.3 Media

- Resolve only project-authorized media.
- Reject path traversal, device paths, arbitrary URLs, unsupported schemes, and unauthorized network fetches.
- Enforce type, size, duration, frame, resolution, and decode budgets.
- Use temporary derivative media with explicit ownership and cleanup.

### 14.4 Model output

- Treat output as untrusted data.
- Validate against strict versioned schemas.
- Reject commands, paths, endpoints, or mutation instructions not represented by the contract.
- Preserve locked scenes and ranges.
- Apply changes only through deterministic project commands.

### 14.5 Secrets and logs

- Store credentials through the existing secret system or environment boundary, not project files.
- Redact tokens, authorization headers, private URLs, and sensitive absolute paths.
- Give runtime logs bounded retention and support-bundle inclusion rules.

## 15. Observability and evidence levels

### Level 0 — declared

Catalog or documentation claims a possible route.

### Level 1 — installed

Model/runtime files and dependencies exist at the expected pinned versions.

### Level 2 — launchable

The process/container starts and exposes its basic health surface.

### Level 3 — execution-ready

The exact model loads with admitted hardware and the route passes readiness checks.

### Level 4 — capability-qualified

The required modality and schema tests pass with valid outputs.

### Level 5 — production-qualified

A real Studio workflow produces a valid draft or media artifact, records a complete receipt, survives cancellation/restart tests, and passes applicable quality and persistence gates.

UI language must not collapse these states into “Ready.” A model may be installed but not execution-ready, or text-qualified but not video-qualified.

## 16. Failure and fallback policy

| Failure | Required behavior |
| --- | --- |
| Model missing | Preserve draft; offer Models navigation and install action. |
| License not accepted | Block download; show exact license action. |
| Runtime unavailable | Try only qualified runtime fallback allowed by policy. |
| Runtime crashes during load | Release lease after verified termination; preserve logs; quarantine repeated failures. |
| Out of memory | Do not silently retry unsafe placement; offer unload/render-session/device-policy actions. |
| Cosmos unavailable | Continue eligible Nemotron job without specialist evidence and record the degradation. |
| Nemotron unavailable | Preserve project; do not silently use Qwen. Offer explicit Qwen choice. |
| Invalid model JSON | One bounded repair attempt, then fail draft generation without mutation. |
| Stale project revision | Reject apply; reload/rebase proposal. |
| Cancellation | Fence publication, stop or drain runtime request, release owned resources, preserve prior draft. |
| Backend restart | Reconcile processes, containers, leases, jobs, and runtime ownership before accepting new work. |

## 17. Performance strategy

Measure end-to-end creative latency, not only token throughput:

- cold runtime start;
- model load;
- warm request time to first token;
- structured-plan completion;
- audio/video preprocessing;
- Cosmos specialist latency;
- validation and draft persistence;
- peak and steady VRAM;
- runtime eviction and memory recovery;
- repeated-request throughput;
- competing render impact.

Optimizations are accepted only when output fidelity, modalities, locks, cancellation, and provenance remain correct.

Initial performance targets should be baselined empirically before fixed thresholds are declared. The product target is a responsive warm Director session and predictable, visible cold-start behavior—not an unsupported promise of instant loading.

## 18. Implementation phases

Each phase is independently reviewable and revertible. A later phase does not erase earlier compatibility routes.

### Phase 0 — Baseline and contract freeze

Deliverables:

- enumerate current model, Director, runtime, GPU, execution-plane, and job contracts;
- record current Nemotron/Cosmos/Qwen catalog identities and migrations;
- add golden serialization tests for new contracts;
- record current direct-worker behavior and known limitations;
- define qualification-level vocabulary in backend and WinUI presentation models.

Acceptance:

- frozen lock checks pass;
- existing Director-to-Reactive/Timeline recovery tests pass;
- existing project samples reopen without migration loss;
- no runtime process is launched by inventory-only endpoints.

### Phase 1 — Real direct-runtime qualification

Deliverables:

- install exact pinned Nemotron and Cosmos snapshots through Models;
- complete direct Transformers loaders and media preprocessing;
- implement bounded local-only model execution;
- add real opt-in text/audio/image/video smoke tools;
- record GPU and memory receipts on the three A6000s;
- verify schema repair, locks, cancellation, cleanup, and draft persistence.

Acceptance:

- Nemotron returns a valid DirectorPlan from real project audio;
- Cosmos returns a valid SpecialistResult from authorized image and video fixtures;
- no network access occurs during local inference;
- all three GPUs are identified by stable physical identity;
- cancellation leaves no publishable partial draft or stale lease;
- saved/reopened project preserves the draft and provenance.

### Phase 2 — Runtime abstraction and capability registry

Deliverables:

- introduce runtime adapter and supervisor interfaces;
- move direct Transformers behind the interface without behavior change;
- add route selection request/decision contracts;
- add qualification store and receipt store;
- expose inventory and status APIs;
- add native Models capability matrix.

Acceptance:

- direct-worker tests pass through the abstraction;
- route decisions are deterministic under fixtures;
- installed-only state cannot satisfy smoke-qualified requirements;
- WinUI renders unknown, blocked, ready, and qualified states distinctly.

### Phase 3 — GPU leases and residency

Deliverables:

- integrate physical GPU inventory and durable leases;
- add Director/render workload classes and priority;
- add residency modes, VRAM reserves, idle eviction, and reconciliation;
- persist physical IDs and visible indices;
- expose leases and residency in Models and Queue.

Acceptance:

- atomic lease tests prevent conflicting assignments;
- crash and cancellation release owned leases only;
- Windows/WSL GPU mapping fixtures reconcile by identity;
- unsafe overcommit is blocked before process launch;
- Nemotron and render workloads obey the selected residency mode.

### Phase 4 — Studio-supervised vLLM

Deliverables:

- pinned WSL2/Linux vLLM environment or container;
- hidden loopback service lifecycle;
- health/readiness, logs, metrics, restart, and drain;
- Nemotron tensor-parallel configuration from a granted lease;
- normalized OpenAI-compatible client adapter;
- exact multimodal capability tests and parity comparison.

Acceptance:

- repeated warm Nemotron requests reuse one resident runtime;
- text, audio, required visual inputs, and DirectorPlan output independently pass or are marked unsupported;
- route survives backend/UI reconnect without duplicating the service;
- no runtime endpoint is user-configured or externally exposed by default;
- fallback to Transformers is recorded and policy-controlled.

### Phase 5 — Cosmos server qualification

Deliverables:

- evaluate vLLM support for exact Cosmos revision;
- reproduce 4 FPS video processing and specialist contract;
- compare output validity and memory behavior with direct Transformers;
- add on-demand load/unload and idle eviction.

Acceptance:

- visual/video results pass the same fixtures on the promoted route;
- no unsupported server route replaces the direct compatibility route;
- Nemotron continues without Cosmos when policy permits degradation;
- memory returns to the admitted baseline after eviction.

### Phase 6 — TensorRT-LLM promotion

Deliverables:

- isolated pinned TensorRT-LLM environment;
- exact model import/load path;
- runtime adapter and serving lifecycle;
- output parity harness;
- multi-GPU topology and memory tests;
- performance comparison against vLLM and Transformers.

Acceptance:

- only proven modalities are advertised;
- real Studio Director job passes with a Level-5 receipt;
- measurable latency, throughput, or memory benefit justifies promotion;
- failure cleanly returns to an allowed qualified runtime or fails closed;
- TensorRT version boundaries remain isolated from other Studio runtimes.

### Phase 7 — Optional NIM route

Deliverables:

- NIM image/profile discovery;
- license and cache handling;
- container supervisor adapter;
- management endpoint integration;
- exact GPU/model/profile qualification;
- optional enterprise deployment documentation.

Acceptance:

- Studio refuses incompatible profiles with a precise reason;
- NIM is optional and removable;
- model data and project state survive NIM removal;
- inference, health, metrics, and shutdown pass;
- fallback remains available without changing user model identity.

### Phase 8 — Production UX and creative intelligence

Deliverables:

- polished Models cards and readiness summaries;
- Director evidence explanations tied to musical ranges;
- Cosmos contribution visualization;
- runtime phases in Queue;
- per-scene runtime/renderer planning;
- Story Bible and locked-content comparison;
- recovery, retry, and explicit fallback flows.

Acceptance:

- a new user can install, direct, review, apply, and render without entering an endpoint or terminal command;
- an expert can determine exactly what ran;
- accessibility, keyboard navigation, high contrast, scaling, and narrow-window checks pass;
- all specialist pages remain available and consistent with Workspace.

### Phase 9 — Packaging, servicing, and scale-out

Deliverables:

- packaged runtime discovery and launch paths;
- clean-machine installation and upgrade tests;
- runtime/version compatibility policy;
- optional remote worker contracts and authentication;
- support bundle coverage;
- documentation and rollback procedure.

Acceptance:

- signed candidate installs, upgrades, launches, and uninstalls without orphaning owned processes;
- model caches and user projects obey retention choices;
- remote execution is opt-in and authenticated;
- Store/package claims remain separate from source-run evidence;
- release notes state qualified models, runtimes, hardware, and limitations exactly.

## 19. Test strategy

### 19.1 Unit and contract tests

- model/runtime identity separation;
- schema versions and extension preservation;
- route selection and rejection reasons;
- capability-level comparisons;
- GPU identity mapping;
- VRAM admission and lease conflicts;
- lifecycle state machine;
- log/secret redaction;
- media containment;
- DirectorPlan and SpecialistResult validation;
- lock preservation and stale revision rejection;
- receipt serialization and invalidation.

### 19.2 Integration tests

- supervisor with deterministic fake runtimes;
- real loopback server lifecycle with a tiny test model;
- WSL command construction and path translation;
- container lifecycle when available;
- crash, timeout, cancellation, restart, and backend reconciliation;
- WinUI API/client and presentation contracts;
- project save/reopen/recovery;
- job queue and publication fencing.

### 19.3 Hardware tests

- real Nemotron load and inference;
- real Cosmos image/video inference;
- three-A6000 identity and model split;
- warm/cold latency and memory;
- concurrent Director/render admission;
- OOM prevention and post-failure recovery;
- vLLM tensor-parallel service;
- TensorRT-LLM route when supported;
- encode/finish coexistence.

### 19.4 Creative validation

- full-track analysis reused across pages;
- evidence references correct source ranges;
- scene continuity across a long track;
- Story Bible identity preservation;
- locked scenes unchanged;
- Director draft applies to Timeline and Reactive Lab;
- camera/motion keys persist after reopen;
- changed scene can be rerendered without invalidating unrelated scenes;
- final media duration, streams, frames, motion, audio sync, and provenance validate.

### 19.5 Required regression commands

At minimum, use the repository-pinned toolchains and current instructions:

```powershell
uv lock --project studio/edmg-studio/python_backend --check
uv run --project studio/edmg-studio/python_backend --frozen --no-sync --group test python scripts/run_pytest_scopes.py
dotnet test studio/edmg-studio-winui/tests/EdmgStudio.Core.Tests/EdmgStudio.Core.Tests.csproj --configuration Release
dotnet build studio/edmg-studio-winui/EdmgStudio.WinUI.csproj --configuration Release --runtime win-x64 --no-restore
```

Real-model and packaged gates remain explicit opt-in qualifications and must not be replaced by mocks.

## 20. Acceptance matrix

| Gate | Pass condition |
| --- | --- |
| Model integrity | Exact pinned snapshot, required files, license, validation, no runtime network fallback. |
| Direct Nemotron | Real text/audio DirectorPlan, locks preserved, receipt saved. |
| Direct Cosmos | Real image/video SpecialistResult, 4 FPS contract, bounded media. |
| Runtime abstraction | Direct route behavior preserved behind adapters; deterministic routing. |
| GPU orchestration | Stable identities, safe leases, no ordinal-only claims, no avoidable oversubscription. |
| vLLM Nemotron | Persistent supervised service; required modalities and structured output pass. |
| Cosmos optimized route | Visual/video parity with direct baseline. |
| TensorRT-LLM | Exact route provides measured benefit and full advertised capability evidence. |
| NIM | Exact supported profile; lifecycle/metrics/inference pass; optional removal works. |
| Director workflow | Generate, review, apply, undo, save, reopen, recover, and stale-write protection pass. |
| Creative continuity | Story Bible, scene locks, timing, camera/motion, and Reactive handoff persist. |
| Render handoff | Per-scene plan produces owned jobs and validated artifacts. |
| Security | Loopback/private exposure, authorized media, redacted secrets, untrusted output validation. |
| Native UX | No endpoint required; actionable status; accessibility and expert diagnostics pass. |
| Release | Fresh signed candidate, clean-machine lifecycle, exact runtime/model disclosure. |

## 21. Risks and mitigations

### Model architecture changes faster than runtime support

Mitigation: direct Transformers remains the compatibility route; capability registry prevents unsupported promotion.

### Nemotron and render models compete for VRAM

Mitigation: residency modes, durable leases, pre-admission memory budgets, explicit Director/Render sessions, and eviction.

### Upstream servers expose unsafe endpoints

Mitigation: loopback/private networking, supervisor-owned configuration, reverse proxy for remote mode, and no assumption that an API key protects every route.

### Large downloads and gated models frustrate users

Mitigation: size/license visibility before install, resumable jobs, progress, cache validation, repair, and clear disk requirements.

### Optimized output diverges from the baseline

Mitigation: parity fixtures, schema comparison, creative invariants, and route-specific qualification.

### Stale receipts create false readiness

Mitigation: bind receipts to exact hashes/versions/hardware/settings and invalidate on material change.

### WSL/container lifecycle becomes fragile

Mitigation: one supervisor, idempotent start, ownership markers, health deadlines, reconciliation, bounded retry, and visible logs.

### Product becomes infrastructure-heavy

Mitigation: keep endpoints and flags out of the default UX; organize Models around creative capability and readiness.

## 22. File and component map

The exact names may be refined during implementation, but responsibilities should remain separated.

### Backend

- `services/model_catalog.py` — immutable model identity and discovery metadata.
- `services/model_manager.py` — installation, validation, repair, removal.
- `services/model_runtime_registry.py` — runtime adapters and qualification metadata.
- `services/model_load_coordinator.py` — load locks and GPU coordination foundations.
- new `services/managed_runtime_supervisor.py` — lifecycle and ownership.
- new `services/runtime_route_resolver.py` — capability/evidence-based selection.
- new `services/runtime_receipts.py` — immutable qualification and execution evidence.
- new `services/runtime_adapters/` — Transformers, vLLM, TensorRT-LLM, NIM, Qwen.
- `services/director_providers.py` — provider-neutral Director/Specialist orchestration.
- `services/director_runtime_settings.py` — user policy, not endpoint configuration.
- `api/director.py` — project-owned Director routes and draft boundary.
- new or extended `api/models.py` / `api/runtime.py` — inventory, lifecycle, policy, receipts.

### WinUI Core

- runtime contracts and presentation models;
- API client methods;
- lifecycle/status normalization;
- capability matrix and readiness summary;
- route/fallback receipt presentation.

### WinUI Pages

- `ModelsPage` — installation, capability, runtime, smoke, logs, receipts.
- `SettingsPage` — policy, residency, allowed execution planes.
- `WorkspacePage` — guided readiness/generation/review/handoff.
- `EdmgDirectorPage` — expert proposal and provenance.
- `QueuePage` — runtime phases and cancellation.
- `RenderPage` — workload/residency coordination and actual-route evidence.

### Scripts and runtime assets

- pinned WSL environment setup;
- idempotent vLLM launcher;
- TensorRT-LLM launcher kept version-isolated;
- optional NIM/container launcher;
- real multimodal smoke harnesses;
- runtime cleanup/reconciliation diagnostics.

## 23. Definition of done

This program is complete only when a user can perform the following without entering an endpoint or terminal command:

1. Open Models and see Nemotron as the default Director, Cosmos as its specialist, and Qwen as optional fallback.
2. Review licenses, disk/memory requirements, install both NVIDIA models, and validate their exact revisions.
3. Import and analyze a complete song once.
4. Provide a brief and authorized references.
5. Generate a real Nemotron draft using the best qualified managed runtime.
6. Use Cosmos evidence where appropriate.
7. Review explanations, locks, continuity, runtime, and resource implications.
8. Apply the approved plan to Storyboard, Reactive Lab, and Timeline.
9. Edit scenes, camera, motion, prompts, and renderer choices.
10. Render through admitted local or explicitly selected remote execution.
11. Cancel and recover without corrupting project state.
12. Save, close, reopen, and preserve exact project and provenance data.
13. Inspect a receipt proving the actual model revision, runtime, GPUs, fallbacks, and validated output.

Completion also requires a fresh full regression pass, real three-A6000 qualification, a valid long-form artifact, native UI traversal, and applicable packaged-release gates. Code presence, model installation, a health endpoint, or a single text response is not completion.

## 24. Recommended implementation order

The shortest path to a differentiated, reliable product is:

1. Qualify the current direct Nemotron and Cosmos paths on real media.
2. Introduce the runtime abstraction without changing behavior.
3. Add durable GPU leases and residency control.
4. Promote Nemotron to a supervised persistent vLLM service after full multimodal parity.
5. Qualify Cosmos under vLLM while retaining direct fallback.
6. Promote exact routes to TensorRT-LLM only when evidence shows a worthwhile benefit.
7. Add NIM only where NVIDIA provides an appropriate model/profile/hardware path.
8. Invest continuously in music evidence, continuity, editability, deterministic compilation, receipts, and native UX—the durable value competitors cannot gain merely by installing the same model.

The resulting product is not “a Studio connected to an AI endpoint.” It is a native audiovisual production system with a managed intelligence and execution fabric: the song is understood, direction is reviewable, production data is editable, compute is automatic, and every result is accountable.
