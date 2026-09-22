# EDMG Studio Full TensorRT Capability Blueprint

Status: planning blueprint only. This document defines the next implementation program; it does not claim that every model is already TensorRT-qualified.

## Objective

Make TensorRT a Studio-wide optional capability underneath the existing Internal Renderer. Every compatible local model component may eventually use TensorRT, while every Studio workflow remains functional when TensorRT is absent, disabled, incompatible, unvalidated, too slow, or broken.

The product remains one Internal Renderer with multiple execution runtimes. TensorRT is never exposed as a separate renderer and never becomes a hard dependency.

## User contract

For ordinary users:

```text
Choose model and creative settings
Click Render
EDMG inspects hardware, model capability, validated engines, and measured benefit
EDMG selects TensorRT or the existing runtime per component
EDMG records the decision
EDMG falls back safely if TensorRT cannot execute
```

TensorRT controls are available in WinUI Settings, WinUI Render/Models advanced options, and Electron Settings. The backend remains the source of truth. The UI never imports TensorRT, loads DLLs, builds engines, or calls `trtexec.exe`.

Every render operation can independently request `auto`, `compatibility`, `performance`, `pytorch_cuda`, `tensorrt`, or explicit CPU/fallback behavior. Existing requests without runtime fields retain their current behavior.

## Non-negotiable guarantees

- Studio launch, project opening, model installation, audio analysis, Director, Reactive Lab, timeline editing, preview, rendering, export, cancel, resume, and backend restart work without TensorRT.
- TensorRT is absent-safe, broken-safe, invalid-engine-safe, and per-operation disableable.
- TensorRT failures fall back to the original runtime when the component contract permits it; strict diagnostic mode may fail the operation intentionally.
- Fallback reuses the same inputs and records the failure, engine ID, component, error, and selected fallback runtime.
- Engines are content-addressed, locally built or trusted-managed, manifest-validated, benchmarked, atomically written, invalidated, quarantined, and removable without touching model weights.
- No global CUDA/PyTorch replacement, permanent PATH mutation, System32 DLL copy, or silent dependency synchronization.
- GPUs remain separate devices. Runtime plans may assign components or jobs to GPU 0, GPU 1, and later GPUs without pretending their VRAM is one pool.
- Qwen/llama.cpp, Whisper/CTranslate2, external APIs, ComfyUI, and existing specialized runtimes remain independent adapters.

## Target architecture

```text
WinUI / Electron
       │ backend API only
       ▼
Internal Renderer
       ▼
Model Adapter + declared component capabilities
       ▼
Runtime Manager / Runtime Plan
       ├── TensorRT adapter + engine cache + validation
       ├── PyTorch CUDA adapter
       ├── llama.cpp adapter
       ├── CTranslate2 adapter
       └── explicit CPU/fallback adapter
       ▼
Hardware Manager: separate GPU devices and CPU
```

The existing `edmg_studio_backend/runtime` package becomes the shared planning and execution boundary. Model adapters declare capabilities rather than embedding runtime-selection logic.

## Runtime policy

The existing render-provider settings store gains a backward-compatible runtime object:

```json
{
  "runtime": {
    "mode": "auto",
    "enabled": true,
    "auto_build": true,
    "allow_fallback": true,
    "precision": "auto",
    "strict": false,
    "cache_enabled": true,
    "cache_limit_gb": 100,
    "package_path": ""
  }
}
```

`auto` uses only a validated engine unless policy permits a background or first-use build without surprising Compatibility users. `compatibility` uses PyTorch CUDA unless a previously validated TensorRT engine exists. `performance` prefers a validated TensorRT engine and may build. `pytorch_cuda` disables TensorRT for that operation. `tensorrt` requests TensorRT but still falls back unless strict mode is enabled. CPU requires explicit selection or an existing CPU policy.

Runtime selection considers model declaration, component, device, precision, shape/profile, cache state, engine benchmark, available VRAM, and current job circuit-breaker state. It must not guess TensorRT support from a model name.

## Component rollout matrix

Each row is a separate qualification gate. A component does not become selectable in `auto` until its reference output, engine output, benchmark, fallback, and resume behavior pass.

| Wave | Model/component candidates | Initial runtime contract |
| --- | --- | --- |
| Existing | SD1.5 VAE decoder | FP32/FP16, static profiles, batch 1; already staged |
| A | SD1.5/SDXL/SD3 VAE decoders | One model family and profile at a time; preserve tiled/sliced PyTorch paths |
| B | Text encoders and vision encoders | Fixed tokenizer/sequence or image profiles; compare embeddings and downstream output |
| C | SD UNet/transformer components | One precision, profile, GPU, and model at a time; preserve scheduler and VAE fallback |
| D | LTX VAE, text/vision encoders, transformer | Integrate only after LTX native pipeline remains independently healthy |
| E | Wan VAE, encoders, transformer | Component-level mixed execution; no assumed tensor parallelism |
| F | HunyuanVideo 1.5 VAE/encoders, then transformer | Start with the smallest stable component; distributed transformer is a later gate |
| G | Additional supported internal models | Add declared adapters individually; never mass-convert by filename convention |

Qwen GGUF and Whisper/CTranslate2 remain specialized runtimes unless a separate model-specific TensorRT project proves equivalent quality and operational behavior.

