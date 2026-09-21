# EDMG Studio — Seamless TensorRT Integration Blueprint

## Target Repository

```text
C:\Users\user\source\repos\DWCTGenerativeSoundStudio
```

Available TensorRT package:

```text
C:\Users\user\Downloads\TensorRT-11.1.0.106
```

---

# 1. Primary Goal

Integrate NVIDIA TensorRT directly into the existing **EDMG Unified Internal Renderer** as an optional acceleration layer.

TensorRT must **not** become:

- a separate renderer
- a separate user workflow
- a hard dependency
- a replacement for PyTorch
- a replacement for llama.cpp
- a replacement for CTranslate2
- something the user must manually configure for every model

The desired user experience is:

```text
Select model
   ↓
Select creative/render settings
   ↓
Click Render
   ↓
EDMG automatically determines best runtime
   ↓
TensorRT used when safe and beneficial
   ↓
PyTorch CUDA used otherwise
```

The user should normally not need to know which runtime is being used.

---

# 2. Core Architectural Rule

TensorRT belongs underneath the existing Internal Renderer.

Do not create:

```text
Internal Renderer
TensorRT Renderer
Hunyuan Renderer
Wan Renderer
LTX Renderer
```

Instead create:

```text
                    EDMG INTERNAL RENDERER
                              │
                              ▼
                       MODEL ADAPTER
                              │
                              ▼
                       RUNTIME MANAGER
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
       TensorRT          PyTorch CUDA       Specialized
                                             runtimes
                                                 │
                                      ┌──────────┴──────────┐
                                      ▼                     ▼
                                  llama.cpp             CTranslate2
```

TensorRT is an implementation detail of the Runtime Manager.

---

# 3. Non-Negotiable Requirements

The integration is not complete unless:

```text
EDMG works when TensorRT is absent.

EDMG works when TensorRT is broken.

EDMG works when an individual TensorRT engine is invalid.

EDMG automatically falls back to PyTorch CUDA.

Existing projects remain compatible.

Existing model installations remain compatible.

Existing render jobs remain compatible.

Electron and WinUI use the same backend/runtime system.

TensorRT runtime decisions happen in the backend, not in the UI.

The user can disable TensorRT globally.

TensorRT engine creation is cached.

TensorRT engines are never assumed portable between incompatible environments.

No DLLs are copied into System32.

No permanent global PATH modification is required.

Existing CUDA/PyTorch installations are not silently replaced.
```

---

# 4. Integration Boundary

The UI must never directly call TensorRT.

Correct:

```text
WinUI / Electron
       │
       ▼
EDMG Backend API
       │
       ▼
Internal Renderer
       │
       ▼
Runtime Manager
       │
       ▼
TensorRT Adapter
```

Incorrect:

```text
WinUI
  ↓
TensorRT DLL
```

or:

```text
Electron
  ↓
trtexec.exe
```

TensorRT belongs exclusively to the backend/runtime layer.

---

# 5. Proposed Repository Structure

Add a dedicated runtime subsystem.

```text
DWCTGenerativeSoundStudio
│
└── studio
    └── edmg-studio
        │
        ├── tools
        │   ├── tensorrt
        │   │   └── 11.1.0.106
        │   │       ├── bin
        │   │       ├── include
        │   │       ├── lib
        │   │       ├── python
        │   │       └── metadata.json
        │   │
        │   └── llama.cpp
        │
        ├── models
        │   └── internal
        │
        ├── data
        │   ├── tensorrt
        │   │   ├── engines
        │   │   ├── manifests
        │   │   ├── timing_cache
        │   │   ├── profiles
        │   │   ├── quarantine
        │   │   └── logs
        │   │
        │   └── benchmarks
        │
        └── python_backend
            └── ...
```

Inside the Python backend introduce:

```text
runtime/
│
├── manager.py
├── registry.py
├── selector.py
├── capabilities.py
├── diagnostics.py
│
├── cuda/
│   ├── probe.py
│   └── devices.py
│
├── pytorch/
│   ├── adapter.py
│   └── diagnostics.py
│
├── tensorrt/
│   ├── adapter.py
│   ├── probe.py
│   ├── builder.py
│   ├── executor.py
│   ├── cache.py
│   ├── manifest.py
│   ├── profiles.py
│   ├── validation.py
│   ├── conversion.py
│   ├── worker.py
│   └── errors.py
│
├── llama_cpp/
│   └── adapter.py
│
└── ctranslate2/
    └── adapter.py
```

