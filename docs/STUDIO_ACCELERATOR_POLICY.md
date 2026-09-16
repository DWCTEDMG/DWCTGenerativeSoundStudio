# Studio accelerator selection

Studio setup defaults to **Automatic — prefer GPU**. An explicit CPU selection is supported, but automatic selection must not silently choose CPU or replace a CUDA installation with CPU wheels.

## Dependency profiles and runtime devices

- Automatic Python setup preserves a CUDA-enabled target environment, including when the NVIDIA driver is temporarily unavailable. Otherwise a successful NVIDIA device probe selects CUDA.
- Windows without CUDA selects the DirectML dependency profile for supported AMD/Intel/other Windows GPU workloads. This selects packages; it does not certify that a GPU or a particular model is ready.
- Other platforms without a supported GPU dependency profile report a setup error. ROCm and Apple MPS dependency profiles are not currently defined in the frozen project; this change does not claim new platform support.
- Internal rendering selects available CUDA, MPS, then DirectML backends. An explicitly requested GPU backend must be available. Automatic rendering with no supported GPU fails with a diagnostic instead of running on CPU.
- CPU remains available through an explicit UI choice, `--accelerator-profile cpu`, or `EDMG_BACKEND_ACCELERATOR_PROFILE=cpu`. Existing explicit choices remain authoritative.
- Automatic portable ComfyUI setup currently supports the NVIDIA lane. It reports a blocker on other GPU lanes rather than guessing a portable archive or choosing CPU. External ComfyUI runtimes remain available.
- This policy governs accelerator selection. CPU-based UI, media I/O, DSP, and deliberate model CPU offload still operate normally. It does not benchmark or distribute work across all GPUs.

## Safe testing and source startup

Run from the repository root with the already prepared backend environment:

```powershell
uv run --project studio/edmg-studio/python_backend --frozen --no-sync python scripts/run_pytest_scopes.py
```

The runner prints the resolved profile and runs both test scopes with `--no-sync`. It checks the lockfile but does not install, remove, or replace dependencies by default. Missing test dependencies fail visibly.

Dependency synchronization is deliberate:

```powershell
uv run --project studio/edmg-studio/python_backend --frozen --no-sync python scripts/run_pytest_scopes.py --sync
```

Use `UV_PROJECT_ENVIRONMENT` to target an isolated environment. CPU-only CI explicitly requests its CPU profile; this is not a product default. Native and compatibility desktop source launches also use `uv run --no-sync`; prepare the environment with the source setup launcher before first launch. Packaged dependencies remain immutable.
