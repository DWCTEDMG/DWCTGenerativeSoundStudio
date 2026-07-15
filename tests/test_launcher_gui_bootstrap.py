import importlib.util
import json
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific bootstrap path handling")
pytest.importorskip("tkinter")


def _load_launcher_gui():
    root = Path(__file__).resolve().parents[1]
    module_path = root / "studio" / "edmg-studio" / "tools" / "launcher_gui.py"
    spec = importlib.util.spec_from_file_location("launcher_gui_test_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_saved_path_if_usable_rejects_missing_windows_drive(monkeypatch):
    launcher_gui = _load_launcher_gui()
    original_exists = launcher_gui.Path.exists

    def fake_exists(self):
        if str(self).upper() == "H:\\":
            return False
        return original_exists(self)

    monkeypatch.setattr(launcher_gui.Path, "exists", fake_exists, raising=False)

    assert launcher_gui._saved_path_if_usable(r"H:\Repositories\DWCTGenerativeSoundStudio") is None


def test_ensure_data_dir_env_ignores_unreachable_saved_home(monkeypatch, tmp_path):
    launcher_gui = _load_launcher_gui()
    original_exists = launcher_gui.Path.exists

    def fake_exists(self):
        if str(self).upper() == "H:\\":
            return False
        return original_exists(self)

    bootstrap_path = tmp_path / "bootstrap.json"
    launcher_env_path = tmp_path / "launcher_env.json"
    bootstrap_path.write_text(json.dumps({"studioHome": r"H:\Repositories\DWCTGenerativeSoundStudio\studio\edmg-studio"}), encoding="utf-8")

    monkeypatch.setattr(launcher_gui.Path, "exists", fake_exists, raising=False)
    monkeypatch.setattr(launcher_gui, "LAUNCHER_ENV_PATH", launcher_env_path)
    monkeypatch.setattr(launcher_gui, "_bootstrap_config_path", lambda: bootstrap_path)
    monkeypatch.delenv("EDMG_STUDIO_HOME", raising=False)
    monkeypatch.delenv("EDMG_STUDIO_DATA_DIR", raising=False)

    data_dir = launcher_gui._ensure_data_dir_env()

    assert data_dir == (launcher_gui.STUDIO_DIR / "data").resolve()

    persisted = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    assert persisted["studioHome"] == str(launcher_gui.STUDIO_DIR.resolve())


def test_launcher_accepts_only_python_312_for_the_locked_backend():
    launcher_gui = _load_launcher_gui()

    assert launcher_gui._is_supported_python_version((3, 12, 0))
    assert launcher_gui._is_supported_python_version((3, 12, 99))
    assert not launcher_gui._is_supported_python_version((3, 11, 9))
    assert not launcher_gui._is_supported_python_version((3, 13, 0))


def test_sync_locked_backend_uses_one_fixed_profile_and_capability_set(monkeypatch):
    launcher_gui = _load_launcher_gui()
    calls = {}

    def fake_sync(profile, *, capability_extras, install_uv):
        calls["sync"] = (profile, tuple(capability_extras), install_uv)
        return Path(r"C:\toolchain\uv.exe")

    def fake_run(profile, command, *, capability_extras):
        calls["run"] = (profile, tuple(command), tuple(capability_extras))
        return ["uv", "run", "--frozen", "python", "-c", "verify"], {"PROFILE": profile}

    monkeypatch.setattr(launcher_gui, "sync_frozen_project", fake_sync)
    monkeypatch.setattr(launcher_gui, "frozen_run_command", fake_run)
    monkeypatch.setattr(launcher_gui, "uv_version", lambda _uv: "0.11.28")
    monkeypatch.setattr(launcher_gui, "lock_sha256", lambda: "a" * 64)
    monkeypatch.setattr(launcher_gui, "_run_cmd", lambda *args, **kwargs: 0)

    launcher_gui._sync_locked_backend("cuda", lambda _message: None)

    assert calls["sync"] == ("cuda", tuple(launcher_gui.RUNTIME_CAPABILITY_EXTRAS), True)
    assert calls["run"][0] == "cuda"
    assert calls["run"][2] == tuple(launcher_gui.RUNTIME_CAPABILITY_EXTRAS)
    assert "python" in calls["run"][1]
