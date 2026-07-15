#!/usr/bin/env python3
"""Studio-local support installer for the vendored EDMG Core packages.

This script is intentionally internal to EDMG Studio. It is used by Studio's
setup/repair flow to install or repair the vendored EDMG engine packages inside
the backend environment without relying on the retired root-level legacy
installers.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Sequence


STUDIO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = STUDIO_ROOT / "python_backend"
UV_VERSION = "0.11.28"
MODE_EXTRAS = {
    "minimal": (),
    "standard": ("core",),
    "full": ("core", "audio", "asr", "internal-video", "aws"),
    "dev": ("core", "audio", "asr", "internal-video", "aws"),
}


def _resolve_path(path_value: str | Path) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = STUDIO_ROOT / path
    return path.resolve()


def _managed_env(cache_root: Optional[Path]) -> Optional[dict[str, str]]:
    if cache_root is None:
        return None

    cache_root = _resolve_path(cache_root)
    paths = {
        "tmp": cache_root / "tmp",
        "uv": cache_root / "uv",
        "xdg": cache_root / "xdg",
        "hf": cache_root / "huggingface",
        "transformers": cache_root / "transformers",
        "torch": cache_root / "torch",
        "nltk": cache_root / "nltk_data",
        "whisper": cache_root / "whisper",
        "matplotlib": cache_root / "matplotlib",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "EDMG_CACHE_ROOT": str(cache_root),
            "UV_CACHE_DIR": str(paths["uv"]),
            "XDG_CACHE_HOME": str(paths["xdg"]),
            "HF_HOME": str(paths["hf"]),
            "HUGGINGFACE_HUB_CACHE": str(paths["hf"] / "hub"),
            "TRANSFORMERS_CACHE": str(paths["transformers"]),
            "TORCH_HOME": str(paths["torch"]),
            "NLTK_DATA": str(paths["nltk"]),
            "WHISPER_CACHE_DIR": str(paths["whisper"]),
            "MPLBACKEND": "Agg",
            "MPLCONFIGDIR": str(paths["matplotlib"]),
            "TMP": str(paths["tmp"]),
            "TEMP": str(paths["tmp"]),
        }
    )
    return env


def _run(
    cmd: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
) -> int:
    proc = subprocess.run(list(cmd), cwd=str(cwd) if cwd else None, env=env)
    return int(proc.returncode)


def _backend_env(env: Optional[dict[str, str]] = None) -> dict[str, str]:
    merged = dict(env or os.environ.copy())
    current = merged.get("PYTHONPATH", "").strip()
    backend_str = str(BACKEND_ROOT)
    merged["PYTHONPATH"] = (
        backend_str if not current else os.pathsep.join([backend_str, current])
    )
    return merged


def _resolve_uv() -> str:
    uv = os.getenv("EDMG_UV_BIN", "").strip() or shutil.which("uv")
    if not uv:
        raise RuntimeError(f"uv {UV_VERSION} is required for EDMG Core repair.")
    completed = subprocess.run(
        [uv, "--version"], capture_output=True, text=True, check=False
    )
    actual = completed.stdout.strip()
    actual_parts = actual.split()
    if completed.returncode != 0 or actual_parts[:2] != ["uv", UV_VERSION]:
        raise RuntimeError(f"Expected uv {UV_VERSION}; found {actual or uv!r}.")
    return uv


def _uv_python(uv: str, code: str) -> list[str]:
    return [
        uv,
        "run",
        "--project",
        str(BACKEND_ROOT),
        "--frozen",
        "--no-sync",
        "python",
        "-c",
        code,
    ]


def _post_install(
    uv: str,
    *,
    skip_corpora: bool,
    skip_models: bool,
    skip_whisper: bool,
    require_whisper: bool,
    env: Optional[dict[str, str]] = None,
) -> int:
    if not skip_corpora:
        if (
            _run(
                _uv_python(
                    uv,
                    "import nltk; nltk.download('punkt', quiet=True); nltk.download('stopwords', quiet=True)",
                ),
                cwd=STUDIO_ROOT,
                env=_backend_env(env),
            )
            != 0
        ):
            return 1
        if (
            _run(
                _uv_python(
                    uv,
                    "import nltk; nltk.download('punkt_tab', quiet=True); nltk.download('vader_lexicon', quiet=True)",
                ),
                cwd=STUDIO_ROOT,
                env=_backend_env(env),
            )
            != 0
        ):
            return 1
        if (
            _run(
                _uv_python(uv, "import spacy; print('spacy ok')"),
                cwd=STUDIO_ROOT,
                env=_backend_env(env),
            )
            != 0
        ):
            return 1

    if require_whisper and not skip_models and not skip_whisper:
        if (
            _run(
                _uv_python(
                    uv,
                    "import importlib.util as u; "
                    "spec=u.find_spec('whisper'); "
                    "print('whisper_installed', bool(spec)); "
                    "import sys; "
                    "sys.exit(0) if spec else sys.exit('locked ASR capability is missing whisper')",
                ),
                cwd=STUDIO_ROOT,
                env=_backend_env(env),
            )
            != 0
        ):
            return 1
    return 0


def install(
    *,
    mode: str,
    backend: str,
    venv: Optional[str],
    cache_root: Optional[str],
    skip_torch: bool,
    skip_corpora: bool,
    skip_models: bool,
    skip_whisper: bool,
) -> int:
    managed_env = (
        _managed_env(_resolve_path(cache_root) if cache_root else None)
        or os.environ.copy()
    )
    uv = _resolve_uv()
    resolved_venv: Optional[Path] = None
    if venv:
        resolved_venv = _resolve_path(venv)
        managed_env["UV_PROJECT_ENVIRONMENT"] = str(resolved_venv)

    if skip_torch:
        raise ValueError(
            "--skip-torch is incompatible with locked accelerator profiles"
        )

    profile = "cuda" if backend in {"cu118", "cu121", "cu124"} else backend
    extras = [profile, *MODE_EXTRAS[mode]]
    sync_cmd = [uv, "sync", "--project", str(BACKEND_ROOT), "--frozen"]
    for extra in extras:
        sync_cmd.extend(["--extra", extra])
    if mode == "dev":
        sync_cmd.extend(["--group", "test", "--group", "lint"])

    print(
        f"[edmg-core-installer] Synchronizing frozen {profile} profile ({', '.join(extras)})"
    )
    if (
        _run(
            [uv, "lock", "--project", str(BACKEND_ROOT), "--check"],
            cwd=BACKEND_ROOT,
            env=managed_env,
        )
        != 0
    ):
        return 1
    if _run(sync_cmd, cwd=BACKEND_ROOT, env=managed_env) != 0:
        return 1

    if (
        _post_install(
            uv,
            skip_corpora=skip_corpora,
            skip_models=skip_models,
            skip_whisper=skip_whisper,
            require_whisper="asr" in extras,
            env=managed_env,
        )
        != 0
    ):
        return 1

    print("\n[edmg-core-installer] OK")
    if resolved_venv:
        print(f"  Environment: {resolved_venv}")
    if cache_root:
        print(f"  Cache:    {_resolve_path(cache_root)}")
    print(
        "  Verify:   uv run --project studio/edmg-studio/python_backend --frozen "
        "python studio/edmg-studio/scripts/edmg_core_installer.py verify"
    )
    return 0


def verify() -> int:
    uv = _resolve_uv()
    code = _run(
        _uv_python(
            uv,
            "import enhanced_deforum_music_generator as e, deforum_music as d; "
            "print('enhanced_deforum_music_generator:', e.__file__); "
            "print('deforum_music:', d.__file__)",
        ),
        cwd=STUDIO_ROOT,
        env=_backend_env(),
    )
    if code != 0:
        return code

    code = _run(
        _uv_python(
            uv,
            "from enhanced_deforum_music_generator.deforum_defaults import make_deforum_settings_template; "
            "d=make_deforum_settings_template(); "
            "print('deforum_template_keys', len(d)); "
            "assert 'W' in d and 'H' in d and 'prompts' in d",
        ),
        cwd=STUDIO_ROOT,
        env=_backend_env(),
    )
    return int(code)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="edmg-core-installer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    install_parser = sub.add_parser(
        "install", help="Install or repair the vendored EDMG Core packages"
    )
    install_parser.add_argument(
        "--mode", default="standard", choices=["minimal", "standard", "full", "dev"]
    )
    install_parser.add_argument(
        "--venv", default="", help="Compatibility environment path managed by uv"
    )
    install_parser.add_argument(
        "--cache-root",
        default="",
        help="Shared cache root for uv/HF/Torch/Whisper/temp files",
    )
    install_parser.add_argument("--skip-torch", action="store_true", default=False)
    install_parser.add_argument(
        "--backend",
        default="cpu",
        choices=["cpu", "directml", "cuda", "cu118", "cu121", "cu124"],
    )
    install_parser.add_argument(
        "--cuda",
        action="store_true",
        default=False,
        help="Deprecated alias for --backend cuda",
    )
    install_parser.add_argument(
        "--cuda-version",
        default="",
        choices=["", "118", "121", "124"],
        help="Deprecated convenience alias",
    )
    install_parser.add_argument("--skip-corpora", action="store_true", default=False)
    install_parser.add_argument("--skip-models", action="store_true", default=False)
    install_parser.add_argument("--skip-whisper", action="store_true", default=False)

    sub.add_parser(
        "verify", help="Verify key EDMG Core imports and template generation"
    )

    args = parser.parse_args(argv)

    if args.cmd == "install":
        venv = args.venv.strip() if isinstance(args.venv, str) else ""
        venv = venv or None

        backend = str(args.backend)
        if args.cuda_version:
            backend = "cuda"
        if bool(args.cuda) and not args.cuda_version and args.backend == "cpu":
            backend = "cuda"

        return install(
            mode=str(args.mode),
            backend=backend,
            venv=venv,
            cache_root=str(args.cache_root).strip() or None,
            skip_torch=bool(args.skip_torch),
            skip_corpora=bool(args.skip_corpora),
            skip_models=bool(args.skip_models),
            skip_whisper=bool(args.skip_whisper),
        )

    if args.cmd == "verify":
        return verify()

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
