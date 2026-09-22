# DWCT Generative Sound Studio
## GPU Runtime Automation Implementation Plan

**Target file:** `/IMPLEMENTATION_PLAN.md`

**Repository:** `DWCTGenerativeSoundStudio`

**Status:** Implementation Plan

---

## 1. Objective

Implement automatic local AI runtime orchestration when DWCT Generative Sound Studio launches.

The Studio should automatically:

- Start or connect to WSL.
- Detect NVIDIA GPUs exposed to WSL.
- Verify CUDA availability.
- Detect GPU count and available VRAM.
- Start llama.cpp for compatible GGUF models.
- Enable CUDA GPU offload automatically.
- Enable multi-GPU automatically when multiple compatible NVIDIA GPUs are available.
- Start TensorRT-LLM for models configured for TensorRT execution.
- Select the correct runtime based on the model profile.
- Wait until the runtime is healthy before allowing inference.
- Expose runtime status in WinUI.
- Capture logs and diagnostics.
- Shut down only Studio-owned runtime processes when appropriate.
- Preserve existing standalone/local/backend functionality.

The implementation must support both current single-GPU systems and future multi-GPU systems without requiring source-code changes.

---

## 2. Runtime Architecture

```text
RUN_ME.bat
    |
    v
DWCT Studio / WinUI
    |
    v
Local Runtime Orchestrator
    |
    +---------------- Hardware Discovery ----------------+
    |                                                   |
    |    WSL available?                                 |
    |    NVIDIA driver available?                       |
    |    CUDA available?                                |
    |    GPU count?                                     |
    |    GPU VRAM?                                      |
    |    llama.cpp available?                           |
    |    TensorRT-LLM available?                        |
    |                                                   |
    +-------------------------+-------------------------+
                              |
                              v
                     Model Runtime Profile
                              |
               +--------------+--------------+
               |                             |
               v                             v
         llama.cpp                       TensorRT-LLM
         GGUF backend                    TRT backend
               |                             |
         CUDA offload                     CUDA
         Multi-GPU                        Tensor parallel
         :8080                            :8081
               |                             |
               +--------------+--------------+
                              |
                              v
                    Runtime Endpoint Layer
                              |
                         OpenAI-style API
                              |
                              v
                    Internal Director / Studio
```

---

## 3. Design Principles

### 3.1 Runtime-neutral Studio code

Studio functionality must depend on a runtime abstraction rather than directly depending on llama.cpp or TensorRT-LLM.

```text
ILocalInferenceRuntime
    StartAsync()
    StopAsync()
    RestartAsync()
    GetStatusAsync()
    GetCapabilitiesAsync()
    GetEndpoint()
```

Implementations:

```text
LlamaCppRuntime
TensorRtLlmRuntime
ExternalRuntime
```

### 3.2 Model profiles determine compatible runtimes

Do not assume all models can use TensorRT.

Each model profile must declare compatible execution providers.

Example:

```json
{
  "id": "qwen3-4b-q4km",
  "runtime": "llama.cpp",
  "model": "Qwen/Qwen3-4B-GGUF:Q4_K_M",
  "acceleration": {
    "cuda": "auto",
    "multiGpu": "auto",
    "splitMode": "layer",
    "gpuLayers": "all"
  },
  "contextSize": 8192
}
```

TensorRT profile:

```json
{
  "id": "example-tensorrt-model",
  "runtime": "tensorrt-llm",
  "model": "<model-or-engine>",
  "acceleration": {
    "cuda": true,
    "tensorParallel": "auto"
  }
}
```

---

## 4. Backends

### 4.1 llama.cpp

Primary use:

- GGUF models.
- Qwen local Director models.
- Broad compatibility.
- Single GPU.
- Multi-GPU.
- CPU fallback if explicitly permitted.

Default startup policy:

```text
GPU layers: all
GPU selection: automatic
Split mode: layer
Memory fitting: enabled
Context size: model/profile defined
Flash Attention: auto
```

Example WSL command:

```bash
~/.llama-app/llama serve \
    -hf Qwen/Qwen3-4B-GGUF:Q4_K_M \
    -ngl all \
    --split-mode layer \
    --fit on \
    -c 8192 \
    --host 127.0.0.1 \
    --port 8080
```

#### Multi-GPU policy

If one CUDA GPU exists:

```text
CUDA enabled
GPU offload enabled
split-mode layer
```

