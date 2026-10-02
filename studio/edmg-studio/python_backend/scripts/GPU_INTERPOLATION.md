# GPU interpolation on this workstation

Configured 2026-10-02. Native Render > Advanced > Interpolation submits
`auto`, `rife`, or `fruc`. Machine-local `launcher_env.json` sets `EDMG_RIFE_CMD` to
`run_rife_interpolation.py`, using `data/tools/rife-env/Scripts/python.exe`.
New backend processes load the configuration; an already running interpolation
process cannot change engines in place.

## Installed path

- Practical-RIFE commit `bbfd2ea90910789a860ea3e2b32a240cd577b75e`.
- Author-provided 4.25-lite weights SHA-256:
  `81CDBA223FE72A120130CC8552E5D2ECAC824259D406F0C15323B3DECF96B8B1`.
- Dedicated Python 3.12 environment: torch 2.11.0+cu130, torchvision 0.26.0+cu130,
  numpy 1.26.4, scipy 1.15.3, opencv-python-headless 4.11.0.86,
  sk-video 1.1.10, tqdm 4.67.1.
- GPU selection: `EDMG_INTERPOLATION_CUDA_DEVICE=2` (local CUDA/NVENC ordinal).
- FP16 CUDA RIFE followed by H.264 NVENC p5/hq, CQ 18, yuv420p.
- Audio remains the responsibility of Studio's existing subsequent mux stage.
- `.rife.json` beside the output records the actual wrapper result.

The adapter requires constant-rate input and an integer FPS multiplier. For
example, 3 to 60 fps works. It preserves duration, extending the last source
frame's display interval after the last interpolated pair. Publication requires
the expected frame count and duration. Unsupported ratios fail the explicit RIFE
route; existing Studio Auto policy may fall back to CPU interpolation.

`--probe` checks basic runtime layout and CUDA visibility, not a full inference
or NVENC qualification. Use a real video smoke test for those gates.

## NVIDIA components

OFA is hardware already present on RTX A6000. The installed Optical Flow SDK
5.0.7 at `C:\Optical_Flow_SDK_5.0.7\Optical_Flow_SDK_5.0.7` includes the built
`NvOFFRUC\NvOFFRUCSample\bin\win64\NvOFFRUCSample.exe` and its runtime DLLs.
`EDMG_FRUC_EXE` selects that executable; `EDMG_FRUC_CMD` invokes
`run_fruc_interpolation.py` with `{in}`, `{out}`, and `{fps}` placeholders.
The adapter uses CUDA allocation on the selected GPU, repeated OFA/FRUC 2x
passes, then target-rate sampling and NVENC. This is a raw-video SDK sample
adapter, not an in-process or zero-copy integration. Long/high-resolution clips
need substantial temporary disk space; the adapter checks capacity before work.
It supports even-sized constant-rate inputs and up to 64x expansion.
`.fruc.json` records the provider, GPU ordinal, pass logs and verified output.
Auto tries configured RIFE, then FRUC, then the existing CPU fallback. Explicit
RIFE and FRUC fail on missing configuration/runtime errors instead of silently
running CPU interpolation. Select NVIDIA OFA / FRUC explicitly to force OFA.
Restart Studio/backend after changing local launcher configuration; an existing
job cannot change engines in place. These SDK files are not bundled for distribution.

Public Maxine source was downloaded under `data/tools/Maxine-VFX-SDK-source`.
This is not an installed effects runtime. Current VFX Core and effect packages
require NGC access. Supported Ampere effects need their own model/runtime
qualification and Studio integration:
https://docs.nvidia.com/maxine/vfx/latest/WindowsVFXSDK/InstalltheVFXSDK.html

Maxine Video Frame Generation requires Ada/Blackwell on Windows, excluding the
Ampere RTX A6000:
https://docs.nvidia.com/maxine/vfx/latest/Filters/VideoFrameGeneration.html

DLSS Frame Generation is also unsupported on this Ampere hardware and is not
configured. No TensorRT RIFE engine was built; this installation uses CUDA Torch.

## Validation and limitations

Initial direct smoke: 320x180, 6 source frames at 3 fps, two seconds -> 120 frames
at 60 fps, two seconds, H.264 through NVENC. Full project, visual quality, packaged
distribution, multi-GPU segmentation and production throughput remain unqualified.
The active CPU render was not canceled or migrated.