Use the project's real package namespace rather than blindly creating these exact folders if equivalent components already exist.

Reuse existing abstractions wherever possible.

Do not duplicate existing GPU detection, job management, model registry, logging, or worker infrastructure.

---

# 6. Runtime Interface

Create one common interface all inference backends can implement.

Conceptually:

```python
class RuntimeAdapter:
    runtime_id: str

    def probe(self):
        ...

    def supports(self, request):
        ...

    def prepare(self, request):
        ...

    def execute(self, request):
        ...

    def health(self):
        ...

    def cleanup(self):
        ...
```

Implementations:

```text
PyTorchCudaRuntime
TensorRTRuntime
LlamaCppRuntime
CTranslate2Runtime
CpuRuntime
```

The Internal Renderer must interact with the common interface rather than importing TensorRT directly.

---

# 7. Central Runtime Registry

Create one runtime registry.

Example:

```python
RuntimeRegistry(
    pytorch_cuda=...,
    tensorrt=...,
    llama_cpp=...,
    ctranslate2=...,
    cpu=...
)
```

Each runtime advertises:

```text
runtime ID
availability
health
GPU devices
supported precision
supported models
supported model components
dynamic shape support
engine/build capability
VRAM requirements
failure reason
```

Example status:

```json
{
  "runtime": "tensorrt",
  "available": true,
  "healthy": true,
  "version": "11.1.0.106",
  "devices": [
    {
      "id": 0,
      "name": "NVIDIA RTX A6000"
    },
    {
      "id": 1,
      "name": "NVIDIA RTX A6000"
    }
  ],
  "precision": [
    "fp32",
    "fp16"
  ]
}
```

---

# 8. Runtime Selection

Build one central selector.

Do not put runtime selection logic inside every model.

Example:

```python
selection = RuntimeSelector.select(
    model=model,
    component=component,
    device=device,
    precision=precision,
    user_preference=user_preference
)
```

Default selection:

```text
AUTO
 │
 ├─ Valid optimized TensorRT engine?
 │        │
 │       YES
 │        ▼
 │     TensorRT
 │
 ├─ TensorRT compatible and auto-build permitted?
 │        │
 │       YES
 │        ▼
 │     Build / validate engine
 │
 ├─ PyTorch CUDA available?
 │        │
 │       YES
 │        ▼
 │     PyTorch CUDA
 │
 └─ compatible fallback
```

Do not attempt TensorRT for models that have not explicitly declared TensorRT support.

---

# 9. User Runtime Modes

Expose these logical modes:

```text
Automatic
Compatibility
Performance
PyTorch CUDA
TensorRT
CPU / Fallback
```

### Automatic

Recommended default.

EDMG chooses the fastest validated route.

### Compatibility

Prefer PyTorch CUDA.

TensorRT only when a previously validated engine exists.

### Performance

Prefer validated TensorRT.

Allow automatic engine compilation.

### PyTorch CUDA

Disable TensorRT for that operation.

### TensorRT

Developer/advanced option.

Still allow configurable fallback unless strict mode is enabled.

---

# 10. Model Capability Metadata

TensorRT support must be declared in model metadata.

Example:

```json
{
  "id": "hunyuan_video_1_5",
  "runtime_support": {
    "pytorch_cuda": true,
    "tensorrt": {
      "supported": true,
      "components": {
        "transformer": true,
        "vae": true,
        "text_encoder": false
      }
    }
  }
}
```

Another model:

```json
{
  "id": "qwen3_vl_8b_gguf",
  "runtime_support": {
    "llama_cpp_cuda": true,
    "tensorrt": {
      "supported": false
    }
  }
}
```

This prevents the Runtime Manager from guessing.

---

# 11. Component-Level TensorRT

Do not assume an entire generative pipeline must run through TensorRT.

Allow mixed execution.

Example:

```text
HunyuanVideo
│
├── Text Encoder
│      └── PyTorch CUDA
│
├── Transformer
│      └── TensorRT
│
├── VAE
│      └── TensorRT
│
└── Scheduler
       └── native/PyTorch
```

Another possible pipeline:

```text
Wan
│
├── Text Encoder        PyTorch
├── Video Transformer   TensorRT
├── VAE                 PyTorch
└── Scheduler           PyTorch
```

This is critical.

Do not reject TensorRT integration just because one component cannot compile.

---

