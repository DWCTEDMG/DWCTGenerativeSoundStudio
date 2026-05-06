from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "studio" / "edmg-studio" / "python_backend"


def run_step(label: str, cwd: Path, args: list[str]) -> int:
    print(f"[pytest-scopes] {label}")
    print(f"[pytest-scopes] cwd={cwd}")
    print(f"[pytest-scopes] cmd={' '.join(args)}")
    completed = subprocess.run(args, cwd=cwd)
    return int(completed.returncode)


def main() -> int:
    steps = [
        (
            "repo-level tests",
            REPO_ROOT,
            [sys.executable, "-m", "pytest", "-c", str(REPO_ROOT / "pytest.ini"), "tests"],
        ),
        (
            "backend package tests",
            BACKEND_ROOT,
            [sys.executable, "-m", "pytest", "-c", str(BACKEND_ROOT / "pyproject.toml")],
        ),
    ]
    for label, cwd, args in steps:
        rc = run_step(label, cwd, args)
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
