"""Dependency-free Linux launcher checks; stdout contains only the profile."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import runpy
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="auto")
    parser.add_argument("--env-mode", choices=("auto", "active"), default="auto")
    args = parser.parse_args()
    if platform.system() != "Linux":
        parser.exit(1, "Run the backend launcher on Linux.\n")
    if sys.version_info[:2] != (3, 12):
        parser.exit(1, "EDMG Studio requires Python 3.12.\n")
    if args.env_mode == "active":
        environment = os.getenv("VIRTUAL_ENV") or os.getenv("CONDA_PREFIX")
        if not environment:
            parser.exit(1, "Active mode requires a virtualenv or conda environment.\n")
        os.environ["UV_PROJECT_ENVIRONMENT"] = environment
    backend = Path(__file__).resolve().parents[1] / "python_backend"
    policy = runpy.run_path(str(backend / "edmg_studio_backend" / "uv_toolchain.py"))
    try:
        profile = policy["resolve_accelerator_profile"](args.profile)
        if profile not in {"cpu", "cuda"}:
            raise RuntimeError("Linux requires the cpu or cuda profile.")
        for variable, default in (("EDMG_FFMPEG_PATH", "ffmpeg"), ("EDMG_FFPROBE_PATH", "ffprobe")):
            executable = os.getenv(variable) or default
            result = subprocess.run([executable, "-version"], capture_output=True, timeout=15, check=False)
            if result.returncode != 0:
                raise RuntimeError(f"{variable} executable did not pass its version check.")
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Linux backend preflight failed: {exc}", file=sys.stderr)
        return 1
    print(profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
