from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "studio" / "edmg-studio" / "python_backend"
DEFAULT_TEMP_ROOT = REPO_ROOT / ".pytest-runtime"


def run_step(label: str, cwd: Path, args: list[str], *, env: dict[str, str]) -> int:
    print(f"[pytest-scopes] {label}")
    print(f"[pytest-scopes] cwd={cwd}")
    print(f"[pytest-scopes] cmd={' '.join(args)}")
    completed = subprocess.run(args, cwd=cwd, env=env)
    return int(completed.returncode)


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


def main() -> int:
    configured_root = Path(os.getenv("EDMG_PYTEST_TEMP_ROOT", str(DEFAULT_TEMP_ROOT))).expanduser().resolve()
    configured_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="run-",
        dir=configured_root,
        ignore_cleanup_errors=True,
    ) as raw_root:
        isolated_root = Path(raw_root)
        env = _isolated_environment(isolated_root)
        steps = [
            (
                "repo-level tests",
                REPO_ROOT,
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-c",
                    str(REPO_ROOT / "pytest.ini"),
                    "tests",
                    "--basetemp",
                    str(isolated_root / "pytest-repo"),
                    "-p",
                    "no:cacheprovider",
                ],
            ),
            (
                "backend package tests",
                BACKEND_ROOT,
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-c",
                    str(BACKEND_ROOT / "pyproject.toml"),
                    "--basetemp",
                    str(isolated_root / "pytest-backend"),
                    "-p",
                    "no:cacheprovider",
                ],
            ),
        ]
        for label, cwd, args in steps:
            rc = run_step(label, cwd, args, env=env)
            if rc != 0:
                return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