If two or more CUDA GPUs exist:

```text
CUDA enabled
all permitted GPUs visible
split-mode layer
automatic memory-proportional model distribution
```

Do not hard-code:

```text
--tensor-split 1,1
```

unless explicitly configured.

Different GPUs may have significantly different amounts of VRAM.

Allow advanced configuration:

```text
tensorSplit: "3,1"
devices: ["CUDA0", "CUDA1"]
```

Experimental tensor-parallel mode may be supported but must not be the default.

---

## 5. TensorRT-LLM Backend

TensorRT-LLM must be implemented as a separate runtime provider.

Do not attempt to pass a GGUF file directly through the TensorRT runtime.

Example service:

```bash
trtllm-serve <MODEL_OR_ENGINE> \
    --tp_size 2 \
    --host 127.0.0.1 \
    --port 8081
```

TensorRT runtime endpoint:

```text
http://127.0.0.1:8081
```

Expected endpoints:

```text
/health
/metrics
/version
/v1/models
/v1/chat/completions
/v1/completions
```

Tensor-parallel size should be resolved from the model profile and compatible GPU topology, not blindly set to every detected GPU.

---

## 6. Hardware Discovery

Create a single GPU discovery service.

Suggested interface:

```text
IGpuDiscoveryService
```

Responsibilities:

- Determine whether WSL is installed.
- Determine whether the configured WSL distro is available.
- Execute `nvidia-smi` inside WSL.
- Detect all CUDA-visible NVIDIA GPUs.
- Determine GPU names.
- Determine VRAM total.
- Determine VRAM available.
- Determine driver version.
- Determine CUDA compatibility.
- Return structured results.

Example detection command:

```bash
nvidia-smi \
  --query-gpu=index,name,memory.total,memory.free,driver_version \
  --format=csv,noheader,nounits
```

Result model:

```text
GpuInfo
    Index
    Name
    TotalVramMiB
    FreeVramMiB
    DriverVersion
    IsCudaAvailable
```

---

## 7. Runtime Capability Detection

At Studio startup, detect:

```text
WSL
CUDA
NVIDIA GPU(s)
llama.cpp
TensorRT-LLM
configured models
ports
existing runtime processes
existing health endpoints
```

Create:

```text
RuntimeCapabilities
```

Example:

```text
WslAvailable: true
CudaAvailable: true
CudaGpuCount: 1
LlamaCppAvailable: true
TensorRtLlmAvailable: false
LlamaPortAvailable: true
TensorRtPortAvailable: true
```

---

## 8. Startup Sequence

Required sequence:

```text
1. WinUI begins startup.
2. Load runtime configuration.
3. Probe configured runtime endpoint.
4. If healthy:
       reuse existing runtime.
5. Otherwise:
       inspect WSL.
6. Detect CUDA devices.
7. Detect installed runtime providers.
8. Resolve selected model profile.
9. Validate runtime/model compatibility.
10. Construct launch command.
11. Start runtime.
12. Poll /health.
13. Query /v1/models.
14. Verify expected model.
15. Mark runtime Ready.
16. Enable inference.
```

---

## 9. Runtime State Machine

Use explicit states:

```text
Stopped
Detecting
Starting
LoadingModel
Ready
Degraded
Stopping
Failed
```

Do not treat a successfully created process as a ready model server.

`Ready` requires a successful runtime health check.

---

## 10. Health Checks

llama.cpp:

```text
GET http://127.0.0.1:8080/health
GET http://127.0.0.1:8080/v1/models
```

TensorRT-LLM:

```text
GET http://127.0.0.1:8081/health
GET http://127.0.0.1:8081/v1/models
GET http://127.0.0.1:8081/version
```

Health polling should use short request timeouts, bounded retries, an overall startup timeout, and cancellation tokens.

Do not freeze the WinUI UI thread.

---

## 11. Port Management

Defaults:

```text
llama.cpp:       8080
TensorRT-LLM:    8081
```

Before starting a process:

```text
Check endpoint health.
Check port occupancy.
Determine whether existing service belongs to Studio.
```

Never kill an arbitrary process solely because it occupies a configured port.

---

## 12. WSL Launcher

Create one standardized Windows-to-WSL process launcher.

Responsibilities:

