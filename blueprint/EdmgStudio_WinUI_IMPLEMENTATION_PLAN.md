# EDMG Studio WinUI
## Local AI Runtime Orchestration Implementation Plan

**Target file:** `/studio/edmg-studio-winui/IMPLEMENTATION_PLAN.md`

---

## 1. Scope

Implement WinUI-side lifecycle management for local AI runtimes used by EDMG Studio.

The WinUI application should automatically coordinate:

- WSL startup/access.
- NVIDIA GPU discovery.
- CUDA verification.
- llama.cpp lifecycle.
- TensorRT-LLM lifecycle.
- Multi-GPU selection.
- Runtime health.
- Model readiness.
- Runtime status UI.
- Logs and diagnostics.

Backend-specific process management must reside in services, not pages or view code.

---

## 2. Target Service Architecture

Add or adapt services equivalent to:

```text
EdmgStudio.Core
|
+-- Runtime
    |
    +-- ILocalRuntimeOrchestrator
    +-- ILocalInferenceRuntime
    +-- IWslCommandRunner
    +-- IGpuDiscoveryService
    +-- IRuntimeHealthService
    +-- IRuntimeProfileResolver
    |
    +-- LlamaCppRuntime
    +-- TensorRtLlmRuntime
```

Suggested supporting models:

```text
RuntimeStatus
RuntimeState
RuntimeCapabilities
RuntimeLaunchResult
RuntimeProfile
GpuInfo
GpuTopology
RuntimeOwnership
```

Use the repository's existing naming conventions and DI architecture where equivalents already exist.

Do not create duplicate abstractions when an existing provider/runtime service can be extended cleanly.

---

## 3. Application Startup

Locate the existing WinUI composition/startup path.

Register runtime services during dependency injection setup.

Do not start long-running model loading synchronously inside the UI constructor.

Recommended sequence:

```text
App startup
    |
    v
Build services
    |
    v
Create main window
    |
    v
Show shell
    |
    v
Start runtime initialization asynchronously
```

The application should remain usable while the model loads.

---

## 4. Runtime Orchestrator

`ILocalRuntimeOrchestrator` should be the primary WinUI-facing API.

Suggested interface:

```csharp
public interface ILocalRuntimeOrchestrator
{
    RuntimeStatus CurrentStatus { get; }

    event EventHandler<RuntimeStatus>? StatusChanged;

    Task InitializeAsync(CancellationToken cancellationToken = default);

    Task<RuntimeStatus> GetStatusAsync(
        CancellationToken cancellationToken = default);

    Task StartAsync(
        string? profileId = null,
        CancellationToken cancellationToken = default);

    Task StopAsync(
        CancellationToken cancellationToken = default);

    Task RestartAsync(
        CancellationToken cancellationToken = default);
}
```

Pages and ViewModels should consume this service.

They should not execute `wsl.exe` directly.

---

## 5. WSL Command Runner

Create one reusable WSL execution abstraction.

Example responsibility:

```csharp
Task<CommandResult> RunAsync(
    string command,
    CancellationToken cancellationToken);
```

Requirements:

- `wsl.exe` execution.
- Configurable distro.
- `bash -lc`.
- stdout capture.
- stderr capture.
- exit code.
- cancellation.
- timeouts.
- safe argument escaping.
- optional detached server launch.

Never build WSL commands in ViewModels.

---

## 6. GPU Discovery Service

Implement WSL-side NVIDIA discovery.

Command:

```bash
nvidia-smi \
  --query-gpu=index,name,memory.total,memory.free,driver_version \
  --format=csv,noheader,nounits
```

Parse into:

```csharp
public sealed record GpuInfo(
    int Index,
    string Name,
    long TotalMemoryMiB,
    long FreeMemoryMiB,
    string DriverVersion);
```

Expose:

```csharp
Task<GpuTopology> DetectAsync(...)
```

`GpuTopology` should include:

```text
CUDA available
GPU count
GPU list
total VRAM
free VRAM
```

---

## 7. llama.cpp Provider

Implement:

```text
LlamaCppRuntime
```

Responsibilities:

- Detect executable.
- Probe current endpoint.
- Reuse healthy running server.
- Resolve active model profile.
- Generate command.
- Start server in WSL.
- Capture logs.
- Poll health.
- Verify model endpoint.
- Stop only owned instance.

Initial command:

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

## 8. llama.cpp Multi-GPU Logic

Detection:

```text
GPU count == 0
    -> CUDA unavailable

GPU count == 1
    -> normal CUDA offload

GPU count > 1
    -> multi-GPU layer split
```

Default:

```text
--split-mode layer
```

Do not calculate a manual split unless the model profile or user requests one.

Automatic llama.cpp fitting should remain available.

Advanced profile fields:

```text
DeviceList
TensorSplit
SplitMode
GpuLayers
Fit
ContextSize
```

Experimental:

```text
SplitMode = tensor
```

must not become the default until separately validated.

---

## 9. TensorRT-LLM Provider

Implement:

```text
TensorRtLlmRuntime
```

separately from `LlamaCppRuntime`.

