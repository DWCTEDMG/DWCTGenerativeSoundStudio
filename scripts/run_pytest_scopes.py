from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "studio" / "edmg-studio" / "python_backend"
DEFAULT_TEMP_ROOT = REPO_ROOT / ".pytest-runtime"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from edmg_studio_backend.uv_toolchain import ToolchainError, resolve_accelerator_profile  # noqa: E402
UV_VERSION = "0.11.28"
UV_PROJECT_FLAGS = [
    "--project",
    str(BACKEND_ROOT),
    "--frozen",
    "--no-sync",
    "--extra",
    "core",
    "--extra",
    "audio",
    "--group",
    "test",
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


def _uv_pytest_command(uv: str, *pytest_args: str, profile: str) -> list[str]:
    return [uv, "run", *UV_PROJECT_FLAGS, "--extra", profile, "python", "-m", "pytest", *pytest_args]


def _isolated_environment(root: Path) -> dict[str, str]:
    env = dict(os.environ)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run isolated repository and backend tests.")
    parser.add_argument(
        "--accelerator-profile",
        choices=("auto", "cpu", "cuda", "directml"),
        default=os.getenv("EDMG_BACKEND_ACCELERATOR_PROFILE", "auto").strip().lower() or "auto",
        help="GPU-first auto selection; CPU requires an explicit choice.",
    )
    parser.add_argument("--sync", action="store_true", help="Explicitly synchronize dependencies before testing. Default: preserve the environment.")
    args = parser.parse_args(argv)
    profile = args.accelerator_profile
    # argparse does not validate a string default against choices.
    if profile not in {"auto", "cpu", "cuda", "directml"}:
        parser.error(f"Unsupported accelerator profile: {profile!r}")
    try:
        profile = resolve_accelerator_profile(profile)
    except ToolchainError as exc:
        parser.error(str(exc))
    print(f"[pytest-scopes] accelerator={profile}; dependency sync={'requested' if args.sync else 'disabled'}", flush=True)
    uv = _resolve_uv()
    toolchain_env = dict(os.environ)
    toolchain_env["EDMG_BACKEND_ACCELERATOR_PROFILE"] = profile
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
            "--inexact",
            "--extra",
            profile,
            "--extra",
            "core",
            "--extra",
            "audio",
            "--group",
            "test",
        ],
        env=toolchain_env,
    ) if args.sync else 0
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
        env = _isolated_environment(isolated_root)
        env["EDMG_BACKEND_ACCELERATOR_PROFILE"] = profile
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
