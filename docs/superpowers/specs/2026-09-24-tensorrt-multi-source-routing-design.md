# TensorRT Multi-Source Routing Design

Date: 2026-09-24

## Purpose

Extend EDMG Studio's existing optional TensorRT component runtime so TensorRT is no longer treated as an ONNX-only build path. The integration must admit supported ONNX graphs, PyTorch checkpoints, Hugging Face models backed by safetensors, and prebuilt TensorRT engines without creating a second renderer or bypassing the existing runtime policy, engine cache, worker isolation, resource guards, model-load coordination, job APIs, or WinUI provider conventions.

The feature is successful when Studio can explain which route a model or component will use, execute only routes that are actually supported and validated, preserve GGUF on llama.cpp, and fail or fall back exactly as configured without reporting TensorRT acceleration unless a validated TensorRT engine executed.

## Constraints

- Preserve all existing render routes, request defaults, cache compatibility, and user-owned uncommitted work.
- Keep native TensorRT and compiler imports inside the isolated backend worker. WinUI and the API process remain control/status surfaces.
- Reuse `ComponentAdapterRegistry`, `RuntimeManager`, `RuntimeProcess`, `EngineCache`, the model-load coordinator, render settings, resource policy, CUDA device selection, and current runtime jobs.
- Do not install, remove, or synchronize dependencies as part of routing. Missing optional packages are capability results, not setup permission.
- Keep source-format support distinct from model/operator support. A recognized `.pth` or `.safetensors` file is not automatically compilable.
- Preserve the established rule that global TensorRT disable wins over per-operation preferences.
- Never mark a route ready merely because a file exists, a module imports, an engine deserializes, or compilation starts.

## Architecture

### Source descriptor

Add a normalized, immutable source descriptor used by the existing component adapter layer. It records:

- model ID, family, component, and resolved source root;
- source kind: `onnx`, `pytorch_checkpoint`, `huggingface`, `tensorrt_engine`, `gguf`, or `unknown`;
- relevant graph, weight, config, index, and engine files;
- architecture identifier and revision when available;
- content hashes required for cache identity;
- detection evidence and a truthful unsupported reason.

Detection is deterministic and side-effect free. Extension checks are followed by structural checks:

- ONNX requires an ONNX model file.
- `.pt` and `.pth` are PyTorch checkpoints but still require a registered architecture/component loader.
- Hugging Face requires configuration that identifies an admitted architecture plus safetensors weights or an index resolving to them.
- `.engine` and `.plan` are prebuilt TensorRT candidates.
- GGUF is classified explicitly and routed to llama.cpp, never offered to TensorRT.
- Ambiguous directories fail classification instead of guessing.

The model catalog/runtime registry exposes the descriptor but remains the owner of package admission and installed-model state.

### Route resolution

Extend each component adapter with the source kinds and compiler routes it supports. A resolver produces one route decision:

| Source | Selected TensorRT route | Admission requirement |
| --- | --- | --- |
| ONNX | `onnx_parser` | Existing model-specific input/profile adapter and supported graph |
| `.pt` / `.pth` | `torch_tensorrt` or `torch_compile_tensorrt` | Registered architecture loader, CUDA, optional compiler installed, supported operators |
| HF safetensors | `huggingface_torch_tensorrt` | Valid config/architecture, registered component loader, CUDA, optional compiler installed, supported operators |
| `.engine` / `.plan` | `prebuilt_engine` | Manifest or supplied metadata sufficient to validate bindings, profiles, precision, device compatibility, and model/component identity |
| GGUF | `llama_cpp` | Existing llama.cpp provider admission |
| Unknown/unsupported | existing runtime or failure | Existing fallback/strict policy |

The route decision contains `requested_runtime`, `selected_runtime`, `source_kind`, `compiler`, `supported`, `reason`, and `fallback_runtime`. Recognition, build eligibility, engine validation, and active acceleration remain separate states.

Torch-TensorRT is preferred for registered PyTorch/Hugging Face adapters. The `torch.compile` TensorRT backend is used only when the adapter declares it compatible and the backend is discoverable. There is no silent switch to a generic compile backend. Unsupported operators or compilation failures are returned to the runtime manager, which applies the existing strict/fallback policy.

### Build and direct-engine admission

The existing isolated runtime worker receives the normalized descriptor and route. Route-specific builders implement a common prepare result:

- `onnx_parser` reuses the current ONNX/TensorRT builder behavior.
- Torch routes load the registered architecture and weights in the worker, compile the admitted component, serialize the resulting engine where supported, then run existing validation.
- `prebuilt_engine` copies or references the supplied immutable engine through the cache admission path; it does not rebuild it. It must deserialize, inspect bindings and profiles, verify the requested precision and component contract, pass memory/resource checks, and execute the appropriate validation fixture before publication.

All native work stays behind the existing process boundary and cancelable model-load lock. CUDA device indexes and multi-GPU settings flow from the current resource policy. A component adapter must explicitly declare whether it supports one device or a multi-GPU strategy; no route invents placement independently.

