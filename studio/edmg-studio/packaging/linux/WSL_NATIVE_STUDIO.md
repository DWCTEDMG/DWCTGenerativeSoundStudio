# Native Windows Studio with a WSL Hunyuan worker

The native WinUI Studio and its control-plane backend run on Windows. The
HunyuanVideo-1.5 worker runs in a configured WSL2 distribution, using Linux model
paths and the Windows NVIDIA driver bridge. Windows and WSL observations of the
same GPU share its UUID and must share the scheduler's physical device lease.

## Configure from native Studio

1. In Models, open the Hunyuan runtime configuration. Select WSL mode and enter
   the distribution name, Linux Python launcher, official Hunyuan checkout,
   model directory, and the four companion directories. Save and probe.
2. In Settings, select the hybrid GPU execution profile. Its automatic policy
   prefers WSL for HunyuanVideo-1.5 when that worker is available.
3. In Render, select HunyuanVideo-1.5 and a mapped GPU. An explicit WSL request
   with environment fallback disabled fails if the worker is unavailable.
4. Run the model runtime smoke test, then render a project. A probe verifies
   prerequisites; a fresh successful motion-validation receipt qualifies the
   runtime. A completed project job separately verifies artifact publication.

The configured launcher environment persists distribution and runtime paths.
Paths under `/home/...` refer to the WSL filesystem, not the Windows checkout.
Keep models and the Python environment on Linux storage. Install `ffmpeg` and
`ffprobe` inside the distribution for worker media handling. Do not install a
Linux NVIDIA display driver in WSL; use its Windows driver bridge.

## Noninteractive GPU discovery

Studio invokes `/usr/lib/wsl/lib/nvidia-smi` explicitly. A successful login-shell
`nvidia-smi` command is insufficient when that directory is absent from the
noninteractive PATH. Ordinary inventory refreshes include the configured WSL
distribution's GPU mapping without loading the model.

## Workstation-specific runtime bootstrap

On the QEMU workstation used for qualification, PyTorch 2.6.0 initialization
encountered non-monotonic virtual CPU timestamps. The dedicated Hunyuan launcher
adds a private `sitecustomize.py` that imports PyTorch with one CPU in its
affinity mask, then restores the original mask in `finally`. This workaround is
scoped to that launcher; it is not a general requirement for WSL.

That worker also uses a private SafeTensors 0.7.0 overlay because the installed
0.8.0 path with its existing PyTorch environment performed checkpoint loading
through scalar storage access. The base virtual environment is preserved.
The launcher exports `OMP_NUM_THREADS=8` and `MKL_NUM_THREADS=8` for CPU weight
conversion and offloading. These settings do not alter Windows CUDA packages.

The current machine paths are:

```text
Distribution: Ubuntu
Launcher: /home/gulleman/edmg/bin/hunyuan-python
Checkout: /home/gulleman/edmg/HunyuanVideo-1.5
Bootstrap: /home/gulleman/edmg/runtime-bootstrap/sitecustomize.py
Compatibility overlay: /home/gulleman/edmg/runtime-compat
Models: /home/gulleman/edmg/models/internal/video/hf_hunyuan_video15_internal
Companions: /home/gulleman/edmg/models/internal/hunyuan-support
```

The absolute machine paths belong in local launcher configuration, not shared
defaults. Preserve other runtime and storage settings when updating that file.
