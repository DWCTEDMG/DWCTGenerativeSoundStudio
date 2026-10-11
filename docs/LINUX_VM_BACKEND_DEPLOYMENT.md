# Linux VM backend deployment

Use a native Linux checkout of the same source revision as the Windows WinUI
client. A headless VM runs the shared Python backend; WinUI and Windows audio
playback stay on the client. This document is a deployment procedure, not a
claim that a specific VM or every model has passed qualification.

## Prepare the VM

For the CUDA lane, use an x86-64 Linux VM exposing an NVIDIA GPU. Verify
`nvidia-smi -L` on the VM before proceeding. Install the driver through the VM
provider's supported procedure. Keep model-specific environments separate.

Install Git, curl, tar, a SHA-256 utility, FFmpeg, ffprobe, and the distribution's
audio runtime libraries (including libsndfile). Clone into a native Linux
filesystem. The launcher uses checksum-pinned uv 0.11.28 and Python 3.12.
An incompatible uv on PATH is rejected; select the pinned executable with
`EDMG_UV_BIN` if necessary.

From the repository root:

```bash
export EDMG_STUDIO_HOME="$HOME/edmg-studio-home"
export EDMG_STUDIO_BACKEND_HOST=127.0.0.1
export EDMG_BACKEND_ACCELERATOR_PROFILE=auto
bash studio/edmg-studio/scripts/start_lightning_backend.sh
```

Automatic selection preserves an installed CUDA profile or selects CUDA when
an NVIDIA GPU is visible. It fails when no supported GPU profile is found;
CPU requires the explicit value `cpu`. The preflight checks FFmpeg and ffprobe
before dependency synchronization. CUDA selection is not proof of usable GPU
compute: a preserved CUDA environment can still have a missing device/driver.

The standard frozen runtime extras are `core`, `audio`, `asr`, `internal-video`,
and `aws`, plus the accelerator profile. Specialized optional extras such as
Parakeet, source separation, CLAP, Gradio, background removal, and Azure SDKs
are separate installations and qualifications. Do not use `--all-extras`:
CPU, DirectML, and CUDA profiles conflict. A standard launch synchronizes to
the standard runtime set; custom capability environments need their own
consistent launch and sync configuration.

Use `EDMG_BACKEND_ENV_MODE=active` only for an intentionally selected Python
3.12 virtualenv or conda environment. It explicitly allows synchronization of
that environment. `EDMG_SKIP_BOOTSTRAP=1` checks the frozen environment instead
of synchronizing it. The TensorRT internal pip installer is disabled by the
launcher; dependencies come from the locked uv installation.

## Connect the Windows client

Use a private network or an authenticated HTTPS reverse proxy to the localhost
listener. If the VM listener must bind to a network interface, set
`EDMG_STUDIO_BACKEND_HOST` to the intended interface address. The launcher
enables required authentication for non-loopback binding and creates a token
under `$EDMG_STUDIO_HOME/config/backend-auth-token` when no token is supplied.
Do not override authentication to disabled for a remote listener. Protect the
token; do not paste it into logs or reports. Configure the native Studio's
external backend URL and matching authentication.

Configure provider credentials on Linux again; Windows keyring credentials
are not portable. Headless keyring availability needs checking. Keep NVIDIA /
Nemotron as the automatic Director choice. Hosted providers require their
own endpoints, credentials, and successful inference checks.

## Qualification on the actual VM

1. Record `git rev-parse HEAD`, dirty state, distribution, Python/uv versions,
   GPU inventory, and exact launch configuration without secrets.
2. Run the backend tests in the frozen deployed environment. Include both
   backend and repository scopes using `scripts/run_pytest_scopes.py` without
   `--sync` after the launcher has installed the selected runtime.
3. Check authenticated `/v1/system/readiness`, including `checks.runtime`
   with `lock_check` and `sync_health`, GPU, writable paths, disk, and media tools.
   `/health` alone only establishes reachability. A nonempty models directory
   does not establish model inference readiness.
4. Connect WinUI, then create/upload/analyze a disposable project, obtain and
   review a Director plan, and verify the render handoff.
5. Obtain an actual output receipt for each intended model. Verify media with
   ffprobe and a full FFmpeg decode. Qualify GPU interpolation and NVENC
   separately when those features are required.

HunyuanVideo 1.5 uses the Linux isolated worker with
`EDMG_HUNYUAN15_RUNNER=external`, Linux Python/repository/model paths, and all
required companion assets. Do not copy Windows `wsl` configuration or Windows
executable paths. LTX and other isolated model runtimes also need Linux paths
and compatible environments. Install weights and model-specific assets through
the corresponding supported workflow before claiming rendering readiness.

Full readiness remains pending until these checks pass on the target VM.