- Invoke `wsl.exe`.
- Specify distro if configured.
- Use `bash -lc`.
- Quote arguments safely.
- Capture stdout.
- Capture stderr.
- Retain process ID information where possible.
- Support cancellation.
- Support graceful shutdown.

Conceptual command:

```powershell
wsl.exe -d <distro> -- bash -lc "<runtime command>"
```

Avoid duplicating WSL command construction across the application.

---

## 13. WSL Runtime Scripts

Prefer stable scripts on the Linux side instead of constructing enormous shell commands from C#.

Proposed location:

```text
~/edmg/runtime/
```

Scripts:

```text
start-llama.sh
start-tensorrt.sh
probe-gpu.sh
probe-runtime.sh
stop-runtime.sh
```

---

## 14. Runtime Ownership

Studio needs to know whether it owns a runtime process.

Track:

```text
StartedByStudio
RuntimeType
Port
ModelId
PID
WSLPid if available
StartTimestamp
SessionId
```

Only automatically terminate a runtime if:

```text
StartedByStudio == true
```

An externally started server should normally remain running.

---

## 15. Configuration

Example:

```json
{
  "localRuntime": {
    "enabled": true,
    "autoStart": true,
    "preferredBackend": "auto",
    "wslDistro": "",
    "cuda": "auto",
    "multiGpu": "auto",
    "llama": {
      "executable": "~/.llama-app/llama",
      "port": 8080,
      "gpuLayers": "all",
      "splitMode": "layer",
      "fit": true
    },
    "tensorRt": {
      "enabled": true,
      "port": 8081,
      "tensorParallel": "auto"
    }
  }
}
```

---

## 16. Backend Selection Algorithm

```text
if selected model explicitly requires TensorRT:
    if TensorRT available and profile valid:
        TensorRT
    else:
        show unavailable reason

else if selected model is GGUF:
    llama.cpp

else if model supports multiple backends:
    use configured preference

else:
    no compatible local runtime
```

Do not silently execute a model through an unvalidated backend.

---

## 17. Fallback Strategy

```text
Preferred compatible backend
        |
        v
CUDA accelerated compatible backend
        |
        v
Alternative compatible local backend
        |
        v
CPU only if explicitly allowed
        |
        v
Unavailable with actionable error
```

Fallback requires model compatibility.

---

## 18. Logging

Suggested locations:

```text
logs/runtime/
```

or WSL:

```text
~/.cache/edmg/
```

Files:

```text
llama-server.log
tensorrt-server.log
gpu-detection.log
runtime-orchestrator.log
```

Each launch record should include:

```text
timestamp
runtime
model
command excluding secrets
GPU list
GPU memory
CUDA status
port
startup duration
health result
exit code
failure reason
```

---

## 19. Security

Runtime servers should default to:

```text
127.0.0.1
```

Do not default to:

```text
0.0.0.0
```

If remote binding is implemented later:

- Require explicit opt-in.
- Require authentication.
- Display a security warning.
- Do not use permissive CORS without justification.

---

## 20. WinUI Integration

WinUI must expose runtime status but must not contain backend-specific orchestration logic inside views.

UI communicates with:

```text
ILocalRuntimeOrchestrator
```

Suggested displayed information:

```text
Internal Director

Runtime: llama.cpp
Status: Ready
Model: Qwen3 4B Q4_K_M
Acceleration: CUDA
GPU: NVIDIA RTX 4050 Laptop GPU
GPU count: 1
Context: 8192
Endpoint: localhost:8080
```

Future multi-GPU example:

```text
Acceleration: CUDA / Multi-GPU
GPUs: 2
Split: Layer
```

TensorRT:

```text
Runtime: TensorRT-LLM
Acceleration: CUDA / Tensor Parallel
TP: 2
```

---

## 21. Controls

Provide:

```text
Start
Stop
Restart
Open Logs
Refresh Hardware
Test Runtime
```

Advanced options may include:

```text
Runtime Auto
llama.cpp
TensorRT-LLM

CUDA Auto / Disabled
Multi-GPU Auto / Disabled
Split Layer / Tensor
Context Size
Ports
```

---

## 22. Existing Render/Provider Integration

Do not duplicate runtime selection logic in render pages.

Preserve:

- render-profile snapshots,
- queued render settings,
- resumable cache behavior,
- TensorRT opt-outs,
- provider dispatch,
- Workspace handoffs,
- Reactive handoffs.

Runtime configuration used by a queued request should be snapshotted when required for deterministic execution.