### Cache identity and manifests

Continue using `EngineCache` and its atomic manifest publication. Increment the cache schema only if needed to make the new identity unambiguous. Identity includes:

- model family, component, adapter version, source kind, and route;
- hashes of graph, weights, safetensors index/config, or prebuilt engine;
- architecture and model revision;
- TensorRT, Torch, Torch-TensorRT, CUDA, and compiler-backend versions as applicable;
- device compute capability, precision, optimization profiles, workspace/memory limits, and relevant build flags.

Fields that do not apply to a route are omitted rather than written as null. Old ready entries remain readable when their legacy identity matches the old path. A different source, config, compiler, profile, or hardware compatibility key cannot reuse an engine accidentally.

Manifests record route, source evidence, validation result, benchmark data, and whether the engine was built or admitted prebuilt. Failed or incompatible direct engines are quarantined using the existing cache state machinery.

### Policy, failure, and fallback

The current runtime policy remains authoritative:

- disabled or explicit PyTorch/CPU mode does not enter TensorRT;
- strict/no-fallback mode raises a user-facing failure with route and cause;
- fallback-enabled mode selects the existing provider and records the reason;
- automatic/compatibility modes retain existing benefit checks;
- GGUF always selects llama.cpp and states that GGUF is not a TensorRT graph format;
- missing Torch-TensorRT or a missing `torch.compile` backend reports unavailable capability and never reports a successful optimization;
- unsupported operators, architecture loaders, bindings, profiles, or devices fail before ready publication;
- `accelerating` becomes true only from an execution receipt showing a validated TensorRT route actually ran.

### APIs and UI status

Extend existing runtime status and job payloads rather than introducing separate endpoints. Component/model status serializes:

- source kind and detected architecture;
- requested and resolved route;
- compiler/backend name and availability;
- support, build eligibility, validation state, and actual acceleration independently;
- engine/cache identity and state where available;
- fallback runtime and a user-facing unsupported/fallback reason;
- supported precisions/profiles and device constraints.

Runtime job requests may identify a model/component source already admitted by the model catalog. Paths are resolved server-side from managed model records; arbitrary client paths are not accepted.

WinUI Models displays the route for each managed model/component, including explicit labels such as ONNX parser, Torch-TensorRT, Hugging Face via Torch-TensorRT, prebuilt TensorRT engine, or llama.cpp. Settings retains global runtime policy and shows compiler/package availability. Render/preflight status carries the resolved route and fallback reason into submission and receipts. The UI does not infer capability from filename extensions.

## Integration Boundaries

Expected implementation areas are:

- backend runtime adapters, source classification, route resolution, builders/worker, cache identity, validation, service/status, and policy-aware managers;
- model catalog/runtime registry descriptors and existing render/runtime job APIs;
- backend tests for routing, detection, compilation selection, prebuilt admission, policy, identity, and serialization;
- WinUI Core JSON contracts/client tests and Models/Settings/preflight presentation;
- TensorRT integration documentation and the existing blueprint/progress records where feature status changes.

Existing Director multi-GPU, Workspace, internal-video motion, and unrelated model-runtime changes remain untouched except where a narrowly shared contract must be merged without losing their behavior.

## Test Strategy

Implementation follows red-green-refactor. Focused tests precede each production change.

Backend tests cover:

- deterministic source classification, including safetensors index/config and ambiguous directories;
- ONNX route preservation;
- `.pt`/`.pth` architecture admission and Torch-TensorRT versus declared `torch.compile` selection;
- HF safetensors configuration and loader selection;
- direct engine validation, incompatible bindings/profiles/devices, and quarantine;
- GGUF routing to llama.cpp;
- missing optional compiler, unsupported architecture/operator, strict failure, and allowed fallback;
- cache-key changes for source/config/compiler/profile/hardware and legacy cache readability;
- API/job/status serialization and the rule that ready/accelerating require validation/execution evidence;
- memory guard, device selection, cancellation, and model-load locking on every new route.

WinUI Core tests cover JSON compatibility, route/reason presentation models, and preservation of older payload defaults. Page-level tests or extracted presentation helpers verify that unsupported and fallback states are visible and not labeled accelerated.

Verification runs the relevant focused backend tests during development, then the frozen aggregate backend suite, WinUI Core tests, and the WinUI Release x64 build. Dependency presence and real GPU qualification are reported separately. If Torch-TensorRT is absent, mocked contract tests may pass while real Torch-TensorRT execution remains an external blocker; no live-runtime claim is made without a real execution receipt.

## Documentation and Qualification

Update the TensorRT integration documentation and blueprint to list each route as implemented, dependency-available, engine-validated, execution-validated, or unsupported. Preserve the distinction between successful builds/tests and live GPU inference, visible UI operation, packaging, signing, or release qualification.

No route is advertised as universal TensorRT support. Model-specific adapters remain required, and unsupported operators or architectures remain explicit limitations.
