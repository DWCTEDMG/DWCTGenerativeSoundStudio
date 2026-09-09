from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "studio" / "edmg-studio" / "python_backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from edmg_studio_backend.uv_toolchain import normalize_accelerator_profile  # noqa: E402


DEFAULT_TEMP_ROOT = REPO_ROOT / ".pytest-runtime"
UV_VERSION = "0.11.28"
UV_PROJECT_FLAGS = [
    "--project",
    str(BACKEND_ROOT),
    "--frozen",
    "--no-sync",
]


def run_step(label: str, cwd: Path, args: list[str], *, env: dict[str, str]) -> int:
    print(f"[pytest-scopes] {label}")
    print(f"[pytest-scopes] cwd={cwd}")
    print(f"[pytest-scopes] cmd={' '.join(args)}")
    completed = subprocess.run(args, cwd=cwd, env=env)
    return int(completed.returncode)


def _resolve_uv() -> str:
    uv = (
        os.getenv("EDMG_UV_BIN", "").strip()
        or os.getenv("UV", "").strip()
        or shutil.which("uv")
    )
    if not uv:
        raise RuntimeError(
            f"uv {UV_VERSION} is required. Install the pinned toolchain before running pytest scopes."
        )
    completed = subprocess.run(
        [uv, "--version"], capture_output=True, text=True, check=False
    )
    actual = completed.stdout.strip()
    actual_parts = actual.split()
    if completed.returncode != 0 or actual_parts[:2] != ["uv", UV_VERSION]:
        raise RuntimeError(f"Expected uv {UV_VERSION}; found {actual or uv!r}.")
    return uv


def _test_dependency_flags(profile: str) -> list[str]:
    return [
        "--extra",
        profile,
        "--extra",
        "core",
        "--extra",
        "audio",
        "--group",
        "test",
    ]


def _uv_pytest_command(uv: str, *pytest_args: str, profile: str) -> list[str]:
    args = [uv, "run", *UV_PROJECT_FLAGS, *_test_dependency_flags(profile)]
    return [*args, "python", "-m", "pytest", *pytest_args]


def _isolated_environment(root: Path, base: dict[str, str]) -> dict[str, str]:
    env = dict(base)
    paths = {
        "EDMG_STUDIO_HOME": root / "studio-home",
        "EDMG_STUDIO_DATA_DIR": root / "studio-home" / "data",
        "EDMG_STUDIO_MODELS_DIR": root / "studio-home" / "models",
        "EDMG_STUDIO_CACHE_DIR": root / "studio-home" / "cache",
        "EDMG_STUDIO_LOGS_DIR": root / "studio-home" / "logs",
        "EDMG_STUDIO_EXTERNAL_DIR": root / "studio-home" / "external",
        "OLLAMA_MODELS": root / "studio-home" / "models" / "ollama",
    }
    for key, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env.update(
        {
            "EDMG_BACKEND_AUTH_MODE": "disabled",
            "EDMG_STUDIO_BACKEND_HOST": "127.0.0.1",
            "EDMG_WORKER_AUTOSTART": "0",
        }
    )
    return env


def main() -> int:
    toolchain_env = dict(os.environ)
    # Reject invalid selections before running uv or creating test directories.
    # CUDA includes the pinned TensorRT dependencies in the shared project lock.
    profile = normalize_accelerator_profile(
        toolchain_env.get("EDMG_BACKEND_ACCELERATOR_PROFILE", "cpu")
    )
    toolchain_env["EDMG_BACKEND_ACCELERATOR_PROFILE"] = profile
    uv = _resolve_uv()
    lock_rc = run_step(
        "validate uv lock", BACKEND_ROOT, [uv, "lock", "--check"], env=toolchain_env
    )
    if lock_rc != 0:
        return lock_rc
    sync_rc = run_step(
        "sync frozen test environment",
        BACKEND_ROOT,
        [
            uv,
            "sync",
            "--frozen",
            # Keep installed ASR, renderer and other optional capabilities.
            # Test preparation must not prune the desktop runtime environment.
            "--inexact",
            *_test_dependency_flags(profile),
        ],
        env=toolchain_env,
    )
    if sync_rc != 0:
        return sync_rc

    configured_root = (
        Path(os.getenv("EDMG_PYTEST_TEMP_ROOT", str(DEFAULT_TEMP_ROOT)))
        .expanduser()
        .resolve()
    )
    configured_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="run-",
        dir=configured_root,
        ignore_cleanup_errors=True,
    ) as raw_root:
        isolated_root = Path(raw_root)
        env = _isolated_environment(isolated_root, toolchain_env)
        steps = [
            (
                "repo-level tests",
                REPO_ROOT,
                _uv_pytest_command(
                    uv,
                    "-c",
                    str(REPO_ROOT / "pytest.ini"),
                    "tests",
                    "--basetemp",
                    str(isolated_root / "pytest-repo"),
                    "-p",
                    "no:cacheprovider",
                    profile=profile,
                ),
            ),
            (
                "backend package tests",
                BACKEND_ROOT,
                _uv_pytest_command(
                    uv,
                    "-c",
                    str(BACKEND_ROOT / "pyproject.toml"),
                    "--basetemp",
                    str(isolated_root / "pytest-backend"),
                    "-p",
                    "no:cacheprovider",
                    profile=profile,
                ),
            ),
        ]
        for label, cwd, args in steps:
            rc = run_step(label, cwd, args, env=env)
            if rc != 0:
                return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
