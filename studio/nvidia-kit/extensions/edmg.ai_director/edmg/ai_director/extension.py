from __future__ import annotations

from .backend_client import BackendClientError, EdmgBackendClient

try:
    import carb.settings  # type: ignore
except Exception:
    carb = None  # type: ignore

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


def _setting(path: str, default: str) -> str:
    try:
        settings = carb.settings.get_settings()  # type: ignore[name-defined]
        value = settings.get(path)
        return str(value or default)
    except Exception:
        return default


class EdmgAiDirectorExtension(omni.ext.IExt):  # type: ignore[name-defined]
    def on_startup(self, ext_id: str) -> None:
        self._ext_id = ext_id
        backend_url = _setting("/edmg/nvidia/backend_url", "http://127.0.0.1:8000")
        self._backend = EdmgBackendClient(base_url=backend_url)
        print(f"[edmg.ai_director] startup backend={backend_url}")
        try:
            status = self._backend.nvidia_status()
            nvidia = status.get("nvidia") if isinstance(status.get("nvidia"), dict) else {}
            print(
                "[edmg.ai_director] NVIDIA "
                f"enabled={nvidia.get('enabled')} profile={nvidia.get('profile') or 'omniverse'}"
            )
        except BackendClientError as exc:
            print(f"[edmg.ai_director] backend status unavailable: {exc}")

    def on_shutdown(self) -> None:
        print("[edmg.ai_director] shutdown")