# 12. TensorRT Package Handling

Do not immediately globally install:

```text
C:\Users\user\Downloads\TensorRT-11.1.0.106
```

First create an inspection/import system.

Desired eventual location:

```text
studio\edmg-studio\tools\tensorrt\11.1.0.106
```

Create:

```text
metadata.json
```

Example:

```json
{
  "product": "NVIDIA TensorRT",
  "version": "11.1.0.106",
  "managed_by": "edmg",
  "source": "local_import"
}
```

The EDMG launcher/backend can temporarily prepend required TensorRT directories to the backend process environment.

Do not permanently modify global Windows environment variables.

---

# 13. TensorRT Probe

Before any integration work, implement:

```text
tensorrt/probe.py
```

It must test:

```text
TensorRT files exist
TensorRT Python bindings import
required DLLs resolve
CUDA device available
TensorRT runtime can initialize
TensorRT builder can initialize
small engine can compile
engine can serialize
engine can deserialize
simple GPU inference works
```

Return:

```json
{
  "installed": true,
  "import_ok": true,
  "builder_ok": true,
  "runtime_ok": true,
  "engine_test_ok": true,
  "inference_test_ok": true,
  "status": "ready"
}
```

Possible statuses:

```text
ready
partial
not_installed
incompatible
broken
disabled
```

---

# 14. Do Not Trust Installation Alone

This:

```text
import tensorrt
```

is not sufficient.

The runtime health check must actually create and execute a minimal TensorRT engine.

This catches:

```text
wrong DLLs
runtime/library mismatch
CUDA incompatibility
missing plugins
Python binding problems
GPU context problems
```

---

# 15. Engine Cache

TensorRT engines should be compiled once and reused.

Root:

```text
data\tensorrt\engines
```

Example:

```text
engines\
└── hunyuan_video_1_5
    └── transformer
        └── gpu_sm86
            └── fp16
                └── 1024x576
                    ├── engine.plan
                    └── manifest.json
```

Do not use only human-readable paths as identity.

Use a cryptographic cache key.

---

# 16. Engine Cache Key

At minimum include:

```text
model weight checksum
model configuration checksum
component ID
TensorRT version
CUDA/runtime identity
GPU architecture
precision
input profile
height
width
frame range
batch configuration
compiler settings
EDMG engine schema version
```

Example:

```python
engine_key = sha256(
    model_hash +
    config_hash +
    component +
    tensorrt_version +
    gpu_arch +
    precision +
    profile +
    engine_schema
)
```

---

# 17. Engine Manifest

Every engine gets a manifest.

Example:

```json
{
  "schema": 1,
  "model": "hunyuan_video_1_5",
  "component": "transformer",
  "model_hash": "...",
  "runtime": "tensorrt",
  "runtime_version": "11.1.0.106",
  "gpu_architecture": "sm86",
  "precision": "fp16",
  "profile": {
    "width": 1024,
    "height": 576
  },
  "validation": {
    "passed": true
  }
}
```

Do not load an engine without validating its manifest.

---

# 18. Automatic Invalidation

Invalidate cached engines when any relevant compatibility value changes.

Examples:

```text
model changed
model configuration changed
TensorRT changed
GPU architecture changed
precision changed
input profile changed
EDMG TensorRT schema changed
engine validation failed
```

Move invalid engines to:

```text
data\tensorrt\quarantine
```

or delete them according to project policy.

Never repeatedly crash on the same bad engine.

---

# 19. Engine Build Worker

Never compile TensorRT engines inside:

```text
Electron UI thread
WinUI UI thread
primary backend request thread
```

Use the existing isolated job system where possible.

Architecture:

```text
Frontend
   │
   ▼
Backend
   │
   ▼
Job Manager
   │
   ▼
TensorRT Build Worker
   │
   ├── compile
   ├── validate
   ├── benchmark
   └── cache
```

The build worker must produce progress events.

Example:

```text
Preparing model
Exporting graph
Building TensorRT engine
Validating engine
Benchmarking engine
Saving engine
Complete
```

---

# 20. Atomic Engine Builds

Never write directly to the final engine path.

Use:

```text
engine.plan.tmp
```

Then:

```text
build
validate
fsync/save
rename atomically
```

Only valid engines become:

```text
engine.plan
```

A crash must not leave a corrupt engine masquerading as valid.

---

# 21. Torch-TensorRT Path