## Qualification sequence for every component

1. Declare model/component capability and unsupported shapes explicitly.
2. Capture a deterministic PyTorch reference with fixed seeds and representative profiles.
3. Export using Torch-TensorRT, ONNX, or direct TensorRT only where the adapter requires it.
4. Build inside the isolated runtime worker, never on the UI or request thread.
5. Validate serialized/deserialized engine integrity and input/output shapes.
6. Compare numerical outputs using component-appropriate tolerances and downstream output checks.
7. Benchmark initialization, build time, first execution, steady state, transfer/IPC overhead, total render time, VRAM, and GPU utilization.
8. Publish only a manifest with `ready`, validation receipt, checksum, identity, benchmark, and provenance.
9. Deliberately test missing engine, stale engine, corrupted engine, unsupported profile, OOM/execution failure, worker termination, cancel, retry, and resume.
10. Enable `auto` only when the measured end-to-end operation is beneficial; otherwise keep the engine available to explicit Performance/TensorRT mode.

## Fallback and checkpoint behavior

Runtime metadata is attached to render results and checkpoints:

```json
{
  "runtime": {
    "requested": "auto",
    "selected": "tensorrt",
    "device": "cuda:0",
    "precision": "fp16",
    "components": {"transformer": "pytorch_cuda", "vae": "tensorrt"},
    "fallback_history": []
  }
}
```

Resume must not require the original TensorRT engine or execution context. A checkpoint created with TensorRT can resume with PyTorch CUDA when model state and output format permit it.

## API and UI plan

The backend exposes shared status, policy, diagnostic, optimization, engine-list, and cache-clear operations. Long builds and diagnostics are existing jobs with progress, logs, cancellation, and result metadata.

WinUI is the priority surface:

- Settings: global policy, package status, diagnostic receipt, cache size, and cleanup.
- Models: per-model capability and optimization status.
- Render/Workspace advanced options: per-operation runtime mode, device, precision, fallback, and strict toggle.
- Job queue: build/diagnostic progress and failure/fallback history.

Electron mirrors the same backend contracts and labels. It does not create a second runtime implementation.

## Environment and packaging

The installed TensorRT runtime is preferred. An optional SDK is activated only in the isolated child process, with interpreter-matching bindings and process-local DLL search paths. The package manager records version, CUDA identity, supported GPU architectures, and source. Packaged WinUI/Electron backends need a separate frozen-bundle qualification before TensorRT is advertised in release builds.

No README may instruct users to run a global `pip install`, alter system PATH, replace PyTorch, copy DLLs into Windows directories, or install TensorRT merely to launch EDMG.

## README update scope

After this blueprint is approved, update only relevant documentation and preserve existing model-specific instructions:

- Root `README.md`: one architecture section, optional-install behavior, supported runtime modes, fallback guarantee, validation status, and links to both blueprints.
- `studio/edmg-studio/README.md`: backend API, runtime policy, job workflow, cache location, no-sync/no-global-mutation rules, and source validation commands.
- `studio/edmg-studio/python_backend/README.md`: adapter contract, component qualification checklist, worker isolation, engine manifest states, and test commands.
- `studio/edmg-studio-winui/README.md`: native Settings/Models/Render controls, backend-driven behavior, accessibility, and packaged/unpackaged limitations.
- `studio/edmg-studio/packaging/windows/README.md` and `packaging/linux/README.md`: platform-specific optional SDK discovery, bundle qualification, and fallback behavior.
- `studio/edmg-studio/docs/STUDIO_MODULARITY.md` and `STUDIO_FORGE.md`: runtime-manager ownership and component rollout policy.

Do not rewrite third-party LTX documentation or unrelated tool READMEs. Add links where useful instead of duplicating the full architecture.

## Phases and acceptance gates

### Phase 0 — Documentation and inventory

Map all existing renderer adapters, model manifests, hardware detection, settings, jobs, checkpoints, WinUI pages, Electron settings, and README claims. Mark claims as implemented, tested, live-verified, or unqualified.

### Phase 1 — Common runtime contract

Complete `RuntimeAdapter`, registry, selector, plan, per-operation request/result fields, and backend-driven status without changing default rendering behavior.

### Phase 2 — Engine infrastructure

Finish cache identity, manifest schema, atomic writes, quarantine, cleanup limits, worker progress, and security checks for trusted engine provenance.

### Phase 3 — Component waves

Qualify the matrix one component at a time. Each wave must include reference comparison, benchmark, fallback, resume, and existing renderer regression tests before enabling `auto`.

### Phase 4 — Full UI parity

Expose the same controls in native WinUI and Electron, with WinUI first. Verify keyboarding, light/dark theme, responsive layout, cancellation, and accessible status text.

### Phase 5 — Packaging and release qualification

Test TensorRT absent, installed, broken, disabled, stale, corrupted, incompatible GPU, multiple GPUs, clean install, upgrade, rollback, and packaged backend behavior. Only then update release claims.

## Definition of done

The Studio-wide capability is complete only when every enabled model/component has a qualification receipt, every unsupported component has an explicit fallback, all README claims match evidence, both frontends consume the same backend contract, and the complete regression matrix passes with TensorRT absent and present.

Until then, the feature is a staged optional capability and must not be described as universal TensorRT acceleration.
