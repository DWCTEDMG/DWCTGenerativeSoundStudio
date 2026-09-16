from __future__ import annotations

import subprocess
import sys
from pathlib import Path


STUDIO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = STUDIO_ROOT / "python_backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from edmg_studio_backend.uv_toolchain import (  # noqa: E402
    ToolchainError,
    frozen_run_command,
    active_accelerator_profile,
    sync_frozen_project,
)


def select_profile() -> str:
    return active_accelerator_profile()


def main() -> int:
    try:
        profile = select_profile()
        uv = sync_frozen_project(profile, install_uv=True)
        command, env = frozen_run_command(
            profile,
            ["python", str(STUDIO_ROOT / "tools" / "launcher_gui.py")],
            install_uv=False,
        )
        env["EDMG_UV_BIN"] = str(uv)
        print(f"[launcher] frozen uv profile: {profile}")
        return int(
            subprocess.run(command, cwd=BACKEND_ROOT, env=env, check=False).returncode
        )
    except ToolchainError as exc:
        print(f"EDMG Studio toolchain setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