For existing PyTorch pipelines, support a Torch-TensorRT path before forcing everything through manual ONNX conversion.

Architecture:

```text
PyTorch Module
      │
      ▼
Torch compile/export
      │
      ▼
Torch-TensorRT
      │
      ▼
TensorRT Engine
```

Hide this behind:

```text
TensorRTBuilder
```

Models should not know whether the implementation used:

```text
Torch-TensorRT
ONNX
direct TensorRT network construction
```

---

# 22. ONNX Path

Provide ONNX only where it is actually needed or more stable.

```text
PyTorch
   ↓
ONNX
   ↓
ONNX validation
   ↓
TensorRT builder
   ↓
Engine
```

Do not force every model through ONNX.

---

# 23. Precision Policy

Initial production support:

```text
FP32
FP16
```

Recommended default on compatible NVIDIA hardware:

```text
FP16
```

Later evaluate:

```text
BF16
FP8
INT8
```

Do not enable lower precision purely because the hardware supports it.

Every precision mode must pass EDMG quality validation.

---

# 24. Dynamic Shapes

Video models require careful profile handling.

Profiles may vary by:

```text
width
height
frames
batch
latent dimensions
sequence length
```

Do not compile one engine supporting every conceivable shape.

Use profile families.

Example:

```text
EDMG_576P

min:
768x432

opt:
1024x576

max:
1152x648
```

And:

```text
EDMG_720P

min:
1024x576

opt:
1280x720

max:
1344x768
```

Custom builds should occur only when necessary.

---

# 25. Hardware Manager Integration

The existing Hardware Manager should expose:

```text
GPU count
GPU name
GPU architecture
VRAM total
VRAM available
CUDA availability
runtime availability
```

For multiple GPUs:

```text
GPU 0
GPU 1
```

must remain separate devices.

Do not incorrectly combine two 48-GB GPUs into one logical 96-GB VRAM pool.

---

# 26. Dual-GPU Scheduling

Initially use job-level or component-level scheduling rather than trying to distribute every TensorRT engine across both GPUs.

Example:

```text
GPU 0
Main video generation

GPU 1
VAE / preprocessing / second render job
```

or:

```text
Shot 1 → GPU 0
Shot 2 → GPU 1
Shot 3 → GPU 0
Shot 4 → GPU 1
```

Only add tensor/model parallelism later where a model explicitly supports it.

---

# 27. Runtime Request Object

Extend the internal render request with runtime preferences.

Example:

```json
{
  "runtime": "auto",
  "device": "auto",
  "precision": "auto",
  "allow_runtime_fallback": true,
  "allow_engine_build": true
}
```

Existing render requests without these properties must continue to work.

Use backward-compatible defaults.

---

# 28. Runtime Result Metadata

Every completed render should record what actually happened.

Example:

```json
{
  "runtime": {
    "requested": "auto",
    "selected": "tensorrt",
    "device": "cuda:0",
    "precision": "fp16",
    "components": {
      "transformer": "tensorrt",
      "vae": "tensorrt",
      "text_encoder": "pytorch_cuda"
    }
  }
}
```

This is important for:

```text
debugging
benchmarking
resume
reproducibility
support
```

---

# 29. Automatic Fallback

This is mandatory.

Example:

```python
try:
    output = tensorrt_runtime.execute(...)
except TensorRTExecutionError:
    mark_engine_unhealthy()
    output = pytorch_runtime.execute(...)
```

But do not silently swallow the problem.

Record:

```text
TensorRT failure
engine ID
model
component
error
fallback runtime
```

The job should continue whenever safe.

---

# 30. Failure Circuit Breaker

Do not retry the same broken engine 50 times during a long render.

When an engine fails:

```text
mark unhealthy for current session
        ↓
skip TensorRT for subsequent shots/components
        ↓
use PyTorch fallback
```

Example log:

```text
[TensorRT] Engine execution failed for Hunyuan transformer.
[TensorRT] Engine disabled for remainder of job.
[Runtime] Falling back to PyTorch CUDA.
```

---

# 31. Render Resume Compatibility

Checkpoint/resume information should record runtime state but must not require that same runtime to remain available.

For example:

```text
original job:
TensorRT

resume:
TensorRT unavailable
```

EDMG should be capable of:

```text
resume with PyTorch CUDA
```

when the output format and model state permit it.

Do not make checkpoints dependent on an ephemeral TensorRT execution context.

---

# 32. Internal Renderer Adapter

