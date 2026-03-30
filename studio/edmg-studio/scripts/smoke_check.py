from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> int:
    print("> " + " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(cwd), env=env)
    return int(p.returncode)


def main() -> int:
    studio_root = Path(__file__).resolve().parents[1]
    repo_root = studio_root.parents[1]

    rc = 0
    python_targets = [
        "python_backend/enhanced_deforum_music_generator",
        "python_backend/deforum_music",
        "scripts",
        str(repo_root / "tests"),
    ]
    rc |= run([sys.executable, "-m", "compileall", "-q", *python_targets], studio_root)
    stable_pytests = [
        str(repo_root / "tests" / "test_studio_proxy_fallback.py"),
        str(repo_root / "tests" / "test_studio_workflow_smoke.py"),
        str(repo_root / "tests" / "test_studio_render_tiers.py"),
        str(repo_root / "tests" / "test_api.py"),
        str(repo_root / "tests" / "test_preview_generator.py"),
        str(repo_root / "tests" / "test_style_transfer.py"),
        str(repo_root / "tests" / "test_selfcheck_script.py"),
    ]
    rc |= run([sys.executable, "-m", "pytest", "-q", *stable_pytests], studio_root)

    print("smoke_check rc:", rc)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
