from __future__ import annotations

import os
from pathlib import Path

try:
    import carb.settings  # type: ignore
except Exception:
    carb = None  # type: ignore

try:
    import omni.usd  # type: ignore
except Exception:
    omni_usd = None  # type: ignore

try:
    import omni.ext  # type: ignore
except Exception:
    class _ExtBase:
        def on_startup(self, ext_id: str) -> None:
            return None

        def on_shutdown(self) -> None:
            return None

    class _OmniExt:
        IExt = _ExtBase

    class omni:  # type: ignore
        ext = _OmniExt()


def _setting(path: str, default: str = "") -> str:
    try:
        settings = carb.settings.get_settings()  # type: ignore[name-defined]
        value = settings.get(path)
        return str(value or default)
    except Exception:
        return default


def _open_stage(path: str) -> None:
    if not path:
        return
    expanded = Path(os.path.expandvars(path)).expanduser()
    if not expanded.exists():
        print(f"[edmg.usd_schema] sample stage missing: {expanded}")
        return
    try:
        context = omni.usd.get_context()  # type: ignore[name-defined]
        context.open_stage(str(expanded))
        print(f"[edmg.usd_schema] opened sample stage: {expanded}")
    except Exception as exc:
        print(f"[edmg.usd_schema] could not open sample stage: {exc}")


class EdmgUsdSchemaExtension(omni.ext.IExt):  # type: ignore[name-defined]
    def on_startup(self, ext_id: str) -> None:
        self._ext_id = ext_id
        print("[edmg.usd_schema] startup")
        _open_stage(_setting("/edmg/nvidia/sample_stage"))

    def on_shutdown(self) -> None:
        print("[edmg.usd_schema] shutdown")