Each internal model should use an adapter similar to:

```python
class InternalVideoModelAdapter:

    def prepare_component(self, component, runtime):
        ...

    def render(self, request, runtime_plan):
        ...
```

The renderer gets a runtime plan:

```text
transformer → TensorRT
VAE → TensorRT
text encoder → PyTorch
```

instead of making those decisions internally.

---

# 33. Runtime Plan

Introduce a runtime planning stage.

Example:

```python
plan = RuntimePlan(
    model="hunyuan_video_1_5",
    components={
        "text_encoder": "pytorch_cuda",
        "transformer": "tensorrt",
        "vae": "tensorrt"
    },
    device_map={
        "text_encoder": 0,
        "transformer": 0,
        "vae": 1
    }
)
```

The plan is created before rendering starts.

This makes runtime decisions observable and testable.

---

# 34. UI Integration

Do not clutter the primary renderer UI.

Normal user-facing model selection remains:

```text
Model
Resolution
Duration
Motion
Quality
Seed
etc.
```

Add only a simple runtime control under advanced options:

```text
Runtime

Automatic
Performance
Compatibility
PyTorch CUDA
TensorRT
```

Default:

```text
Automatic
```

---

# 35. Settings UI

Add:

```text
Settings
└── AI / Runtime
    └── NVIDIA Acceleration
```

Display:

```text
GPU:
NVIDIA RTX A6000

CUDA:
Ready

PyTorch CUDA:
Ready

TensorRT:
Ready

TensorRT version:
11.1.0.106

Engine cache:
XX GB

Runtime mode:
Automatic
```

Controls:

```text
Enable TensorRT

Automatically build optimized engines

Allow PyTorch fallback

Preferred precision

Engine cache size

Run diagnostics

Optimize installed models

Clear TensorRT cache
```

---

# 36. WinUI and Electron

Do not implement TensorRT separately in each frontend.

Both frontends consume:

```text
GET /runtime/status
```

or the project's equivalent backend API.

The backend returns everything needed for UI presentation.

WinUI:

```text
Backend API → Runtime status
```

Electron:

```text
Backend API → Runtime status
```

One backend implementation.

Two presentations.

---

# 37. Backend API

Adapt naming to existing API conventions.

Suggested endpoints:

```text
GET /runtime
GET /runtime/devices
GET /runtime/tensorrt
GET /runtime/tensorrt/engines

POST /runtime/tensorrt/diagnose
POST /runtime/tensorrt/build
POST /runtime/tensorrt/rebuild
POST /runtime/tensorrt/benchmark

DELETE /runtime/tensorrt/cache/{engine_id}
```

Long operations should be jobs, not blocking HTTP requests.

---

# 38. Runtime Diagnostics UI

Diagnostics should clearly distinguish:

```text
Installed
Available
Healthy
Compatible
Accelerating something
```

For example:

```text
TensorRT
Installed:       Yes
Version:         11.1.0.106
Runtime load:    PASS
Builder:         PASS
GPU inference:   PASS
Models optimized: 3
Status:          READY
```

---

# 39. Logging

Every render should log runtime selection.

Example:

```text
[Runtime] Requested mode: auto
[Runtime] Model: hunyuan_video_1_5
[Runtime] Device: NVIDIA RTX A6000 cuda:0
[Runtime] Precision: fp16

[Runtime] Component plan:
[Runtime] text_encoder = pytorch_cuda
[Runtime] transformer = tensorrt
[Runtime] vae = tensorrt

[TensorRT] transformer engine cache HIT
[TensorRT] vae engine cache HIT
```

Avoid excessive low-level TensorRT noise unless debug mode is enabled.

---

# 40. Benchmarking

Do not assume TensorRT is beneficial.

EDMG should benchmark:

```text
PyTorch CUDA
vs
TensorRT
```

Measure:

```text
initialization
first inference
steady-state inference
total render time
peak VRAM
average GPU utilization
engine build time
```

Store benchmarks by:

```text
model
component
GPU
precision
resolution/profile
runtime version
```

---

# 41. Runtime Selection Based on Actual Benefit

Eventually allow EDMG to remember benchmarks.

Example:

```text
TensorRT:
7.2 seconds/frame

PyTorch:
7.0 seconds/frame
```

In that case:

```text
AUTO → PyTorch
```

not TensorRT.

TensorRT should be preferred because it is faster for that configuration, not merely because it exists.

---

# 42. Output Validation

