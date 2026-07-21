# uv migration inventory

This inventory records the supported Python environment, installation, test,
and release paths inspected before the uv migration. The baseline was the
branch tip immediately before UV-01. Historical design documents and external
repositories cloned by sidecar setup are not supported backend execution paths.

## First-party consumers

| Baseline consumer | Previous behavior | Locked replacement |
| --- | --- | --- |
| `.github/workflows/studio.yml` | `python -m pip install -e ...` and ambient Python | Pinned `astral-sh/setup-uv`, Python 3.12, lock check, frozen CPU sync, plus DirectML/CUDA frozen dry-runs |
| `scripts/run_pytest_scopes.py` | Reused the invoking interpreter/environment | Verifies uv 0.11.28, checks the lock, synchronizes the frozen CPU test profile, then runs both scopes with `uv run --no-sync` |
| `RUN_ME` / Studio launchers and `tools/launcher_gui.py` | Created `venv`, upgraded pip, chose a dynamic CUDA wheel tag/index, and installed editable extras | Checksum-pinned uv bootstrap, Python 3.12 acquisition, one locked accelerator profile, frozen capability sync, and frozen backend execution |
| Setup Wizard and backend repair | Installed editable bundle extras and dynamically refreshed Torch/TensorRT | Shared uv toolchain service, explicit profile selection, lock/sync health and provenance in the UI |
| `scripts/edmg_core_installer.py` | Created a venv, upgraded packaging tools, dynamically installed Torch/Whisper, and installed editable bundles | Frozen profile/capability sync; the legacy `--venv` path is an explicit uv project environment only |
| `scripts/prepare-release-bundle.mjs` | Created a release venv; upgraded pip/wheel/setuptools; optionally injected a Torch index; installed PyInstaller dynamically | Rejects dependency/index overrides and dirty/untracked inputs; lock check, frozen profile/build sync, frozen PyInstaller run, and a provenance manifest |
| `packaging/windows/build_all.ps1` | Managed its own Python range, venv, pip installs, and PyInstaller invocation | Requires uv 0.11.28 and delegates the locked DirectML release build to the canonical pnpm script |
| Backend, AWS Batch, and Hyperlift Dockerfiles | Upgraded pip and installed editable/dynamic requirements | Python 3.12 images copy uv 0.11.28 and perform a frozen CPU/capability sync before `uv run --no-sync` |
| GCP and Vast bootstraps | Created venvs and selected arbitrary CUDA indexes | Checksum-verified uv archive, Python 3.12, fixed CPU/CUDA profile, lock check, frozen sync, and hardware validation |
| Lightning launcher and generated bundle | Installed into an ambient environment and generated an unpinned `requirements.txt` | Frozen CPU/CUDA sync (or active-environment check), copied project metadata/lock, and lock-derived bundle manifest |
| Backend capability error messages and Studio Cloud/Settings UI | Advertised one-off pip commands | Advertise frozen uv capability syncs using the selected profile |
| Developer/operator documentation | Advertised ambient `python`, venv, and pip workflows | Documents Python 3.12, uv 0.11.28, mutually exclusive profiles, capabilities, lock policy, and frozen commands |

`requirements-internal.txt` and `requirements-directml.txt` had no tracked
consumer at the baseline. After every supported path moved to `pyproject.toml`
and `uv.lock`, both files were removed rather than retained as independent
dependency sources.

## Explicit external-environment exception

The Linux ComfyUI, Hugging Face bucket, and S3 helpers install into independent
sidecar/system interpreters. They use the pinned uv executable and explicit
`uv pip install --python ...` commands. ComfyUI's cloned upstream
`requirements.txt` is allowed only in that external ComfyUI environment; it is
never copied into, synchronized with, or used to build the EDMG backend or a
release artifact.

## Guardrails and parity evidence

`tests/test_uv_migration_static.py` fails when a supported first-party path:

- invokes pip directly or creates a venv;
- consumes either retired requirements file;
- consumes a dynamic Torch/index override rather than rejecting it;
- drops lock checks or frozen CI/release commands;
- reintroduces an unpinned Lightning requirements bundle; or
- weakens the checksum-pinned shell uv bootstrap.

The same test generates a Lightning bundle and verifies its lock hash and
startup commands. Launcher, Setup, release-toolchain, PyInstaller, and packaged
runtime compatibility tests cover their respective execution boundaries.
