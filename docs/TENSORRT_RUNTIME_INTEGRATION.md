# Optional TensorRT component runtime

Implementation checkpoint, 2026-09-21. This is a staged implementation of
`EDMG_TensorRT_Integration_Blueprint.md`, not production qualification of every phase.

The existing Internal Renderer owns rendering. `edmg_studio_backend/runtime`
provides backend policy, explicit component capabilities, an isolated native child,
content-addressed engines, numerical validation, benchmark receipts, and PyTorch
fallback. Model package admission stays in `services/model_runtime_registry.py`.
The existing job store, worker dispatcher and cross-process model admission lock
schedule diagnostic/optimization jobs. Qwen, Whisper, external providers and video
model adapters retain their existing paths.

## Supported components

The managed SD1.5 runtime has two independently selectable TensorRT components:

| Component | TensorRT path | Existing-runtime path |
| --- | --- | --- |
| UNet | Named multi-input/multi-output bindings, batch 1-2, bounded dynamic latent spatial profiles, FP32/FP16 | Diffusers UNet |
| AutoencoderKL VAE decoder | One latent input, batch 1, static output profiles from 64 to 1024 pixels per axis, FP32/FP16 | Diffusers VAE decoder |
| Text encoder and scheduler | Unsupported by the component runtime | Diffusers/PyTorch |

This forms a hybrid pipeline: the UNet and VAE select and fall back independently,
while text encoding and scheduling stay native to the existing Diffusers pipeline.
Alternate VAE weight layouts retain PyTorch VAE decoding without disabling an
otherwise eligible UNet. LoRA/PEFT, ControlNet, IP Adapter, extra conditioning,
custom or merged weights, and other graph mutations retain the existing runtime
unless their exact graph is represented by a validated engine identity.

SDXL, SD3, Flux, SVD, AnimateDiff, LTX 2.5, WAN, and HunyuanVideo 1.5 remain
explicitly unsupported by the managed TensorRT component runtime. Their diagnostics
rows include a concrete unsupported reason and retain the existing model provider.
Qwen remains on llama.cpp and Whisper remains on CTranslate2; neither is presented as
a diffusion TensorRT adapter.

Automatic/Compatibility use existing numerically validated engines only and check
both the kernel benchmark and the actual transfer/IPC round-trip before preferring
TensorRT. Performance/TensorRT can build on first use when permitted. Failed native
workers are disposed before decoding the unchanged latent with PyTorch; strict mode
instead fails. Failed engines are quarantined and skipped for the manager lifetime.
Model weights are never deleted by cache cleanup.

## Settings and API

WinUI Settings has an AI runtime / NVIDIA acceleration expander. Electron Settings
has the same controls under GPU / Render Runtime. Both consume:

- `GET /v1/runtime/status`
- `POST /v1/runtime/settings`
- `POST /v1/runtime/jobs` (`diagnose`, `optimize`, `optimize_all`, `rebuild`, or
  `validate`, plus model family, component, GPU index, precision, and bounded profile)
- `DELETE /v1/runtime/tensorrt/cache/{engine_id}`

Settings are persisted in the existing render-provider settings store. GPU index is
intentionally request-scoped rather than a persisted global setting: WinUI sends it
on runtime jobs and per-render overrides, while status returns the detected `gpus`
list. Runtime jobs use a dedicated diagnostics project in the existing queue;
existing job endpoints provide progress, logs, cancellation and result retrieval.
Optimize defaults to a 512-by-512 SD1.5 decoder for backward compatibility; native
controls explicitly select UNet or VAE. Optimize-all processes every registered
buildable component.
Rebuild clears only matching managed engine artifacts and then performs a full build
and numerical validation. Validate refuses to build, resolves the exact cached
identity, verifies its manifest/checksum, deserializes it on the requested GPU, and
executes deterministic component-shaped inputs with finite-output checks. It preserves
the numerical reference-validation receipt created during build; it does not claim a
new reference comparison. Delete uses the selected status row's exact engine ID.

Engine identities include model and component hashes, adapter/compiler settings,
TensorRT/CUDA/framework versions, GPU identity and compute capability, precision,
optimization profile, plugin metadata, and graph-mutation metadata. Cache lookup
requires the exact identity, a validation receipt, and the engine checksum. Stale or
corrupt records are rejected or quarantined rather than selected.

## Optional dependencies and isolation

Source workers use the backend interpreter. Packaged workers have a `runtime-worker`
CLI entry point. The current CUDA onedir candidate passed isolated frozen server-health
and worker-protocol startup tests; packaged model compilation and install lifecycle are
separate qualification gates.
Installed TensorRT bindings are preferred. An optional SDK folder (or
`EDMG_TENSORRT_ROOT`) activates its interpreter-matching Windows wheel only in the
child, extracted under `data/tensorrt/bindings`. SDK DLL directories are child-local.
Downloaded SDKs are reported without changing the installed runtime. No global PATH,
CUDA, cuDNN or PyTorch installation is changed.

The installed matching PyTorch 2.11 / Torch-TensorRT 2.11 / TensorRT 10 combination
uses torch export and raw engine compilation. TensorRT 11 uses the ONNX compiler
path, which requires the optional ONNX package; it has not yet been qualified with
a real component here. TensorRT 11 synthetic probing does not require ONNX.

## Evidence at the checkpoint

- TensorRT 10.15.1.29, CUDA 13.0, PyTorch/Torch-TensorRT 2.11, and three RTX A6000
  devices were detected. Synthetic engine build, serialization, fresh deserialization,
  and inference passed independently on GPU 0, GPU 1, and GPU 2. This is three separate
  device tests, not one inference distributed across GPUs.