Before marking an engine as production-ready compare TensorRT output to the reference PyTorch implementation.

Use relevant metrics such as:

```text
max absolute error
mean absolute error
cosine similarity
latent similarity
image/output comparison
```

For generative video models, numerical comparisons alone may not be sufficient.

Also use deterministic fixed-seed test cases where practical.

---

# 43. Engine State

Use explicit states.

```text
missing
building
validating
ready
failed
stale
quarantined
disabled
```

Do not use ambiguous booleans like:

```text
engine_ok = true
```

for the entire lifecycle.

---

# 44. Security

TensorRT serialized engines should be treated as executable machine-generated artifacts.

Only automatically load engines that:

```text
EDMG built locally

or

came from a trusted EDMG-managed source
```

Do not automatically execute arbitrary `.engine` or `.plan` files discovered inside random model directories.

---

# 45. Disk Management

TensorRT engines may become large.

Add configurable limits.

Example:

```text
Maximum TensorRT cache:
100 GB
```

Support:

```text
LRU cleanup
manual cleanup
per-model cleanup
rebuild
```

Never delete original model weights when clearing TensorRT cache.

---

# 46. Installer / Toolchain Integration

Eventually integrate TensorRT into the EDMG toolchain manager.

Desired behavior:

```text
EDMG starts
   ↓
detect TensorRT
   ↓
not installed?
   ↓
continue normally
```

Optional:

```text
Settings
   ↓
Install NVIDIA Acceleration
```

The installer then handles:

```text
package
verification
installation
environment
health check
```

For the first implementation, use the locally downloaded TensorRT package and keep installation explicitly separated from runtime architecture work.

---

# 47. Existing Runtime Preservation

Do not modify or break:

```text
llama.cpp
Qwen GGUF
CTranslate2
Faster-Whisper
existing Diffusers runtime
existing PyTorch CUDA runtime
CPU fallback
external API providers
```

TensorRT is additive.

---

# 48. External Providers

External/API render providers remain outside the local runtime hierarchy.

Architecture:

```text
EDMG Model/Provider Selection
              │
        ┌─────┴─────┐
        │           │
      LOCAL       REMOTE
        │           │
        ▼           ▼
 Internal Engine    Provider API
        │
 Runtime Manager
```

TensorRT affects only compatible local inference.

Do not entangle API providers with TensorRT code.

---

# 49. Phase 1 — Reconnaissance

Before editing anything:

Inspect existing:

```text
renderer abstraction
model registry
backend routes
job manager
worker process system
hardware detector
CUDA detector
settings system
model manifests
Electron runtime settings
WinUI runtime settings
logging
checkpoint system
```

Document where TensorRT fits.

Do not create parallel systems when equivalent infrastructure already exists.

---

# 50. Phase 2 — Runtime Foundation

Implement:

```text
RuntimeAdapter
RuntimeRegistry
RuntimeSelector
RuntimePlan
```

Initially register only existing runtimes.

Confirm all existing rendering still passes.

TensorRT should not be introduced until the common runtime architecture works.

---

# 51. Phase 3 — TensorRT Probe

Implement TensorRT detection and health diagnostics.

No real EDMG model conversion yet.

Pass criteria:

```text
TensorRT detected

DLLs load

Python binding works

builder works

engine serialization works

engine deserialization works

simple inference works
```

---

# 52. Phase 4 — Engine Infrastructure

Implement:

```text
engine cache
manifest
cache key
validation
quarantine
atomic writes
build worker
engine lifecycle
```

Test using synthetic networks first.

---

# 53. Phase 5 — First Real Component

Choose one manageable model component.

Good candidates:

```text
VAE decoder
text encoder
vision encoder
```

Do not begin with the largest Hunyuan/Wan transformer.

Flow:

```text
PyTorch reference
      ↓
TensorRT compile
      ↓
validate
      ↓
benchmark
      ↓
cache
      ↓
fallback test
```

---

# 54. Phase 6 — Video Transformer

After component-level infrastructure works:

Integrate one video model.

Recommended pattern:

```text
ONE MODEL
ONE COMPONENT
ONE PRECISION
ONE GPU
ONE PROFILE
```

Example:

```text
HunyuanVideo 1.5
Transformer
FP16
GPU 0
1024x576 profile
```

Get that stable before expanding.

---

# 55. Phase 7 — Mixed Runtime Pipeline

Enable:

```text
text encoder → PyTorch
transformer → TensorRT
VAE → PyTorch
```

Then:

```text
text encoder → PyTorch
transformer → TensorRT
VAE → TensorRT
```

Verify both produce valid renders.

---

# 56. Phase 8 — Runtime Fallback

Intentionally trigger:

```text
missing engine
corrupted engine
execution failure
out-of-memory condition
unsupported shape
```

Every case must cleanly fall back where possible.

The render should not be lost merely because TensorRT fails.

---

# 57. Phase 9 — UI Integration

Only after backend behavior is stable:

Add runtime status and controls to:

```text
WinUI
Electron
```

Both must consume the same backend data.

Do not duplicate runtime logic.

---

# 58. Phase 10 — Additional Models

After the first model is stable:

```text
LTX
Hunyuan
Wan
```

Integrate one at a time.

Do not attempt a mass-conversion project.

---

# 59. Phase 11 — Advanced Optimizations

Only after the basic TensorRT implementation is production-stable evaluate:

```text
BF16
FP8
INT8
CUDA graphs
advanced timing caches
parallel engine builds
multi-GPU scheduling
engine prewarming
model-specific optimization plugins
```

These are optimizations, not prerequisites.

---

# 60. Compatibility Test Matrix

Test at minimum:

```text
TensorRT absent

TensorRT installed and healthy

TensorRT installed but broken

TensorRT disabled

engine missing

engine valid

engine stale

engine corrupted

unsupported model

unsupported resolution

PyTorch CUDA available

CUDA unavailable

GPU 0

GPU 1

fallback during render

checkpoint/resume

Electron

WinUI
```

---

# 61. Existing Render Regression Tests

Every existing renderer test must continue passing.

Test:

```text
project creation
model selection
image generation
video generation
internal renderer
resume
cancel
progress
preview
export
model installation
model removal
settings
backend restart
```

TensorRT must not introduce regressions into unrelated systems.

---

# 62. Model Download Behavior

Downloading a model must not automatically require engine compilation.

Correct:

```text
Download model
   ↓
Model ready for PyTorch
```

Then optionally:

```text
Optimize now
```

or build automatically on first use.

This means users do not need TensorRT just to install models.

---

# 63. First-Use Behavior

If AUTO mode detects no TensorRT engine:

```text
Model selected
   ↓
PyTorch available
   ↓
Render may begin immediately
```

Depending on policy either:

```text
Option A:
render now with PyTorch
build TensorRT later
```

or:

```text
Option B:
build engine before first performance-mode render
```

Do not unexpectedly make users wait for a large optimization build when they selected Compatibility mode.

---

# 64. Recommended Default Behavior

For normal users:

```text
Runtime:
AUTO

TensorRT:
Enabled

Auto-build:
Enabled

Fallback:
Enabled

Precision:
AUTO

Strict TensorRT:
Disabled
```

The Studio handles the rest.

---

# 65. Developer Mode

Expose extra controls only in developer/advanced mode:

```text
force runtime
force GPU
force precision
rebuild engine
show engine key
show optimization profile
show TensorRT logs
strict TensorRT
disable fallback
```

Do not clutter normal workflows with these controls.

---

# 66. Strict TensorRT Mode

Strict mode exists only for diagnostics.

Behavior:

```text
TensorRT failure
      ↓
job fails
```

Normal behavior:

```text
TensorRT failure
      ↓
fallback
      ↓
job continues
```

Strict mode default:

```text
OFF
```

---

# 67. Configuration

Add configuration similar to:

```json
{
  "runtime": {
    "mode": "auto",
    "allow_fallback": true,
    "tensorrt": {
      "enabled": true,
      "auto_build": true,
      "precision": "auto",
      "cache_enabled": true,
      "strict": false
    }
  }
}
```

Respect existing configuration architecture instead of introducing an unrelated configuration file if the Studio already has one.

---

# 68. Observability

Runtime decisions should be easy to inspect.

Expose in diagnostics:

```text
requested runtime
selected runtime
fallback history
device
precision
engine
engine status
engine build reason
engine cache status
model/component support
```

This will dramatically simplify future troubleshooting.

---

# 69. No Silent Environment Mutation

TensorRT integration must not silently:

```text
pip uninstall torch
install a different PyTorch build
replace CUDA
replace cuDNN
modify Windows PATH permanently
change system CUDA_HOME
copy DLLs into Windows directories
```