Responsibilities:

- Detect installation.
- Validate configured model/engine compatibility.
- Determine usable GPU topology.
- Resolve tensor-parallel configuration.
- Launch server.
- Probe health.
- Query version.
- Query models.
- Capture metrics.
- Shutdown owned process.

Conceptual launch:

```bash
trtllm-serve <model-or-engine> \
  --tp_size <resolved> \
  --host 127.0.0.1 \
  --port 8081
```

Do not route GGUF profiles into this provider.

---

## 10. Profile Resolver

Create:

```text
IRuntimeProfileResolver
```

Input:

```text
selected Studio model
global acceleration settings
hardware topology
runtime availability
per-render override
```

Output:

```text
ResolvedRuntimeProfile
```

Include:

```text
RuntimeType
Model
Port
CUDA
GpuDevices
MultiGpu
SplitMode
TensorSplit
TensorParallelSize
ContextSize
AdditionalArguments
```

Preserve per-render overrides and queued-request snapshots.

---

## 11. Runtime States

Use:

```csharp
public enum RuntimeState
{
    Stopped,
    Detecting,
    Starting,
    LoadingModel,
    Ready,
    Degraded,
    Stopping,
    Failed
}
```

`RuntimeStatus` should include:

```text
State
Runtime
Model
Endpoint
Acceleration
GPU names
GPU count
Error
LastUpdated
StartedByStudio
```

---

## 12. Health Service

Create common health checks.

Example interface:

```csharp
public interface IRuntimeHealthService
{
    Task<RuntimeHealthResult> ProbeAsync(
        Uri endpoint,
        CancellationToken cancellationToken = default);
}
```

For llama.cpp:

```text
/health
/v1/models
```

For TensorRT:

```text
/health
/version
/v1/models
```

Health polling must happen asynchronously.

---

## 13. Startup Polling

Use bounded retries.

Concept:

```csharp
while (!cancellationToken.IsCancellationRequested)
{
    var health = await ProbeAsync(...);

    if (health.IsReady)
        return;

    if (startupDeadlineExceeded)
        throw new RuntimeStartupException(...);

    await Task.Delay(retryDelay, cancellationToken);
}
```

Do not use `Thread.Sleep(...)` on UI execution paths.

---

## 14. Process Ownership

Record whether Studio launched the service.

Example:

```csharp
public sealed record RuntimeOwnership(
    bool StartedByStudio,
    int? WindowsProcessId,
    int? WslProcessId,
    DateTimeOffset StartedAt);
```

Shutdown rule:

```text
External server:
    leave running.

Studio-owned server:
    optionally stop during Studio shutdown
    according to configuration.
```

---

## 15. Main Runtime Status UI

Add a compact status area.

Example:

```text
Internal Director
────────────────────────
● Ready

Runtime     llama.cpp
Model       Qwen3 4B Q4_K_M
Compute     CUDA
GPU         RTX 4050 Laptop GPU
GPUs        1
Context     8192
Port        8080
```

Loading:

```text
● Loading model...
```

TensorRT:

```text
● Ready

Runtime     TensorRT-LLM
Compute     CUDA
Parallel    TP × 2
GPUs        2
Port        8081
```

---

## 16. UI Controls

Provide:

```text
Start
Stop
Restart
Refresh
Open Logs
Test
```

Settings:

```text
Auto-start runtime
Runtime: Auto / llama.cpp / TensorRT-LLM
CUDA: Auto / Disabled
Multi-GPU: Auto / Disabled
```

Advanced section:

```text
GPU devices
Split mode
Tensor split
Tensor parallel size
Context size
Ports
```

---

## 17. Error UX

Display actionable failures.

Examples:

```text
CUDA unavailable
WSL unavailable
NVIDIA GPU not visible inside WSL
llama.cpp not installed
TensorRT-LLM not installed
Selected model does not support TensorRT
Port 8080 already occupied
Runtime timed out while loading
Model failed to load
Insufficient GPU memory
```

Show actions such as:

```text
View Log
Retry
Switch Runtime
Open Settings
```

when applicable.

---

## 18. Logging

Use the existing application logging abstraction if present.

Add structured categories:

```text
Runtime.Orchestrator
Runtime.WSL
Runtime.GPU
Runtime.Llama
Runtime.TensorRT
Runtime.Health
```

Do not log secrets or credentials.

Include command arguments only after sanitization.

---

## 19. Configuration Persistence

Use existing Studio settings/profile storage where possible.

Suggested settings:

```text
LocalRuntime.Enabled
LocalRuntime.AutoStart
LocalRuntime.PreferredRuntime
LocalRuntime.StopOnExit
LocalRuntime.WslDistro

Llama.Executable
Llama.Port
Llama.GpuLayers
Llama.SplitMode
Llama.Fit
Llama.ContextSize

TensorRT.Enabled
TensorRT.Port
TensorRT.TensorParallelSize
```

Defaults:

```text
AutoStart = true
PreferredRuntime = auto
CUDA = auto
MultiGpu = auto
Llama.Port = 8080
TensorRT.Port = 8081
SplitMode = layer
```

