from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


HF_AUTH_LOGIN_COMMAND = "hf auth login"
HF_AUTH_TOKEN_COMMAND = "hf auth token"
HF_AUTH_WHOAMI_COMMAND = "hf auth whoami"


@dataclass(frozen=True)
class HfTokenCandidate:
    token: str
    source: str


def _looks_like_hf_token(value: str) -> bool:
    stripped = value.strip()
    return len(stripped) >= 20 and not any(ch.isspace() for ch in stripped)


def _add_candidate(
    out: list[HfTokenCandidate],
    seen: set[str],
    token: str | None,
    source: str,
) -> None:
    value = str(token or "").strip()
    if not value or value in seen:
        return
    if not _looks_like_hf_token(value):
        return
    seen.add(value)
    out.append(HfTokenCandidate(value, source))


def _hf_cli_path() -> str | None:
    configured = os.getenv("EDMG_HF_CLI", "").strip()
    if configured:
        return configured
    return shutil.which("hf")


def _hf_cli_token() -> str:
    cli = _hf_cli_path()
    if not cli:
        return ""
    try:
        result = subprocess.run(
            [cli, "auth", "token"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return str(result.stdout or "").strip()


def _hf_hub_cache_token() -> str:
    try:
        from huggingface_hub import get_token  # type: ignore
    except Exception:
        return ""
    try:
        return str(get_token() or "").strip()
    except Exception:
        return ""


def hf_token_candidates(*, secrets_store: Any | None = None) -> list[HfTokenCandidate]:
    """Return available HF auth tokens without exposing their values.

    Priority is explicit env, then the modern `hf` auth/cache path, then Studio's
    saved token. Keeping the CLI/cache ahead of Settings prevents a stale saved
    token from shadowing a fresh `hf auth login` session.
    """
    out: list[HfTokenCandidate] = []
    seen: set[str] = set()
    for name in ("EDMG_HF_TOKEN", "HF_TOKEN", "HUGGINGFACE_TOKEN"):
        _add_candidate(out, seen, os.getenv(name), f"env:{name}")
    _add_candidate(out, seen, _hf_hub_cache_token(), "hf_cache")
    _add_candidate(out, seen, _hf_cli_token(), "hf_cli")
    if secrets_store is not None:
        try:
            _add_candidate(out, seen, secrets_store.get("hf_token"), "settings")
        except Exception:
            pass
    return out


def resolve_hf_token(*, secrets_store: Any | None = None) -> tuple[str, str]:
    candidates = hf_token_candidates(secrets_store=secrets_store)
    if not candidates:
        return "", ""
    chosen = candidates[0]
    return chosen.token, chosen.source


def describe_hf_auth(*, secrets_store: Any | None = None) -> dict[str, Any]:
    token, source = resolve_hf_token(secrets_store=secrets_store)
    return {
        "available": bool(token),
        "token_source": source or None,
        "modern_cli": "hf",
        "cli_available": bool(_hf_cli_path()),
        "login_command": HF_AUTH_LOGIN_COMMAND,
        "whoami_command": HF_AUTH_WHOAMI_COMMAND,
        "token_command": HF_AUTH_TOKEN_COMMAND,
    }
