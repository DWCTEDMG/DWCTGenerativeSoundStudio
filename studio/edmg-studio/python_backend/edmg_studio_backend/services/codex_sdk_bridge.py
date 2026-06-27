from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from ..errors import UserFacingError


def codex_sdk_status() -> dict[str, Any]:
    installed = importlib.util.find_spec("openai_codex") is not None
    enabled = os.getenv("EDMG_CODEX_SDK_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "ok": True,
        "installed": installed,
        "enabled": enabled,
        "model": os.getenv("EDMG_CODEX_SDK_MODEL", "gpt-5.4"),
        "mode": "server_side_read_only",
        "hint": (
            "Set EDMG_CODEX_SDK_ENABLED=1 and install openai-codex to enable Studio render diagnostics."
            if not (installed and enabled)
            else "Codex SDK diagnostics are available."
        ),
    }


def run_render_review(
    *,
    project_dir: Path,
    project_id: str,
    variant_index: int,
    latest_render: dict[str, Any] | None,
    prompt_extra: str | None = None,
) -> dict[str, Any]:
    status = codex_sdk_status()
    if not status["enabled"]:
        raise UserFacingError(
            "Codex SDK integration is disabled",
            hint="Set EDMG_CODEX_SDK_ENABLED=1, restart Studio, then retry.",
            code="CODEX_SDK_DISABLED",
            status_code=400,
        )
    if not status["installed"]:
        raise UserFacingError(
            "Codex SDK is not installed",
            hint='Install it in the Studio backend environment with: pip install openai-codex',
            code="CODEX_SDK_MISSING",
            status_code=400,
        )

    try:
        from openai_codex import Codex, Sandbox  # type: ignore
    except Exception as exc:
        raise UserFacingError(
            "Codex SDK could not be imported",
            hint="Reinstall openai-codex in the active Studio backend Python environment.",
            code="CODEX_SDK_IMPORT_FAILED",
            status_code=500,
        ) from exc

    render_json = latest_render or {}
    prompt = (
        "Review this EDMG Studio render state and return a concise engineering diagnosis. "
        "Focus on why a render might look static, what settings/model path should be changed, "
        "and what verification command or UI action should be tried next. "
        "Do not modify files. "
        f"Project id: {project_id}. Variant index: {variant_index}. "
        f"Project directory: {project_dir}. "
        f"Latest render metadata: {render_json}. "
        f"Extra user note: {prompt_extra or ''}"
    )

    model = str(status.get("model") or "gpt-5.4")
    with Codex() as codex:
        thread = codex.thread_start(model=model, sandbox=Sandbox.read_only)
        result = thread.run(prompt, sandbox=Sandbox.read_only)
        return {
            "ok": True,
            "model": model,
            "thread_id": str(getattr(thread, "id", "") or getattr(thread, "thread_id", "") or ""),
            "final_response": str(getattr(result, "final_response", "") or result),
        }