- On GPU 0, a fresh managed SD1.5 FP16 VAE decoder was built, numerically compared,
  serialized, and published as engine
  `6230674939e0a66e19a531bc0c61bada5afc1e4c1242b89eab0784768afff608`.
  Build time was approximately 37.38 seconds; measured component execution was
  approximately 39.84 ms versus 57.74 ms for PyTorch. Maximum absolute error was
  0.12209 against the component limit 0.15; all other gates also passed.
- On GPU 0, a fresh managed SD1.5 FP16 UNet was built, numerically compared at batches
  1 and 2, serialized, and published as engine
  `70ec69eaadbc586e52368e6a46c6e977b35168224c8e2c0cabda40050bc0fb2c`.
  Build time was approximately 388.49 seconds; measured component execution was
  approximately 69.11 ms versus 117.61 ms for PyTorch. Mean absolute error was
  0.003643 against the component limit 0.006 and P99 error was 0.013672 against 0.02;
  all other gates also passed.
- A new Python process loaded both exact engines with `allow_build=False`, reported
  `cache: hit`, deserialized them, and executed finite VAE `[1,3,512,512]` and UNet
  `[1,4,64,64]` outputs without rebuilding.
- Current automated results are: component/runtime `48 passed`; Director `14 passed`;
  complete backend `1060 passed, 2 skipped`; repository packaging/static `12 passed,
  2 skipped` before supplying the frozen executable; packaging/signing Node `39 passed,
  1 skipped`; native Core Debug `552 passed`; WinUI Debug x64 build 0 warnings/errors.
- The current CUDA onedir backend subsequently passed both opt-in frozen startup tests:
  server health without a source/Python path and the `runtime-worker` protocol.
- The native Debug x64 executable stayed alive while its supervisor started a healthy
  source backend reporting version 1.2.0. This proves process startup and supervision,
  not interactive page behavior.
- Local generated engine evidence is under backend
  `data/runtime-validation/real-sd15-candidate/`; it is validation output and is not
  release source or staged content. Saved logs use `%TEMP%\tensorrt-*` names.

## Current validation and remaining qualification

The current candidate has real managed-model evidence for the claimed SD1.5 UNet and
VAE component paths on GPU 0. It does not qualify TensorRT for any other model family.
The live render also exposed a Diffusers compatibility defect: `AutoencoderKL.decode`
accepts but ignores a generator argument, while the wrapper had treated any generator
as unsupported custom behavior. The wrapper now permits that semantically inert
argument while continuing to reject arbitrary kwargs, slicing, tiling, graph mutations,
shape mismatches, and precision mismatches; focused and full regressions pass.

Interactive Settings, Models, and Render page operation was not exercised because no
UI automation driver was available; those surfaces have compiled XAML/code and typed API
coverage only. Remaining external or separate release gates include end-to-end render
VRAM profiling, TensorRT 11 real-component qualification, packaged Torch-TensorRT model
compilation (the frozen build warns that `torchtrt.dll` is unresolved), production
sign/install and clean-machine lifecycle, Store qualification, and SDK-backed native
VST3 hosting.
Additional model families remain unsupported by design until they have their own real
adapter, build, validation, deserialization, execution, dispatch, and fallback evidence.


## Validation schema 2

The current SD1.5 VAE component engine identity uses adapter version 3 and the UNet
identity uses adapter version 2. ONNX-based identities include the ONNX version. These
versions force new content-addressed keys after adapter or validation-policy changes;
older engines are not deleted and cannot be mistaken for current validation.

FP32 validation no longer rejects an engine solely because one decoded value crosses
the previous 0.005 maximum-absolute-error boundary. Version 2 evaluates max and mean
absolute error, RMSE, P99 absolute error, PSNR and a dependency-free global SSIM
statistic across the fixed validation seeds. Maximum relative error is recorded for
diagnostics but is not a hard gate because reference values near zero make it
unstable as a VAE acceptance criterion.

The default FP32 maximum-absolute threshold is 0.0075, while mean error, RMSE, P99,
PSNR and SSIM independently constrain broad output drift. Strict execution and
no-fallback behavior remain unchanged.

The existing `services/tensorrt_standalone.py` implementation remains a separate,
verified external-bundle SD1.5 UNet route. The managed component runtime can now also
replace the ordinary Diffusers UNet after its own build and validation; diagnostics
report the standalone and managed capabilities separately.

## Multi-source routing

The component registry now classifies managed model sources before selecting a runtime.
It distinguishes ONNX graphs, PyTorch `.pt`/`.pth` checkpoints, Hugging Face layouts
with complete safetensors/config metadata, prebuilt `.engine`/`.plan` files, GGUF, and
unknown or ambiguous directories. Recognition is not a success claim: the status API
reports source kind, architecture, selected route, compiler, support reason, validation,
fallback, and active acceleration separately.

- ONNX selects the existing TensorRT parser route for registered components.
- Registered PyTorch checkpoints select Torch-TensorRT, or an explicitly available
  `torch.compile` TensorRT backend. Unknown architectures fail or use the configured
  existing-runtime fallback.
- Hugging Face safetensors require readable architecture config and every indexed shard
  before the Torch-TensorRT route is offered.
- Prebuilt TensorRT engines require registered binding contracts plus deserialization
  and execution validation before atomic cache publication.
- GGUF always remains on llama.cpp and is labeled non-TensorRT.

Cache identities include source hashes, route/compiler and versions, precision, profile,
and device compatibility fields while retaining legacy identity lookup. WinUI consumes
the backend decision and never infers support from a filename. `accelerating` remains
false until a validated execution receipt proves that TensorRT ran.

The CUDA dependency lane pins Torch-TensorRT and TensorRT and now also includes NVIDIA
Model Optimizer plus the Windows Triton package. Their presence enables compatible
compiler/operator paths; it does not make an unregistered model architecture supported.
