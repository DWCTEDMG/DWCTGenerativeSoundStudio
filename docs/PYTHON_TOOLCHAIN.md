# Python toolchain

EDMG Studio uses Python 3.12 and `uv` 0.11.28 for every supported source,
test, CI, cloud-bootstrap, and release-build path. JavaScript and Electron stay
on `pnpm@10.33.0`; the Python migration does not change the Node toolchain.

The repository `.python-version`, backend `pyproject.toml`, and committed
`studio/edmg-studio/python_backend/uv.lock` are one reviewed release input.
Never hand-edit `uv.lock`, substitute an arbitrary PyTorch index, or install an
untracked package into an environment used for a release.

## Profiles and capabilities

Every project environment must select exactly one accelerator profile:

- `cpu`: CPU PyTorch wheels from the explicit CPU index.
- `directml`: CPU PyTorch wheels plus the Windows DirectML/ONNX stack.
- `cuda`: CUDA 13.0 PyTorch wheels and the locked TensorRT stack.

The profiles are mutually exclusive in `[tool.uv].conflicts`. Accelerator
choice is independent from product capability extras such as `core`, `audio`,
`clap`, `asr`, `source-separation`, `parakeet`, `aws`, `azure`, `codex`, and
`internal-video`.

The baseline developer workflow preserves the selected accelerator environment:

```shell
uv lock --project studio/edmg-studio/python_backend --check
uv run --project studio/edmg-studio/python_backend --frozen --no-sync \
  --group test python scripts/run_pytest_scopes.py
```

Use `python scripts/run_pytest_scopes.py --sync` only when provisioning is required.
Automatic selection preserves CUDA and otherwise selects the supported Windows
DirectML lane. CPU is an explicit CI or troubleshooting choice via
`--accelerator-profile cpu`; never use it to replace an active GPU environment.

Optional CLAP analysis composes with, but does not replace, the accelerator and
audio selections. After the selected environment and model assets are cached,
run its parity probe without synchronization:

```shell
uv run --project studio/edmg-studio/python_backend --frozen --no-sync --offline \
  python scripts/check_clap_capability.py
```

The parity probe performs imports and version checks only; it does
not download a model. Runtime adapters must load an explicitly configured local
CLAP model/cache and degrade cleanly when it is absent.

The capability uses Transformers' native `ClapModel`/`ClapProcessor` API. Do
not add `laion-clap`: importing that package resolves a tokenizer model at
module import time and breaks the offline contract.

On PowerShell, put multiline `uv` commands on one line or use PowerShell
backticks instead of shell backslashes.

Run tools through the same frozen environment without synchronization:

```shell
uv run --project studio/edmg-studio/python_backend --frozen --no-sync \
  --group test python -m pytest
uv run --project studio/edmg-studio/python_backend --frozen --no-sync \
  --group lint ruff check .
```

`scripts/run_pytest_scopes.py` checks the lock and runs both Python test scopes.
From the repository root, it preserves installed dependencies unless `--sync`
is explicitly supplied:

```shell
uv run --project studio/edmg-studio/python_backend --frozen --no-sync \
  --group test python scripts/run_pytest_scopes.py
```

## Release environments

A release build chooses one of `cpu`, `directml`, or `cuda` through
`EDMG_BACKEND_ACCELERATOR_PROFILE`. The build must run `uv lock --check` and
`uv sync --frozen --extra <profile> --group build` before invoking PyInstaller
through `uv run --frozen`. Arbitrary Torch-index environment overrides are
rejected.

The backend bundle manifest records the Python and uv versions, lock SHA-256,
accelerator profile, resolved Torch packages and index, and PyInstaller
version. The lockfile and manifest are artifact provenance, not advisory
metadata.

The installed Electron application contains the PyInstaller backend executable.
End users do not need Python or uv to launch a packaged application. Source
launchers may bootstrap the pinned uv binary; the packaged-binary fast path must
remain independent of both tools.

## Lock maintenance

- Change `pyproject.toml` and `uv.lock` in the same reviewed change.
- Confirm normal changes with `uv lock --check`; CI and release builds never
  rewrite the lock.
- Use `uv lock --upgrade` for a scheduled full update or
  `uv lock --upgrade-package <name>` for a targeted update, then rerun the CPU,
  DirectML, CUDA, model, and packaging evidence appropriate to that package.
- Treat Torch, Diffusers, Transformers, Accelerate, ONNX Runtime, PyInstaller,
  CUDA, and TensorRT changes as compatibility-matrix changes.

The Linux ComfyUI, Hugging Face CLI, and S3 helper scripts provision external
sidecars rather than the backend project. They may use pinned `uv pip --python`
commands because their upstream environments are not represented by the backend
lock. They must never modify a release-build environment.

The inspected baseline consumers and their migrated replacements are recorded
in [`UV_MIGRATION_INVENTORY.md`](UV_MIGRATION_INVENTORY.md).
