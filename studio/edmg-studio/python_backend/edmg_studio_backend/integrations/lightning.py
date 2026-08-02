from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

UV_VERSION = "0.11.28"
BACKEND_SOURCE_DIRS = (
    "edmg_studio_backend",
    "enhanced_deforum_music_generator",
    "deforum_music",
    "edmg_ai_service",
    "edmg",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate_lightning_bundle(
    output_dir: str, host: str = "0.0.0.0", port: int = 7863
) -> dict[str, Any]:
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    backend_root = Path(__file__).resolve().parents[2]
    repo_root = backend_root.parents[2]
    profile = os.getenv("EDMG_BACKEND_ACCELERATOR_PROFILE", "cpu").strip().lower() or "cpu"
    if profile not in {"cpu", "cuda"}:
        raise ValueError(f"Lightning bundles support cpu or cuda, got {profile!r}.")

    required_files = {
        backend_root / "pyproject.toml": out / "pyproject.toml",
        backend_root / "uv.lock": out / "uv.lock",
        repo_root / ".python-version": out / ".python-version",
        backend_root.parent / "scripts" / "uv_toolchain.sh": out / "uv_toolchain.sh",
    }
    missing = [str(source) for source in required_files if not source.is_file()]
    if missing:
        raise RuntimeError(
            f"Cannot create frozen Lightning bundle; required files are missing: {', '.join(missing)}"
        )
    for source, destination in required_files.items():
        shutil.copy2(source, destination)

    for name in BACKEND_SOURCE_DIRS:
        source = backend_root / name
        if not source.is_dir():
            raise RuntimeError(
                f"Cannot create Lightning bundle; backend source directory is missing: {source}"
            )
        shutil.copytree(
            source,
            out / name,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    (out / "startup.sh").write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source ./uv_toolchain.sh
UV_BIN="$(edmg_require_uv)"
PROFILE={profile}
export EDMG_STUDIO_HOME="${{EDMG_STUDIO_HOME:-${{HOME}}/edmg-studio-home}}"
export EDMG_STUDIO_CACHE_DIR="${{EDMG_STUDIO_CACHE_DIR:-${{EDMG_STUDIO_HOME}}/cache}}"
export HF_HOME="${{EDMG_STUDIO_CACHE_DIR}}/huggingface"
export HF_HUB_CACHE="${{HF_HOME}}/hub"
export HF_XET_CACHE="${{HF_HOME}}/xet"
export HF_ASSETS_CACHE="${{HF_HOME}}/assets"
export HUGGINGFACE_HUB_CACHE="${{HF_HUB_CACHE}}"
export HUGGINGFACE_ASSETS_CACHE="${{HF_ASSETS_CACHE}}"
export TRANSFORMERS_CACHE="${{EDMG_STUDIO_CACHE_DIR}}/transformers"
mkdir -p "${{HF_HUB_CACHE}}" "${{HF_XET_CACHE}}" "${{HF_ASSETS_CACHE}}" "${{TRANSFORMERS_CACHE}}"
"${{UV_BIN}}" python install 3.12
"${{UV_BIN}}" lock --check
"${{UV_BIN}}" sync --frozen \\
  --extra "${{PROFILE}}" \\
  --extra core --extra audio --extra asr --extra internal-video --extra aws
echo "Starting EDMG Studio backend on {host}:{port}"
exec "${{UV_BIN}}" run --frozen --no-sync python -m edmg_studio_backend serve --host {host} --port {port}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    legacy_requirements = out / "requirements.txt"
    if legacy_requirements.exists():
        legacy_requirements.unlink()

    manifest = {
        "schema_version": 1,
        "python": "3.12",
        "uv_version": UV_VERSION,
        "accelerator_profile": profile,
        "lock_sha256": _sha256(out / "uv.lock"),
        "capability_extras": ["core", "audio", "asr", "internal-video", "aws"],
    }
    (out / "lightning-bundle-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out / "README.md").write_text(
        f"""# Lightning bundle

This bundle is locked to Python 3.12, uv {UV_VERSION}, and the `{profile}` accelerator profile.
Upload the complete folder to Lightning (or copy it into a Lightning workspace) and run:
- bash startup.sh

It binds to {host}:{port}.
""".strip()
        + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(out / "startup.sh", 0o755)
    except Exception:
        pass
    return {"ok": True, "output_dir": str(out), **manifest}