---

## 20. Studio Shutdown

During shutdown:

```text
Cancel startup probes.
Cancel pending health checks.
Stop owned runtime if configured.
Do not stop external runtime.
Flush runtime logs.
Dispose HTTP clients/services.
```

Shutdown must not hang the WinUI process indefinitely.

---

## 21. Dependency Injection

Register abstractions as services rather than constructing them manually.

Conceptually:

```csharp
services.AddSingleton<IWslCommandRunner, WslCommandRunner>();
services.AddSingleton<IGpuDiscoveryService, GpuDiscoveryService>();
services.AddSingleton<IRuntimeHealthService, RuntimeHealthService>();

services.AddSingleton<LlamaCppRuntime>();
services.AddSingleton<TensorRtLlmRuntime>();

services.AddSingleton<
    ILocalRuntimeOrchestrator,
    LocalRuntimeOrchestrator>();
```

Adapt to the project's existing DI framework.

---

## 22. Tests

Add Core tests for:

```text
GPU CSV parsing
0/1/2+ GPU topology
runtime profile resolution
CUDA unavailable
runtime unavailable
health state conversion
multi-GPU selection
TensorRT TP resolution
model/backend incompatibility
port collisions
process ownership
restart
shutdown
```

Mock:

```text
IWslCommandRunner
IRuntimeHealthService
IGpuDiscoveryService
```

Avoid requiring actual CUDA hardware for normal unit tests.

---

## 23. Hardware Integration Tests

Create optional hardware-tagged tests.

Test on a CUDA machine:

```text
nvidia-smi visible
llama executable visible
server starts
/health succeeds
/v1/models succeeds
completion succeeds
GPU memory increases
```

Multi-GPU hardware test when available:

```text
2+ CUDA GPUs detected
all intended GPUs selected
model split occurs
request succeeds
```

TensorRT hardware test:

```text
TensorRT runtime detected
compatible model starts
/health succeeds
/v1/models succeeds
request succeeds
metrics available
```

---

## 24. Regression Requirements

Before merge:

```text
Backend Python tests pass.
Core tests pass.
WinUI builds without errors.
WinUI tests pass.
Render profile compatibility preserved.
Queued request behavior preserved.
Provider dispatch preserved.
TensorRT disable switches preserved.
Workspace/Reactive paths preserved.
```

A successful build is not sufficient to claim UI verification.

Perform a live WinUI launch when policy/environment permits it.

---

## 25. Recommended Implementation Order

1. Add models/interfaces only.
2. Add WSL and NVIDIA GPU discovery.
3. Add health probing.
4. Add llama.cpp provider.
5. Add runtime orchestrator.
6. Integrate orchestrator into app startup.
7. Add WinUI status.
8. Add controls/settings.
9. Add TensorRT-LLM provider.
10. Validate multi-GPU.
11. Add crash recovery and production hardening.

---

## 26. First Working Milestone

```text
Windows
   |
   v
WinUI
   |
   v
wsl.exe
   |
   v
Ubuntu
   |
   v
NVIDIA CUDA
   |
   v
llama.cpp
   |
   v
Qwen3 4B Q4_K_M
   |
   v
localhost:8080
   |
   v
Internal Director
```

Configuration:

```text
Runtime        llama.cpp
Model          Qwen/Qwen3-4B-GGUF:Q4_K_M
CUDA           Auto
GPU Layers     All
Multi-GPU      Auto
Split          Layer
Fit            On
Context        8192
Port           8080
```

---

## 27. Multi-GPU Milestone

With two CUDA GPUs visible:

```text
WinUI
   |
   v
GPU Discovery
   |
   +--> CUDA0
   |
   +--> CUDA1
   |
   v
llama.cpp
--split-mode layer
   |
   v
Model distributed across GPUs
```

No code change should be required to move from one GPU to multiple GPUs.

---

## 28. TensorRT Milestone

```text
WinUI
   |
   v
Runtime Profile Resolver
   |
   v
TensorRT-compatible model
   |
   v
TensorRtLlmRuntime
   |
   v
trtllm-serve
   |
   v
CUDA / TP
   |
   v
localhost:8081
   |
   v
Studio
```

The same Director/provider-facing layer should work against either runtime where API capabilities overlap.

---

## 29. Definition of Done

WinUI implementation is complete when:

- `RUN_ME.bat` launches Studio.
- Studio automatically discovers WSL.
- CUDA detection occurs without manual shell commands.
- GPU topology appears in runtime diagnostics.
- The Qwen GGUF Director starts automatically.
- CUDA offload is verified.
- Multi-GPU is automatically available when supported.
- TensorRT profiles start the TensorRT provider.
- Model readiness is determined by health checks.
- Runtime state is shown in WinUI.
- Start/stop/restart work reliably.
- Existing external runtime instances are not destroyed.
- Logs identify runtime failures clearly.
- UI stays responsive throughout model loading.
- Existing test suites remain green.
- New runtime logic has automated coverage.
- Live inference succeeds through the selected backend.
