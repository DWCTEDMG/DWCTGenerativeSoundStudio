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

## Supported first component

SD1.5 AutoencoderKL VAE decoder, unmodified default safetensors weights, one input,
batch 1, four latent channels, static output profiles from 64 to 1024 pixels per
axis, FP32 or FP16. Tiling, slicing, alternate weight layouts and unsupported
components retain PyTorch. Hunyuan/LTX/Wan transformers are not enabled.

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
- `POST /v1/runtime/jobs` (`diagnose` or `optimize`, GPU index and bounded profile)
- `DELETE /v1/runtime/tensorrt/cache/{engine_id}`

Settings are persisted in the existing render-provider settings store. Runtime jobs
use a dedicated diagnostics project in the existing queue; existing job endpoints
provide progress, logs, cancellation and result retrieval. Optimize defaults to a
512-by-512 decoder. Clear a failed engine before explicitly rebuilding it.

## Optional dependencies and isolation

Source workers use the backend interpreter. Packaged workers have a `runtime-worker`
CLI entry point; a new frozen package still requires separate qualification.
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

- WinUI Release x64 build passed, zero warnings/errors, before the final strict-mode
  checkbox addition. Final UI build/launch verification remains pending.
- Frontend typecheck passed; Settings/runtime panel tests: 12 passed.
- Focused backend runtime/diffusers/legacy TensorRT tests: 88 passed with test-process
  authentication variables cleared. The earlier inherited environment produced two
  unrelated 401 failures. No production authentication setting was changed.
- TensorRT 10.15.1.29: synthetic build/serialize/deserialize/GPU inference passed on
  GPU 0. Downloaded TensorRT 11.1.0.106: the same passed on GPU 1. Three A6000 devices
  were individually enumerated.
- Real SD1.5 FP32 VAE, 128-by-128 output, GPU 2: engine built, three fixed-seed numeric
  checks passed (max error 0.0027563; mean error 0.0000742). Kernel benchmark was
  PyTorch 49.81 ms versus TensorRT 12.55 ms. These are component timings, not total
  render speedup.
- Cache reuse and deliberate child termination passed a live test. PyTorch fallback
  decoded the identical latent with exactly equal reference output. The deliberately
  failed validation engine was quarantined.
- Local evidence: backend `data/runtime-validation/` and
  `data/runtime-validation-sdk11/`; WinUI log `%TEMP%/tensorrt-winui-build.log`.

Automatic approval review rejected the attempted WinUI launch as "blocked by policy".
A responsive updated native window has not been verified.

## Remaining qualification

Full Internal Renderer image/video output and end-to-end timing; final UI build and
interactive controls; FP16 and production-size profiles; TensorRT 11 real component;
frozen packaging; broader resume/cancel regression matrix; engine disk management
under contention; and additional video components/models. Do not describe this
checkpoint as completion of the blueprint's production-readiness criteria.


## Validation schema 2

The SD1.5 VAE component engine identity now uses adapter version 2. This forces a
new content-addressed engine key after the validation-policy change; failed or ready
version-1 engines are not deleted and cannot be mistaken for version-2 validation.

FP32 validation no longer rejects an engine solely because one decoded value crosses
the previous 0.005 maximum-absolute-error boundary. Version 2 evaluates max and mean
absolute error, RMSE, P99 absolute error, PSNR and a dependency-free global SSIM
statistic across the fixed validation seeds. Maximum relative error is recorded for
diagnostics but is not a hard gate because reference values near zero make it
unstable as a VAE acceptance criterion.

The default FP32 maximum-absolute threshold is 0.0075, while mean error, RMSE, P99,
PSNR and SSIM independently constrain broad output drift. Strict execution and
no-fallback behavior remain unchanged.

The existing `services/tensorrt_standalone.py` implementation remains the verified
SD1.5 UNet TensorRT route. It is reported separately as `tensorrt_standalone`
rather than claiming that the normal Diffusers component runtime can replace its
UNet.