Any environment migration must be an explicit toolchain-management action.

---

# 70. Acceptance Criteria

Integration is considered production-ready when:

```text
EDMG launches normally with TensorRT missing.

EDMG detects TensorRT automatically.

TensorRT diagnostics pass.

One real EDMG model uses TensorRT successfully.

TensorRT provides measurable benefit for that workload.

Output passes validation.

Engine caching works.

Engine invalidation works.

A corrupted engine cannot crash the whole Studio.

Fallback to PyTorch works automatically.

A failed TensorRT execution can continue the render.

Existing PyTorch rendering remains unchanged.

Qwen/llama.cpp remains unchanged.

Faster-Whisper/CTranslate2 remains unchanged.

External API providers remain unchanged.

Electron and WinUI expose the same capabilities.

Multiple GPUs are correctly recognized.

Cache can be cleared safely.

TensorRT can be disabled.

Checkpoint/resume remains functional.

Existing projects still open and render.

No system-wide TensorRT installation is required for the Studio to launch.
```

---

# 71. Final Target Architecture

```text
                              EDMG STUDIO
                                   │
                 ┌─────────────────┴─────────────────┐
                 │                                   │
               WinUI                              Electron
                 │                                   │
                 └─────────────────┬─────────────────┘
                                   │
                                   ▼
                              BACKEND API
                                   │
                                   ▼
                            INTERNAL ENGINE
                                   │
                     ┌─────────────┴─────────────┐
                     │                           │
                MODEL MANAGER                PROVIDERS
                     │                           │
                     │                      External APIs
                     │
                     ▼
                 RUNTIME PLAN
                     │
                     ▼
                RUNTIME MANAGER
                     │
       ┌─────────────┼──────────────┬──────────────┐
       │             │              │              │
       ▼             ▼              ▼              ▼
   TensorRT      PyTorch CUDA    llama.cpp     CTranslate2
       │             │              │              │
       └─────────────┴──────┬───────┴──────────────┘
                            │
                            ▼
                     HARDWARE MANAGER
                            │
                 ┌──────────┼──────────┐
                 │          │          │
                 ▼          ▼          ▼
              GPU 0       GPU 1       CPU
```

---

# 72. Final Design Principle

The feature should never feel like:

```text
"EDMG now has another renderer called TensorRT."
```

It should feel like:

```text
"EDMG renders faster when the hardware and model support it."
```

The Internal Renderer remains the product.

TensorRT is simply one optimized execution technology underneath it.

---

# 73. Instructions to Codex

Before modifying code:

1. Inspect the complete current runtime, renderer, model registry, job/worker, settings, hardware, API, Electron and WinUI architecture.
2. Reuse existing abstractions wherever they already solve part of this blueprint.
3. Do not delete or rewrite functioning renderer infrastructure merely to fit this document.
4. Introduce the smallest clean abstraction necessary for a common Runtime Manager.
5. Preserve all existing behavior before enabling TensorRT.
6. Implement TensorRT behind feature detection.
7. Add tests before migrating actual production model execution.
8. Start with TensorRT diagnostics and a synthetic engine.
9. Add engine caching and fallback before integrating large models.
10. Integrate one real component and one real model first.
11. Benchmark against PyTorch before declaring TensorRT preferable.
12. Do not globally modify CUDA/PyTorch/TensorRT installations.
13. Do not remove external providers.
14. Do not break llama.cpp or CTranslate2 paths.
15. Keep Electron and WinUI runtime logic backend-driven.
16. Run relevant backend, frontend and renderer tests after each major phase.
17. Commit work in logical phases rather than one enormous TensorRT commit.
18. Document every new runtime/environment dependency.
19. Do not mark the integration complete until automatic fallback has been deliberately tested.
20. Preserve the overarching EDMG principle:

**One Internal Renderer, multiple models, multiple execution runtimes, automatic selection, graceful fallback.**

---

# End State

When finished, a user should be able to launch EDMG Studio, select Hunyuan, Wan, LTX or another supported internal model and click Render.

EDMG should automatically:

```text
inspect hardware
        ↓
inspect model capabilities
        ↓
inspect available runtimes
        ↓
find/build validated TensorRT engine
        ↓
choose optimal GPU
        ↓
choose precision
        ↓
render
        ↓
fall back if necessary
        ↓
record runtime metadata
```

No manual TensorRT configuration should be required for ordinary operation.

That is the standard for calling the TensorRT integration seamless.
