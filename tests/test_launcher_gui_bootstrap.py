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