---

## 23. Tests

### Unit tests

Test:

```text
GPU parsing
0 GPU
1 GPU
2+ GPU
mixed VRAM sizes
CUDA unavailable
WSL unavailable
llama unavailable
TensorRT unavailable
port occupied
healthy existing server
unhealthy server
runtime selection
model compatibility
profile override
automatic split selection
runtime ownership
shutdown semantics
```

### Integration tests

Test:

```text
Studio -> WSL
WSL -> nvidia-smi
Studio -> llama.cpp
Studio -> TensorRT-LLM
/health polling
/v1/models
chat completion
runtime restart
runtime crash recovery
Studio shutdown
```

### Regression tests

All existing backend/Core/WinUI tests must continue to pass.

---

## 24. Implementation Phases

### Phase 1 — Runtime abstractions

Implement:

```text
ILocalInferenceRuntime
ILocalRuntimeOrchestrator
IGpuDiscoveryService
IWslCommandRunner
RuntimeCapabilities
RuntimeStatus
RuntimeProfile
GpuInfo
```

### Phase 2 — Hardware detection

Implement:

```text
WSL detection
nvidia-smi probing
CUDA GPU enumeration
VRAM parsing
runtime executable detection
```

### Phase 3 — llama.cpp orchestration

Implement:

```text
existing-server probe
launch
health polling
GPU offload
multi-GPU layer splitting
logging
shutdown
restart
```

Validate Qwen3 4B GGUF first.

### Phase 4 — WinUI startup integration

Add asynchronous runtime initialization after application/service construction.

### Phase 5 — TensorRT-LLM provider

Implement independent TensorRT runtime provider.

### Phase 6 — Multi-GPU validation

Validate:

```text
single GPU
dual GPU
unequal GPUs
explicit device list
automatic layer splitting
TensorRT TP
```

### Phase 7 — UI controls and diagnostics

Implement:

```text
status panel
runtime selector
restart
logs
GPU details
runtime test
error details
```

### Phase 8 — Production hardening

Add:

```text
timeouts
cancellation
port collision handling
process ownership
crash recovery
safe shutdown
configuration migration
telemetry/log redaction
security review
```

---

## 25. Acceptance Criteria

Implementation is complete when:

- Studio launches without requiring the user to manually open WSL.
- Studio detects available NVIDIA CUDA GPUs.
- Studio detects GPU count correctly.
- A one-GPU system automatically uses CUDA.
- A multi-GPU system can automatically use compatible GPUs.
- llama.cpp runs GGUF models using GPU offload.
- llama.cpp defaults to stable layer splitting for multi-GPU.
- TensorRT-LLM is treated as a separate execution provider.
- TensorRT-compatible profiles can start TensorRT-LLM automatically.
- Studio waits for runtime health before inference.
- Existing healthy runtimes are reused.
- Studio does not kill external runtime processes.
- Runtime failures produce actionable diagnostics.
- UI remains responsive during startup.
- APIs bind to localhost by default.
- Existing automated tests continue passing.
- New orchestration logic has unit and integration coverage.
- A successful live inference is demonstrated through each supported backend.

---

## 26. Initial Reference Configuration

For the current Qwen GGUF Director:

```text
Model:
Qwen/Qwen3-4B-GGUF:Q4_K_M

Backend:
llama.cpp

CUDA:
Auto

GPU Layers:
All

Multi-GPU:
Auto

Split Mode:
Layer

Memory Fit:
On

Context:
8192

Host:
127.0.0.1

Port:
8080
```

Expected WSL command:

```bash
~/.llama-app/llama serve \
  -hf Qwen/Qwen3-4B-GGUF:Q4_K_M \
  -ngl all \
  --split-mode layer \
  --fit on \
  -c 8192 \
  --host 127.0.0.1 \
  --port 8080
```

---

## 27. Definition of Done

```text
Launch RUN_ME.bat
      |
      v
Studio opens
      |
      v
WSL detected automatically
      |
      v
CUDA GPU detected
      |
      v
Correct runtime selected
      |
      v
Model server launched
      |
      v
Health check succeeds
      |
      v
GPU acceleration verified
      |
      v
Internal Director request succeeds
      |
      v
Runtime status visible in WinUI
```

The same architecture must remain valid when additional CUDA GPUs and TensorRT-compatible model profiles are added later.
